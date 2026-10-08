import marimo

__generated_with = "0.25.0"
app = marimo.App(width="medium", app_title="03 · Model results")


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    # 03 · Model results

    **Goal of this notebook:** show how well each model ranks hospitals by HRRP penalty on a year
    it has never seen, and what drives its predictions.

    Everything here comes from `hri model train` (code in `src/hri/model/`): the metrics from
    `reports/model/metrics.json`, the fitted models from `data/model/`. The rules (D-024):

    - **Train** on FY 2020 - FY 2023, **test** once on FY 2026, whose patients do not overlap.
    - Settings are tuned and the final model is **chosen by cross-validation grouped by
      hospital**, on the training years only; the test year only reports.
    - The main metric is **AUC for the top quarter of penalties within the year**: the chance that
      a random top-quarter hospital is scored above a random other hospital (0.5 = guessing).
    """)
    return


@app.cell
def _():
    import json

    import joblib
    import marimo as mo
    import matplotlib.pyplot as plt
    import numpy as np
    import pandas as pd
    import shap
    from matplotlib.patches import Patch

    from hri import PROJECT_ROOT
    from hri.model import honest_split, load_roles, load_table
    return PROJECT_ROOT, Patch, honest_split, joblib, json, load_roles, load_table, mo, np, pd, plt, shap


@app.cell
def _(PROJECT_ROOT, honest_split, joblib, json, load_roles, load_table, plt):
    IMAGES = PROJECT_ROOT / "images"
    BLUE, ORANGE, INK, MUTED, GRID = "#2a78d6", "#eb6834", "#0b0b0b", "#52514e", "#e4e3df"
    GREY = "#b9b8b3"
    plt.rcParams.update({
        "figure.dpi": 110, "savefig.dpi": 150, "savefig.bbox": "tight",
        "axes.spines.top": False, "axes.spines.right": False,
        "axes.edgecolor": MUTED, "axes.labelcolor": MUTED,
        "xtick.color": MUTED, "ytick.color": MUTED,
        "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.8, "axes.axisbelow": True,
        "axes.titlesize": 12, "axes.titleweight": "bold", "axes.titlecolor": INK,
        "axes.titlelocation": "left", "font.size": 10,
    })

    results = json.loads((PROJECT_ROOT / "reports" / "model" / "metrics.json").read_text(encoding="utf-8"))
    # Pickled models written by `hri model train` on this machine (never load pickles you did not make).
    bundle = joblib.load(PROJECT_ROOT / "data" / "model" / "models.joblib")
    roles = load_roles()
    table = load_table()
    train, test = honest_split(table)
    return BLUE, GREY, IMAGES, INK, MUTED, ORANGE, bundle, results, roles, test


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## 1 · How well does each model rank hospitals?
    """)
    return


@app.cell
def _(mo, pd, results):
    def _interval(t, metric):
        low_high = t.get("interval_95", {}).get(metric)
        return f"{low_high[0]:.3f} - {low_high[1]:.3f}" if low_high else ""

    comparison = pd.DataFrame([
        {"model": name,
         "cv_auc_top_quarter": m.get("cv", {}).get("auc_top_quarter"),
         "test_auc_top_quarter": m["test"]["auc_top_quarter"],
         "interval_95": _interval(m["test"], "auc_top_quarter"),
         "test_spearman": m["test"]["spearman"],
         "test_auc_penalized": m["test"]["auc_penalized"],
         "train_years": ", ".join(m["train_years"])}
        for name, m in results["models"].items()
    ])
    mo.vstack([
        mo.md(f"**Chosen from cross-validation:** `{results['selection']['chosen']}` "
              f"(rule: {results['selection']['rule']})"),
        mo.plain(comparison),
    ])
    return (comparison,)


@app.cell
def _(BLUE, GREY, IMAGES, MUTED, ORANGE, Patch, plt, results):
    _rows = list(results["models"].items())[::-1]
    _fig, _ax = plt.subplots(figsize=(8, 4.2))
    for _i, (_name, _m) in enumerate(_rows):
        _t = _m["test"]
        _overlap = _name == "penalty_1_year_earlier"
        _color = GREY if "family" not in _m else (ORANGE if _name.endswith("with_prior") else BLUE)
        _low, _high = _t.get("interval_95", {}).get("auc_top_quarter", (_t["auc_top_quarter"],) * 2)
        _ax.plot([_low, _high], [_i, _i], color=_color, lw=2.5, alpha=0.6)
        _ax.plot(_t["auc_top_quarter"], _i, "o", color=_color, mfc="white" if _overlap else _color, ms=7)
    _ax.set_yticks(range(len(_rows)), [n for n, _ in _rows])
    _ax.axvline(0.5, color=MUTED, lw=0.8, ls=":")
    _ax.set_xlabel("AUC, top quarter of FY 2026 penalties (95% interval)")
    _ax.set_title("Finding the hospitals with the largest penalties")
    _ax.legend(handles=[Patch(color=GREY, label="baseline / reference"), Patch(color=BLUE, label="drivers only"),
                        Patch(color=ORANGE, label="drivers + results 3 years earlier")],
               frameon=False, loc="upper center", bbox_to_anchor=(0.45, -0.14), ncols=3, fontsize=8)
    _fig.savefig(IMAGES / "09_model_comparison.png")
    _fig
    return


@app.cell
def _(mo, pd, results):
    paired = pd.DataFrame([
        {"comparison": name, "metric": metric, "difference": d["difference"],
         "interval_95": f"{d['interval_95'][0]:+.3f} to {d['interval_95'][1]:+.3f}",
         "share_of_resamples_better": d["share_of_resamples_better"]}
        for name, by_metric in results["paired_comparisons"].items() for metric, d in by_metric.items()
    ])
    mo.vstack([mo.md("**Paired bootstrap** (the same resampled hospitals for both models):"), mo.plain(paired)])
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## 2 · The split trap, model by model

    The same tuned settings, trained three ways and scored on held-out rows: a **random split** of
    all hospital-years; training that **includes FY 2024-2025** (which share patients with the test
    year); and the **honest** split.
    """)
    return


@app.cell
def _(BLUE, GREY, IMAGES, ORANGE, mo, np, pd, plt, results):
    trap = pd.DataFrame(results["naive_split_auc_top_quarter"]).T
    _fig, _ax = plt.subplots(figsize=(7, 3.4))
    _x = np.arange(len(trap))
    for _k, (_column, _color, _label) in enumerate([
        ("random_rows", GREY, "random split"), ("overlapping_years_in_training", ORANGE, "overlapping years"),
        ("honest", BLUE, "honest (FY 2020-23 -> FY 2026)")]):
        _ax.bar(_x + (_k - 1) * 0.26, trap[_column], width=0.26, color=_color, label=_label)
    _ax.set_xticks(_x, trap.index)
    _ax.set_ylim(0.5, max(0.8, trap.max().max() + 0.02))
    _ax.set_ylabel("AUC, top quarter")
    _ax.set_title("Same model, different splits")
    _ax.legend(frameon=False, ncols=3, loc="upper left", fontsize=8)
    _fig.savefig(IMAGES / "10_split_trap.png")
    mo.vstack([mo.plain(trap.round(3)), _fig])
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## 3 · What drives the predictions?

    Two independent explanations, for two different models:

    - **SHAP** for LightGBM: for each hospital, how much each feature pushed its prediction away
      from the average. Features are summed **by family** (survey, volume, county, ...) because
      correlated features share credit unpredictably; a family is a more stable answer than any
      one survey question.
    - **EBM**: the model *is* a sum of one learned curve per feature (plus 10 pairs), so each
      hospital's prediction splits exactly into one score per term, read directly from the model.

    Both are grouped the same way: **per hospital, add up the contributions within a family, then
    average the absolute values.** The order matters. Adding up each feature's importance instead
    would over-count families of correlated features that push in opposite directions (county
    housing and food insecurity correlate at 0.97 across hospitals; see the curves below).

    If both models point to the same families, the explanation is a property of the data, not of
    one algorithm.
    """)
    return


@app.cell
def _(bundle, np, pd, roles, shap, test):
    _pipeline = bundle["models"]["lightgbm_drivers"]
    _drivers = list(bundle["drivers"])
    _X = _pipeline.named_steps["categories"].transform(test[_drivers])
    shap_values = shap.TreeExplainer(_pipeline.named_steps["lightgbm"]).shap_values(_X)
    shap_frame = pd.DataFrame(shap_values, columns=_drivers, index=test.index)

    _by_group = shap_frame.T.groupby(roles.groups).sum().T  # per hospital, summed within each family
    shap_groups = _by_group.abs().mean().sort_values(ascending=False).rename("mean_abs_shap_pp")
    shap_features = pd.DataFrame({
        "mean_abs_shap_pp": shap_frame.abs().mean(),
        # Direction: does a higher value push the prediction up (+1) or down (-1)? Numeric only.
        "direction": [np.sign(test[f].corr(shap_frame[f])) if pd.api.types.is_numeric_dtype(test[f])
                      else np.nan for f in _drivers],
        "group": [roles.groups[f] for f in _drivers],
    }).sort_values("mean_abs_shap_pp", ascending=False)
    return shap_features, shap_groups


@app.cell
def _(bundle, pd, roles, test):
    ebm = bundle["models"]["ebm_drivers"]
    # One score per hospital per term; they add up (with the intercept) to the prediction.
    _scores = pd.DataFrame(ebm.eval_terms(test[list(bundle["drivers"])]), columns=ebm.term_names_)
    _family = [roles.groups.get(t, "pairs") for t in ebm.term_names_]  # "a & b" terms are pairs
    ebm_groups = (_scores.T.groupby(_family).sum().T.abs().mean()
                  .sort_values(ascending=False).rename("mean_abs_score_pp"))
    ebm_terms = (pd.DataFrame({"term": ebm.term_names_, "mean_abs_score_pp": _scores.abs().mean().values,
                               "group": _family})
                 .sort_values("mean_abs_score_pp", ascending=False).reset_index(drop=True))
    return ebm, ebm_groups, ebm_terms


@app.cell
def _(BLUE, IMAGES, ORANGE, ebm_groups, mo, pd, plt, shap_groups):
    _fig, (_a, _b) = plt.subplots(1, 2, figsize=(10, 3.6))
    _s = shap_groups.iloc[::-1]
    _a.barh(_s.index.str.replace("_", " "), _s.values, color=BLUE)
    _a.set_title("LightGBM: mean |SHAP| by family")
    _a.set_xlabel("percentage points of payment reduction")
    _e = ebm_groups.iloc[::-1]
    _b.barh(_e.index.str.replace("_", " "), _e.values, color=ORANGE)
    _b.set_title("EBM: mean |score| by family")
    _b.set_xlabel("percentage points of payment reduction")
    _fig.tight_layout()
    _fig.savefig(IMAGES / "11_drivers_by_family.png")
    mo.vstack([mo.plain(pd.concat([shap_groups.rename("lightgbm_shap"), ebm_groups.rename("ebm")], axis=1)
                        .round(4)), _fig])
    return


@app.cell
def _(ebm_terms, mo, shap_features):
    mo.hstack([
        mo.vstack([mo.md("**LightGBM, top features (SHAP)**"), mo.plain(shap_features.head(15).round(4))]),
        mo.vstack([mo.md("**EBM, top terms**"), mo.plain(ebm_terms.head(15).round(4))]),
    ])
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ### The shapes the EBM learned

    Each curve is the EBM's contribution of one feature to the predicted reduction (percentage
    points), holding the others fixed. These are the model itself, not an approximation. Missing
    values get their own score, not shown on the curves (most are hospitals without survey data).

    Shown: the strongest feature of each family. **Read single county curves with care.** County
    measures are so correlated that the model can split one effect between two of them with
    opposite signs (housing insecurity up, food insecurity down); only their sum is meaningful.
    That is why the family totals above are the explanation, not any one county curve.
    """)
    return


@app.cell
def _(BLUE, IMAGES, MUTED, ebm, ebm_terms, np, plt, roles, test):
    # Curves only for numeric features with more than two values (not ownership, not yes/no flags).
    _curves = ebm_terms[ebm_terms.term.map(lambda t: t in roles.groups and t != "ownership"
                                           and test[t].nunique() > 2)]
    # Strongest feature of each family, then the next strongest overall (incl. the offsetting county one).
    _first = list(_curves.groupby("group").head(1).term)
    _numeric = (_first + [t for t in _curves.term if t not in _first])[:6]
    _global = ebm.explain_global()
    _fig, _axes = plt.subplots(2, 3, figsize=(11, 5.6))
    for _ax, _term in zip(_axes.flat, _numeric, strict=False):
        _data = _global.data(list(ebm.term_names_).index(_term))
        _edges, _scores = np.asarray(_data["names"], dtype=float), np.asarray(_data["scores"], dtype=float)
        _ax.step(_edges[:-1], _scores, where="post", color=BLUE)
        _ax.axhline(0, color=MUTED, lw=0.8)
        _lo, _hi = np.nanpercentile(_edges, [1, 99])
        _ax.set_xlim(_lo, _hi)
        _ax.set_title(_term.replace("_", " "), fontsize=10)
    _fig.supylabel("contribution to reduction (pp)", color=MUTED, fontsize=9)
    _fig.tight_layout()
    _fig.savefig(IMAGES / "12_ebm_shapes.png")
    _fig
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## 4 · What a hospital manager would see

    The chosen model's FY 2026 top-quarter predictions, against what actually happened. A ranking
    tool is useful if its top of the list is enriched with hospitals that really get large
    penalties.
    """)
    return


@app.cell
def _(PROJECT_ROOT, mo, pd, results):
    _chosen = results["selection"]["chosen"] + "_drivers"
    _pred = pd.read_parquet(PROJECT_ROOT / "data" / "model" / "test_predictions.parquet")
    _pred["predicted_top_quarter"] = _pred[_chosen] >= _pred[_chosen].quantile(0.75)
    lift = (_pred.groupby("predicted_top_quarter")
            .agg(hospitals=("facility_id", "size"),
                 actually_top_quarter=("is_top_quarter_penalty", "mean"),
                 mean_actual_reduction_pct=("payment_reduction_pct", "mean"))
            .rename(index={True: "flagged by the model", False: "not flagged"}).round(3))
    mo.plain(lift)
    return (lift,)


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Summary

    - **LightGBM is chosen** by cross-validation on the training years (CV AUC 0.723 vs ridge 0.683
      and EBM 0.674), and the test year agrees: **0.745** [0.73-0.76], +0.030 over ridge (paired
      interval +0.014 to +0.046) and +0.048 over the hospital's own penalty 3 years earlier.
    - **In practice:** of the quarter of hospitals the model flags, about half really end up in
      the top quarter of penalties (a random quarter would give 25%), and their average actual
      reduction is 0.60% against 0.26% for the rest.
    - **EBM is not better than ridge here.** Similar AUC, lower rank correlation. Its value in
      this project is as a second, readable explanation.
    - **The split trap is real for flexible models.** A random split overstates LightGBM by 0.03
      and EBM by 0.05 AUC; for ridge it made no difference. The more a model can memorize
      hospitals, the more an overlapping split flatters it.
    - **Adding prior results helps ridge (+0.045) but not LightGBM (-0.007).** In training, the prior
      penalty only exists for FY 2023 rows, where it comes from FY 2020 (mean 0.59%); for the test
      year it comes from FY 2023, after penalties were halved (mean 0.33%). The trees learned
      thresholds on the old scale. Ridge's single straight slope survives a shift in scale better.
      Cross-validation could not see this, because its folds are drawn from the same years.
    - **Explanations agree on the main families:** volume and county conditions lead in both
      models, then survey scores. Volume is partly mechanical (CMS shrinks small hospitals'
      ratios toward 1.0, so they rarely get large penalties; notebook 02). Single county or
      survey features should not be read alone: they are strongly correlated and share or
      offset each other's effect. All of this is association, not cause.
    """)
    return


if __name__ == "__main__":
    app.run()
