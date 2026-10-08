"""Train and evaluate the step 7b models: baselines, the linear model, and the split comparison.

`hri model train` runs `run()`. Everything is evaluated the same way (D-024):
1. Tune on the training years only, with cross-validation grouped by hospital.
2. Refit on all training years, score the test year once.
3. Report ranking metrics within the year, with a bootstrap interval.

Results go to reports/model/ (small, committed, so the README's numbers can be traced) and the
test-year predictions to data/model/ (rebuilt on every run, not committed).
"""

import json
import logging
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.model_selection import GroupKFold, train_test_split

from hri import PROJECT_ROOT
from hri.model.data import DB_PATH, Roles, honest_split, load_roles, load_table
from hri.model.metrics import bootstrap_difference, bootstrap_interval, within_year_metrics, year_metrics
from hri.model.models import (
    earlier_penalty,
    linear_coefficients,
    make_linear,
    split_feature_types,
    training_mean,
)

log = logging.getLogger(__name__)

REPORTS_DIR = PROJECT_ROOT / "reports" / "model"
PREDICTIONS_DIR = PROJECT_ROOT / "data" / "model"
ALPHAS = (0.1, 1.0, 10.0, 100.0, 1000.0, 10000.0)
CV_FOLDS = 5


def grouped_folds(df: pd.DataFrame, n_splits: int = CV_FOLDS, seed: int = 0):
    """Cross-validation folds where each hospital's rows (all its years) fall in one fold only, so
    the model is never validated on a hospital it has seen in training."""
    return GroupKFold(n_splits=n_splits, shuffle=True, random_state=seed).split(df, groups=df["facility_id"])


def tune_linear(train: pd.DataFrame, features: tuple[str, ...], target: str,
                seed: int = 0) -> tuple[float, dict]:
    """Pick the ridge strength with the best grouped-CV AUC for the top penalty quarter."""
    numeric, categorical = split_feature_types(train, features)
    results = {}
    for alpha in ALPHAS:
        scores = []
        for fit_idx, val_idx in grouped_folds(train, seed=seed):
            fit, val = train.iloc[fit_idx], train.iloc[val_idx]
            model = make_linear(numeric, categorical, alpha).fit(fit[list(features)], fit[target])
            scores.append(within_year_metrics(val, model.predict(val[list(features)]), target))
        results[alpha] = {m: float(np.mean([s[m] for s in scores])) for m in scores[0]}
    best = max(results, key=lambda a: results[a]["auc_top_quarter"])
    return best, results[best]


def fit_linear(train: pd.DataFrame, features: tuple[str, ...], target: str, alpha: float):
    numeric, categorical = split_feature_types(train, features)
    return make_linear(numeric, categorical, alpha).fit(train[list(features)], train[target])


def _test_report(test: pd.DataFrame, score: np.ndarray, target: str, n_boot: int, seed: int) -> dict:
    report = year_metrics(test, score, target)
    if n_boot and np.unique(score).size > 1:
        report["interval_95"] = bootstrap_interval(test, score, n=n_boot, seed=seed)
    return report


def _years(df: pd.DataFrame) -> list[str]:
    return sorted(df["fiscal_year"].unique())


def run(db_path: Path = DB_PATH, n_boot: int = 1000, seed: int = 0, reports_dir: Path = REPORTS_DIR,
        predictions_dir: Path = PREDICTIONS_DIR) -> dict:
    roles: Roles = load_roles()
    table = load_table(db_path)
    train, test = honest_split(table, roles.split)
    target = roles.target
    log.info("train %s rows (%s), test %s rows (%s)", f"{len(train):,}", ", ".join(_years(train)),
             f"{len(test):,}", ", ".join(_years(test)))

    models: dict[str, dict] = {}
    predictions = test[["facility_id", "fiscal_year", target, "is_top_quarter_penalty"]].copy()

    def record(name: str, description: str, score: np.ndarray, fitted_on: pd.DataFrame, **extra) -> None:
        log.info("%-28s scoring %s", name, _years(test)[0])
        models[name] = {
            "description": description,
            "train_rows": len(fitted_on),
            "train_years": _years(fitted_on),
            **extra,
            "test": _test_report(test, score, target, n_boot, seed),
        }
        predictions[name] = score

    # Baselines
    fill = float(train[target].median())
    record("training_mean", "Every hospital gets the training-years average.",
           training_mean(train, test, target), train)
    record("penalty_3_years_earlier",
           "The hospital's own penalty from the fiscal year whose period ends before this one starts "
           "(no shared patients); training median where missing.",
           earlier_penalty(table, test, 3, target, fill), train)
    record("penalty_1_year_earlier",
           "Reference only: last year's penalty. Its period shares 2 of 3 years of patients with the "
           "test year, so it shows how good a score looks with overlap.",
           earlier_penalty(table, test, 1, target, fill), train)

    # Linear model on the drivers (the main model's features)
    alpha, cv = tune_linear(train, roles.features, target, seed)
    drivers = fit_linear(train, roles.features, target, alpha)
    record("linear_drivers", "Ridge regression on the driver features, all training years.",
           drivers.predict(test[list(roles.features)]), train,
           features=len(roles.features), alpha=alpha, cv=cv)

    # The variant with prior results exists only for years whose FY-3 file is in the archive, so
    # compare it with the drivers-only model trained on exactly the same rows.
    with_prior = roles.features + roles.variant_features
    prior_years = train.loc[train[list(roles.variant_features)].notna().any(axis=1), "fiscal_year"].unique()
    prior_train = train[train["fiscal_year"].isin(prior_years)]
    for name, features, description in [
        ("linear_drivers_same_rows", roles.features,
         "Ridge on the drivers, trained only on the years the prior-results variant can use."),
        ("linear_with_prior", with_prior,
         "Ridge on the drivers plus the hospital's results from three fiscal years earlier."),
    ]:
        a, c = tune_linear(prior_train, features, target, seed)
        m = fit_linear(prior_train, features, target, a)
        record(name, description, m.predict(test[list(features)]), prior_train,
               features=len(features), alpha=a, cv=c)

    # The trap, in numbers: the same drivers model under two naive splits
    naive = {}
    random_train, random_test = train_test_split(table, test_size=0.2, random_state=seed)
    m = fit_linear(random_train, roles.features, target, alpha)
    naive["random_rows"] = {
        "description": "Random 80/20 split of all hospital-years: the same hospital and overlapping "
                       "periods on both sides.",
        **within_year_metrics(random_test, m.predict(random_test[list(roles.features)]), target),
    }
    overlap_train = table[table[roles.split].isin(["train", "overlap_unused"])]
    m = fit_linear(overlap_train, roles.features, target, alpha)
    naive["overlapping_years_in_training"] = {
        "description": "Train on FY 2020 - FY 2025, test on the test year: FY 2024-2025 share "
                       "patients with it.",
        **year_metrics(test, m.predict(test[list(roles.features)]), target),
    }
    naive["honest"] = {
        "description": "Train on the training years only (the linear_drivers result).",
        **{k: v for k, v in models["linear_drivers"]["test"].items() if k != "interval_95"},
    }

    # Paired comparisons: is a model really better than its reference, on the same hospitals?
    comparisons = {}
    if n_boot:
        for better, reference in [("linear_drivers", "penalty_3_years_earlier"),
                                  ("linear_drivers", "training_mean"),
                                  ("linear_with_prior", "linear_drivers_same_rows")]:
            # A constant score has no rank correlation, so the training mean gets AUC only.
            metrics = ["auc_top_quarter"] + ([] if reference == "training_mean" else ["spearman"])
            comparisons[f"{better} vs {reference}"] = {
                metric: bootstrap_difference(test, predictions[better].to_numpy(),
                                             predictions[reference].to_numpy(), metric, n_boot, seed)
                for metric in metrics
            }

    results = {
        "table": {"rows": len(table), "train_rows": len(train), "train_years": _years(train),
                  "test_rows": len(test), "test_year": _years(test)[0]},
        "selection_metric": "auc_top_quarter, grouped cross-validation on the training years",
        "models": models,
        "paired_comparisons": comparisons,
        "naive_split_comparison": naive,
    }
    reports_dir.mkdir(parents=True, exist_ok=True)
    metrics_file = reports_dir / "metrics.json"
    metrics_file.write_text(json.dumps(_rounded(results), indent=2) + "\n", encoding="utf-8")
    linear_coefficients(drivers).round(4).to_csv(reports_dir / "linear_coefficients.csv", index=False)
    predictions_dir.mkdir(parents=True, exist_ok=True)
    predictions.to_parquet(predictions_dir / "test_predictions.parquet", index=False)
    log.info("wrote %s", metrics_file)
    return results


def _rounded(value):
    if isinstance(value, float):
        return None if np.isnan(value) else round(value, 4)
    if isinstance(value, dict):
        return {str(k): _rounded(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_rounded(v) for v in value]
    if isinstance(value, np.integer | np.floating):
        return _rounded(value.item())
    return value


def summary(results: dict) -> str:
    """The results as a text table for the terminal."""
    lines = [f"{'model':28s} {'AUC top 25%':>18s} {'Spearman':>18s} {'AUC pen.':>9s} {'MAE pp':>7s}"]

    def cell(test: dict, metric: str) -> str:
        value = test[metric]
        if value is None or (isinstance(value, float) and np.isnan(value)):
            return f"{'-':>18s}"
        low_high = test.get("interval_95", {}).get(metric)
        return f"{value:6.3f} [{low_high[0]:.2f}-{low_high[1]:.2f}]" if low_high else f"{value:6.3f}{'':12s}"

    for name, m in results["models"].items():
        t = m["test"]
        lines.append(f"{name:28s} {cell(t, 'auc_top_quarter')} {cell(t, 'spearman')} "
                     f"{t['auc_penalized']:9.3f} {t['mae_pct']:7.3f}")
    lines.append("")
    lines.append("Paired differences (95% interval, share of resamples where the first is better):")
    for name, by_metric in results.get("paired_comparisons", {}).items():
        for metric, d in by_metric.items():
            low, high = d["interval_95"]
            lines.append(f"  {name:52s} {metric:16s} {d['difference']:+.3f} [{low:+.3f} to {high:+.3f}]  "
                         f"{d['share_of_resamples_better']:.0%}")
    lines.append("")
    lines.append("Same drivers model, different splits:")
    for name, m in results["naive_split_comparison"].items():
        lines.append(f"  {name:30s} AUC top 25% {m['auc_top_quarter']:.3f}   Spearman {m['spearman']:.3f}")
    return "\n".join(lines)
