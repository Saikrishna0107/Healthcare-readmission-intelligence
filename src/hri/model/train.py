"""Train and evaluate the step 7 models: baselines, ridge, LightGBM and EBM (D-009, D-024).

`hri model train` runs `run()`. Every model family is evaluated the same way:
1. Tune on the training years only, with cross-validation grouped by hospital.
2. Refit the best settings on all training years, score the test year once.
3. Report ranking metrics within the year, with a bootstrap interval.

The final model is chosen from the cross-validation scores, never from the test year (D-009).
Results go to reports/model/ (small, committed, so the README's numbers can be traced); the
test-year predictions and the fitted models go to data/model/ (rebuilt on every run).
"""

import json
import logging
from itertools import product
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.model_selection import GroupKFold, train_test_split

from hri import PROJECT_ROOT
from hri.model.data import DB_PATH, Roles, honest_split, load_roles, load_table
from hri.model.metrics import bootstrap_difference, bootstrap_interval, within_year_metrics, year_metrics
from hri.model.models import (
    earlier_penalty,
    linear_coefficients,
    make_ebm,
    make_lightgbm,
    make_linear,
    split_feature_types,
    training_mean,
)

log = logging.getLogger(__name__)

REPORTS_DIR = PROJECT_ROOT / "reports" / "model"
MODEL_DIR = PROJECT_ROOT / "data" / "model"
CV_FOLDS = 5

# Settings tried for each family. Small on purpose: about 12,000 rows and a weak signal reward
# simple, heavily regularized models, and every extra setting is another chance to fit noise.
GRIDS: dict[str, list[dict]] = {
    "linear": [{"alpha": a} for a in (0.1, 1.0, 10.0, 100.0, 1000.0, 10000.0)],
    "lightgbm": [
        {"num_leaves": leaves, "min_child_samples": min_rows, "n_estimators": trees}
        for leaves, min_rows, trees in product((7, 15, 31), (50, 200), (300, 600))
    ],
    # EBM: one setting, because each fit takes about 1.5 minutes. 10 pair effects instead of the
    # default 5 per feature (225 here; too slow to finish in a trial run): a few pairs keep the model
    # readable, which is the reason to use an EBM at all.
    "ebm": [{"interactions": 10, "outer_bags": 8}],
}
# When cross-validation scores are this close, prefer the easier model to explain (D-009).
SIMPLER_FIRST = ("linear", "ebm", "lightgbm")
TIE_MARGIN = 0.01


def grouped_folds(df: pd.DataFrame, n_splits: int = CV_FOLDS, seed: int = 0):
    """Cross-validation folds where each hospital's rows (all its years) fall in one fold only, so
    the model is never validated on a hospital it has seen in training."""
    return GroupKFold(n_splits=n_splits, shuffle=True, random_state=seed).split(df, groups=df["facility_id"])


def make_model(family: str, df: pd.DataFrame, features: tuple[str, ...], params: dict, seed: int = 0):
    numeric, categorical = split_feature_types(df, features)
    if family == "linear":
        return make_linear(numeric, categorical, **params)
    if family == "lightgbm":
        return make_lightgbm(categorical, seed, **params)
    if family == "ebm":
        return make_ebm(seed, **params)
    raise ValueError(f"unknown model family {family!r}")


def fit(family: str, train: pd.DataFrame, features: tuple[str, ...], target: str, params: dict,
        seed: int = 0):
    return make_model(family, train, features, params, seed).fit(train[list(features)], train[target])


def tune(family: str, train: pd.DataFrame, features: tuple[str, ...], target: str,
         seed: int = 0) -> tuple[dict, dict]:
    """Pick the settings with the best grouped-CV AUC for the top penalty quarter. Returns the
    settings and their average cross-validation metrics."""
    folds = list(grouped_folds(train, seed=seed))
    results = []
    for params in GRIDS[family]:
        scores = []
        for fit_idx, val_idx in folds:
            fitted, val = train.iloc[fit_idx], train.iloc[val_idx]
            model = fit(family, fitted, features, target, params, seed)
            scores.append(within_year_metrics(val, model.predict(val[list(features)]), target))
        results.append((params, {m: float(np.mean([s[m] for s in scores])) for m in scores[0]}))
    return max(results, key=lambda r: r[1]["auc_top_quarter"])


def choose(cv_auc: dict[str, float]) -> str:
    """The family to use: the best cross-validated AUC, unless a simpler family is within
    TIE_MARGIN of it. Uses training-year scores only."""
    best = max(cv_auc.values())
    return next(f for f in SIMPLER_FIRST if f in cv_auc and cv_auc[f] >= best - TIE_MARGIN)


def _test_report(test: pd.DataFrame, score: np.ndarray, target: str, n_boot: int, seed: int) -> dict:
    report = year_metrics(test, score, target)
    if n_boot and np.unique(score).size > 1:
        report["interval_95"] = bootstrap_interval(test, score, n=n_boot, seed=seed)
    return report


def _years(df: pd.DataFrame) -> list[str]:
    return sorted(df["fiscal_year"].unique())


def run(db_path: Path = DB_PATH, n_boot: int = 1000, seed: int = 0, reports_dir: Path = REPORTS_DIR,
        model_dir: Path = MODEL_DIR, families: tuple[str, ...] = ("linear", "lightgbm", "ebm")) -> dict:
    roles: Roles = load_roles()
    table = load_table(db_path)
    train, test = honest_split(table, roles.split)
    target = roles.target
    drivers = roles.features
    log.info("train %s rows (%s), test %s rows (%s)", f"{len(train):,}", ", ".join(_years(train)),
             f"{len(test):,}", ", ".join(_years(test)))

    models: dict[str, dict] = {}
    fitted: dict[str, object] = {}
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

    def train_and_record(name: str, family: str, description: str, rows: pd.DataFrame,
                         features: tuple[str, ...]) -> None:
        log.info("%-28s tuning %d setting(s) x %d folds", name, len(GRIDS[family]), CV_FOLDS)
        params, cv = tune(family, rows, features, target, seed)
        model = fit(family, rows, features, target, params, seed)
        fitted[name] = model
        record(name, description, model.predict(test[list(features)]), rows,
               family=family, features=len(features), params=params, cv=cv)

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

    # The three families on the drivers (the main model's features)
    descriptions = {
        "linear": "Ridge regression",
        "lightgbm": "LightGBM gradient-boosted trees",
        "ebm": "Explainable Boosting Machine",
    }
    for family in families:
        train_and_record(f"{family}_drivers", family, f"{descriptions[family]} on the driver features.",
                         train, drivers)
    chosen = choose({f: models[f"{f}_drivers"]["cv"]["auc_top_quarter"] for f in families})
    log.info("chosen from cross-validation: %s", chosen)

    # The variant with prior results exists only for years whose FY-3 file is in the archive, so
    # compare it with the chosen family on the drivers, trained on exactly the same rows.
    prior_years = train.loc[train[list(roles.variant_features)].notna().any(axis=1), "fiscal_year"].unique()
    prior_train = train[train["fiscal_year"].isin(prior_years)]
    train_and_record(f"{chosen}_drivers_same_rows", chosen,
                     f"{descriptions[chosen]} on the drivers, trained only on the years the prior-results "
                     "variant can use.", prior_train, drivers)
    train_and_record(f"{chosen}_with_prior", chosen,
                     f"{descriptions[chosen]} on the drivers plus the hospital's results from three fiscal "
                     "years earlier.", prior_train, drivers + roles.variant_features)

    # The trap, in numbers: each driver model under two naive splits, with its tuned settings
    naive = {}
    random_train, random_test = train_test_split(table, test_size=0.2, random_state=seed)
    overlap_train = table[table[roles.split].isin(["train", "overlap_unused"])]
    for family in families:
        params = models[f"{family}_drivers"]["params"]
        random_model = fit(family, random_train, drivers, target, params, seed)
        overlap_model = fit(family, overlap_train, drivers, target, params, seed)
        honest = models[f"{family}_drivers"]["test"]
        naive[family] = {
            "random_rows": within_year_metrics(
                random_test, random_model.predict(random_test[list(drivers)]), target)["auc_top_quarter"],
            "overlapping_years_in_training": year_metrics(
                test, overlap_model.predict(test[list(drivers)]), target)["auc_top_quarter"],
            "honest": honest["auc_top_quarter"],
        }

    # Paired comparisons: is a model really better than its reference, on the same hospitals?
    pairs = [(f"{f}_drivers", "linear_drivers") for f in families if f != "linear"]
    pairs += [(f"{chosen}_drivers", "penalty_3_years_earlier"),
              (f"{chosen}_with_prior", f"{chosen}_drivers_same_rows")]
    comparisons = {}
    if n_boot:
        for better, reference in pairs:
            comparisons[f"{better} vs {reference}"] = {
                metric: bootstrap_difference(test, predictions[better].to_numpy(),
                                             predictions[reference].to_numpy(), metric, n_boot, seed)
                for metric in ("auc_top_quarter", "spearman")
            }

    results = {
        "table": {"rows": len(table), "train_rows": len(train), "train_years": _years(train),
                  "test_rows": len(test), "test_year": _years(test)[0]},
        "selection": {
            "metric": "auc_top_quarter, 5-fold cross-validation grouped by hospital, training years only",
            "rule": f"best CV AUC; a simpler family ({' < '.join(SIMPLER_FIRST)}) wins within {TIE_MARGIN}",
            "chosen": chosen,
        },
        "models": models,
        "paired_comparisons": comparisons,
        "naive_split_auc_top_quarter": naive,
    }
    reports_dir.mkdir(parents=True, exist_ok=True)
    metrics_file = reports_dir / "metrics.json"
    metrics_file.write_text(json.dumps(_rounded(results), indent=2) + "\n", encoding="utf-8")
    if "linear_drivers" in fitted:
        linear_coefficients(fitted["linear_drivers"]).round(4).to_csv(
            reports_dir / "linear_coefficients.csv", index=False)
    model_dir.mkdir(parents=True, exist_ok=True)
    predictions.to_parquet(model_dir / "test_predictions.parquet", index=False)
    # Fitted models, for the explanations (notebook 03). Pickles: load only files you made.
    joblib.dump({"models": fitted, "drivers": drivers, "variant_features": roles.variant_features,
                 "chosen": chosen}, model_dir / "models.joblib")
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
    lines = [f"{'model':28s} {'CV AUC':>7s} {'AUC top 25%':>18s} {'Spearman':>18s} "
             f"{'AUC pen.':>9s} {'MAE pp':>7s}"]

    def cell(test: dict, metric: str) -> str:
        value = test[metric]
        if value is None or (isinstance(value, float) and np.isnan(value)):
            return f"{'-':>18s}"
        low_high = test.get("interval_95", {}).get(metric)
        return f"{value:6.3f} [{low_high[0]:.2f}-{low_high[1]:.2f}]" if low_high else f"{value:6.3f}{'':12s}"

    for name, m in results["models"].items():
        t = m["test"]
        cv = f"{m['cv']['auc_top_quarter']:7.3f}" if "cv" in m else f"{'':7s}"
        lines.append(f"{name:28s} {cv} {cell(t, 'auc_top_quarter')} {cell(t, 'spearman')} "
                     f"{t['auc_penalized']:9.3f} {t['mae_pct']:7.3f}")
    lines.append(f"\nChosen from cross-validation: {results['selection']['chosen']}")
    lines.append("")
    lines.append("Paired differences (95% interval, share of resamples where the first is better):")
    for name, by_metric in results.get("paired_comparisons", {}).items():
        for metric, d in by_metric.items():
            low, high = d["interval_95"]
            lines.append(f"  {name:52s} {metric:16s} {d['difference']:+.3f} [{low:+.3f} to {high:+.3f}]  "
                         f"{d['share_of_resamples_better']:.0%}")
    lines.append("")
    lines.append("AUC top 25% of each driver model under different splits:")
    lines.append(f"  {'':10s} {'random rows':>12s} {'overlap yrs':>12s} {'honest':>8s}")
    for family, m in results["naive_split_auc_top_quarter"].items():
        lines.append(f"  {family:10s} {m['random_rows']:12.3f} {m['overlapping_years_in_training']:12.3f} "
                     f"{m['honest']:8.3f}")
    return "\n".join(lines)
