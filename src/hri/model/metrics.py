"""How a penalty model is judged (D-024).

The main metrics are about **ranking within one fiscal year**: does the model put the hospitals
with the largest penalties first? The level of penalties shifts between years for reasons no
driver explains (it roughly halved from FY 2023), so level errors are reported but not used to
choose between models.

- auc_top_quarter: chance that a random top-quarter hospital is scored above a random other one.
  0.5 = guessing, 1.0 = perfect.
- auc_penalized: the same for "penalized at all" (75-83% of hospitals, a weak question).
- spearman: rank correlation between score and actual reduction.
- mae_pct / mean_predicted_pct: level error in percentage points, for models that predict a level.
"""

import numpy as np
import pandas as pd
from sklearn.metrics import mean_absolute_error, roc_auc_score

RANKING_METRICS = ("auc_top_quarter", "auc_penalized", "spearman")


def _auc(labels: np.ndarray, score: np.ndarray) -> float:
    labels = labels.astype(bool)
    if labels.all() or not labels.any():
        return float("nan")
    return float(roc_auc_score(labels, score))


def _spearman(a: np.ndarray, b: np.ndarray) -> float:
    a, b = pd.Series(a).rank(), pd.Series(b).rank()
    if a.nunique() < 2 or b.nunique() < 2:
        return float("nan")  # a constant score has no ranking
    return float(a.corr(b))


def year_metrics(year: pd.DataFrame, score: np.ndarray, target: str = "payment_reduction_pct") -> dict:
    """Metrics for one fiscal year. A constant score gets AUC 0.5 by definition."""
    score = np.asarray(score, dtype=float)
    return {
        "auc_top_quarter": _auc(year["is_top_quarter_penalty"].to_numpy(), score),
        "auc_penalized": _auc(year["is_penalized"].to_numpy(), score),
        "spearman": _spearman(year[target].to_numpy(), score),
        "mae_pct": float(mean_absolute_error(year[target], score)),
        "mean_actual_pct": float(year[target].mean()),
        "mean_predicted_pct": float(score.mean()),
        "hospitals": len(year),
    }


def within_year_metrics(df: pd.DataFrame, score: np.ndarray, target: str = "payment_reduction_pct") -> dict:
    """Metrics computed separately for each fiscal year in `df`, then averaged (weighted by the
    number of hospitals). Pooling years would reward a model for telling years apart, which is
    not the question."""
    df = df.assign(_score=np.asarray(score, dtype=float))
    per_year = {fy: year_metrics(g, g["_score"].to_numpy(), target) for fy, g in df.groupby("fiscal_year")}
    weights = np.array([m["hospitals"] for m in per_year.values()], dtype=float)
    averaged = {}
    for name in ("auc_top_quarter", "auc_penalized", "spearman", "mae_pct"):
        values = np.array([m[name] for m in per_year.values()])
        ok = ~np.isnan(values)
        averaged[name] = float(np.average(values[ok], weights=weights[ok])) if ok.any() else float("nan")
    return averaged


def bootstrap_interval(
    df: pd.DataFrame,
    score: np.ndarray,
    metrics: tuple[str, ...] = ("auc_top_quarter", "spearman"),
    n: int = 1000,
    seed: int = 0,
    level: float = 0.95,
) -> dict[str, tuple[float, float]]:
    """Percentile interval for each metric over one fiscal year, resampling hospitals with
    replacement. One test year gives one estimate; the interval shows how much it would move with
    a different set of hospitals of the same kind."""
    if df["fiscal_year"].nunique() != 1:
        raise ValueError("bootstrap_interval scores one fiscal year at a time")
    columns = {
        "auc_top_quarter": lambda i: _auc(top_quarter[i], score[i]),
        "auc_penalized": lambda i: _auc(penalized[i], score[i]),
        "spearman": lambda i: _spearman(actual[i], score[i]),
    }
    top_quarter, penalized = df["is_top_quarter_penalty"].to_numpy(), df["is_penalized"].to_numpy()
    actual, score = df["payment_reduction_pct"].to_numpy(), np.asarray(score, dtype=float)
    rng = np.random.default_rng(seed)
    draws: dict[str, list[float]] = {m: [] for m in metrics}
    for _ in range(n):
        idx = rng.integers(0, len(df), len(df))
        for m in metrics:
            draws[m].append(columns[m](idx))
    tail = (1 - level) / 2 * 100
    return {m: (float(np.nanpercentile(v, tail)), float(np.nanpercentile(v, 100 - tail)))
            for m, v in draws.items()}


def bootstrap_difference(
    df: pd.DataFrame, score: np.ndarray, reference: np.ndarray, metric: str = "auc_top_quarter",
    n: int = 1000, seed: int = 0, level: float = 0.95,
) -> dict:
    """How much better `score` is than `reference` on `metric`, with a paired bootstrap: each
    resample draws the same hospitals for both, so differences in which hospitals were drawn
    cancel out. Separate intervals that overlap can still hide a clear paired difference."""
    point = within_year_metrics(df, score)[metric] - within_year_metrics(df, reference)[metric]
    rng = np.random.default_rng(seed)
    labels = {"auc_top_quarter": df["is_top_quarter_penalty"], "auc_penalized": df["is_penalized"]}
    score, reference = np.asarray(score, dtype=float), np.asarray(reference, dtype=float)
    diffs = []
    for _ in range(n):
        idx = rng.integers(0, len(df), len(df))
        if metric == "spearman":
            actual = df["payment_reduction_pct"].to_numpy()[idx]
            diffs.append(_spearman(actual, score[idx]) - _spearman(actual, reference[idx]))
        else:
            y = labels[metric].to_numpy()[idx]
            diffs.append(_auc(y, score[idx]) - _auc(y, reference[idx]))
    tail = (1 - level) / 2 * 100
    return {"difference": float(point),
            "interval_95": (float(np.nanpercentile(diffs, tail)), float(np.nanpercentile(diffs, 100 - tail))),
            "share_of_resamples_better": float(np.mean(np.array(diffs) > 0))}
