import marimo

__generated_with = "0.25.0"
app = marimo.App(width="medium", app_title="02 · Modeling data")


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    # 02 · Modeling data

    **Goal of this notebook:** look at the table the model will learn from, *before* training
    anything, and decide how to judge the model honestly. Four questions:

    1. **Target:** what exactly do we predict, and how does it behave over the years?
    2. **The overlap trap:** why a random train/test split would make the model look far better
       than it is.
    3. **Signal:** which drivers move with the penalty, and how strongly?
    4. **Expectations:** what is a realistic result, so a suspiciously good one gets questioned?

    The table is `ml.ml_penalty_features`, built by dbt from the marts
    (`dbt/models/ml/ml_penalty_features.sql`). Every column has a role (key, target, split,
    feature) and every feature a written leakage review in `dbt/models/ml/_ml.yml`.
    Decisions: D-002 (what to predict) and D-024 (validation design) in
    [`docs/decisions.md`](https://github.com/Saikrishna0107/Healthcare-readmission-intelligence/blob/main/docs/decisions.md).
    """)
    return


@app.cell
def _():
    import duckdb
    import marimo as mo
    import matplotlib.pyplot as plt
    import pandas as pd

    from hri import PROJECT_ROOT
    return PROJECT_ROOT, duckdb, mo, pd, plt


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Setup

    The notebook reads the DuckDB warehouse built by `hri dbt build` (read-only, so it can stay
    open while dbt runs elsewhere). Column roles come from the dbt YAML, so the notebook and the
    training code use the same list of features.
    """)
    return


@app.cell
def _(PROJECT_ROOT, duckdb, plt):
    IMAGES = PROJECT_ROOT / "images"
    IMAGES.mkdir(exist_ok=True)

    BLUE, ORANGE, INK, MUTED, GRID = "#2a78d6", "#eb6834", "#0b0b0b", "#52514e", "#e4e3df"
    plt.rcParams.update({
        "figure.dpi": 110, "savefig.dpi": 150, "savefig.bbox": "tight",
        "axes.spines.top": False, "axes.spines.right": False,
        "axes.edgecolor": MUTED, "axes.labelcolor": MUTED,
        "xtick.color": MUTED, "ytick.color": MUTED,
        "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.8, "axes.axisbelow": True,
        "axes.titlesize": 12, "axes.titleweight": "bold", "axes.titlecolor": INK,
        "axes.titlelocation": "left", "font.size": 10,
    })

    con = duckdb.connect(str(PROJECT_ROOT / "data" / "hri.duckdb"), read_only=True)
    data = con.execute("select * from ml.ml_penalty_features").df()
    return BLUE, IMAGES, INK, MUTED, ORANGE, con, data


@app.cell
def _(PROJECT_ROOT, mo, pd):
    import yaml

    _spec = yaml.safe_load((PROJECT_ROOT / "dbt" / "models" / "ml" / "_ml.yml").read_text(encoding="utf-8"))
    _model = next(m for m in _spec["models"] if m["name"] == "ml_penalty_features")
    roles = pd.DataFrame([
        {"column": c["name"], "role": c["config"]["meta"]["role"], "group": c["config"]["meta"].get("group", "")}
        for c in _model["columns"]
    ])
    FEATURES = roles.loc[roles.role == "feature", "column"].tolist()
    PRIOR = roles.loc[roles.role == "variant_feature", "column"].tolist()
    mo.plain(roles.groupby(["role", "group"]).size().rename("columns").to_frame())
    return FEATURES, PRIOR, roles


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## 1 · The target: the hospital's penalty

    **Grain:** one row per hospital and fiscal year in a CMS penalty file (FY 2020 to FY 2026).
    **Target:** `payment_reduction_pct`, the cut to the hospital's Medicare payments, 0% to 3%.

    *Why the penalty and not each condition's readmission ratio?* The penalty is what costs the
    hospital money and what a manager asks about. Condition-level ratios are noisy (CMS reports
    them with wide intervals) and our drivers are measured per hospital, not per condition, so the
    hospital level is where drivers and target meet (D-002).
    """)
    return


@app.cell
def _(data, mo):
    by_year = data.groupby("fiscal_year").agg(
        hospitals=("facility_id", "size"),
        split=("split", "first"),
        mean_reduction_pct=("payment_reduction_pct", "mean"),
        median_reduction_pct=("payment_reduction_pct", "median"),
        top_quarter_starts_at=("payment_reduction_pct", lambda s: s.quantile(0.75)),
        share_penalized=("is_penalized", "mean"),
        share_at_3pct_cap=("payment_reduction_pct", lambda s: (s >= 3).mean()),
    ).round(3)
    mo.plain(by_year)
    return (by_year,)


@app.cell
def _(BLUE, IMAGES, ORANGE, by_year, plt):
    _fig, (_a, _b) = plt.subplots(1, 2, figsize=(10, 3.4))
    _colors = by_year.split.map({"train": BLUE, "overlap_unused": "#b9b8b3", "test": ORANGE})
    _a.bar(by_year.index.str[2:], by_year.mean_reduction_pct, color=_colors)
    _a.set_title("Average payment reduction, %")
    _b.bar(by_year.index.str[2:], by_year.share_penalized * 100, color=_colors)
    _b.set_title("Hospitals penalized, %")
    _b.set_ylim(0, 100)
    for _ax in (_a, _b):
        _ax.set_xlabel("Fiscal year  (blue = train, grey = overlaps test, orange = test)")
    _fig.tight_layout()
    _fig.savefig(IMAGES / "05_target_by_year.png")
    _fig
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    **What we see:**

    - **Most hospitals are penalized** (75-83% every year), so "penalized or not" is a weak
      question: a model that says "yes" to everyone is right four times out of five. We keep it as
      a check, but judge the model on whether it finds the **top quarter** of penalties.
    - **Penalties roughly halve from FY 2023** (average 0.53-0.58% before, 0.32-0.34% after).
      FY 2023 is the first year whose period includes the pandemic, and CMS left pneumonia out.
      The training years (FY 2020-2023) are mostly in the "high" regime and the test year is in
      the "low" one.
    - ➡ **Implication:** a model's *level* (how many percent) will be off in the test year for
      reasons no driver explains. Its *ranking* (which hospitals are worst) can still hold. So the
      main metrics are ranking metrics computed **within one year**: AUC for top-quarter penalty,
      and rank correlation. `is_top_quarter_penalty` is defined per year for the same reason.
    - Only 0.3-1.8% of hospitals hit the 3% cap, so the cap barely distorts the target.
    """)
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## 2 · The overlap trap: why the split must follow time

    Each fiscal year's penalty is based on **three years of patients**, and the windows slide by
    one year. FY 2025 (July 2020 - June 2023) and FY 2026 (July 2021 - June 2024) share two of
    their three years: the **same patients** are in both. A model trained on FY 2025 and tested on
    FY 2026 is partly tested on the data it learned from.

    How strong is that effect? Below, the correlation between a hospital's (discharge-weighted)
    readmission ratio in one year and *k* years later.
    """)
    return


@app.cell
def _(con, data, mo, pd):
    _h = con.execute("""
        select facility_id, cast(substr(fiscal_year, 3) as integer) as fy,
               sum(excess_readmission_ratio * discharges) / sum(discharges) as err
        from marts.fct_readmissions
        where excess_readmission_ratio is not null and discharges > 0
        group by all
    """).df()
    _p = data.assign(fy=data.fiscal_year.str[2:].astype(int))[["facility_id", "fy", "payment_reduction_pct"]]

    def _lag_corr(df, column, k):
        later = df.assign(fy=df.fy - k)
        pairs = df.merge(later, on=["facility_id", "fy"], suffixes=("", "_later"))
        return pairs[column].corr(pairs[f"{column}_later"]), len(pairs)

    lags = pd.DataFrame([
        {"years_apart": k,
         "patients_shared": {1: "2 of 3 years", 2: "1 of 3 years"}.get(k, "none"),
         "err_correlation": _lag_corr(_h, "err", k)[0],
         "reduction_correlation": _lag_corr(_p, "payment_reduction_pct", k)[0] if k <= 3 else None,
         "hospital_pairs": _lag_corr(_h, "err", k)[1]}
        for k in (1, 2, 3, 4)
    ]).round(2)
    mo.plain(lags)
    return (lags,)


@app.cell
def _(BLUE, IMAGES, ORANGE, lags, plt):
    _fig, _ax = plt.subplots(figsize=(7, 3.4))
    _ax.plot(lags.years_apart, lags.err_correlation, marker="o", color=BLUE, label="Readmission ratio")
    _r = lags.dropna(subset=["reduction_correlation"])
    _ax.plot(_r.years_apart, _r.reduction_correlation, marker="o", color=ORANGE, label="Payment reduction")
    _ax.axvspan(0.6, 2.5, color="#f3d9cc", alpha=0.5, lw=0)
    _ax.text(1.55, 0.3, "periods share patients", ha="center", color="#8a3b17")
    _ax.set_xticks([1, 2, 3, 4])
    _ax.set_ylim(0, 1)
    _ax.set_xlabel("Fiscal years apart")
    _ax.set_title("Same hospital, k years later: correlation")
    _ax.legend(frameon=False)
    _fig.savefig(IMAGES / "06_overlap_by_lag.png")
    _fig
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    **What we see:** one year apart the ratios correlate at about **0.85**, and part of that is
    simply the shared patients. Three years apart (no shared patients) it is about **0.55**: the
    real persistence of a hospital's performance. The penalty, which is a thresholded, capped
    version of the ratios, drops from 0.76 to 0.37.

    ➡ **The split (D-024):**

    | Rows | Fiscal years | Use |
    |---|---|---|
    | `train` | FY 2020 - FY 2023 | Fit the model; tune it with cross-validation **grouped by hospital**, so one hospital's years never sit on both sides |
    | `overlap_unused` | FY 2024, FY 2025 | Not used for the honest evaluation: they share patients with the test year |
    | `test` | FY 2026 | Scored once, at the end. Its period (July 2021 - June 2024) starts the day after FY 2023's ends |

    The dbt test `assert_ml_split_has_no_shared_patients` fails if a training period ever
    overlaps the test period, for example after next year's file shifts the latest year.

    In step 7b we will also report the **naive** result (training on FY 2025 included) next to
    the honest one, to show the size of the trap in numbers.
    """)
    return


@app.cell
def _(data, mo):
    mo.plain(data.groupby("split").agg(
        rows=("facility_id", "size"),
        hospitals=("facility_id", "nunique"),
        fiscal_years=("fiscal_year", lambda s: ", ".join(sorted(s.unique()))),
    ))
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## 3 · Volume: small hospitals are rarely penalized

    CMS does not report a small hospital's raw readmission rate. It **shrinks** the ratio toward
    1.0 (the national average) in proportion to how little data the hospital has, so a hospital
    with 40 patients cannot look extreme by chance. Side effect: small hospitals rarely land far
    above the peer median.
    """)
    return


@app.cell
def _(BLUE, IMAGES, ORANGE, con, data, mo, pd, plt):
    _r = con.execute("""
        select discharges, excess_readmission_ratio as err
        from marts.fct_readmissions
        where excess_readmission_ratio is not null and discharges > 0
    """).df()
    _r["volume_quintile"] = pd.qcut(_r.discharges, 5, labels=False) + 1
    shrinkage = _r.groupby("volume_quintile").agg(
        discharges_from=("discharges", "min"), discharges_to=("discharges", "max"),
        err_spread_sd=("err", "std"),
    ).round(3)

    _d = data.assign(volume_quintile=data.groupby("fiscal_year").eligible_discharges
                     .transform(lambda s: pd.qcut(s, 5, labels=False) + 1))
    by_volume = _d.groupby("volume_quintile").agg(
        share_penalized=("is_penalized", "mean"), share_top_quarter=("is_top_quarter_penalty", "mean"),
        mean_reduction_pct=("payment_reduction_pct", "mean"),
    ).round(3)

    _fig, (_a, _b) = plt.subplots(1, 2, figsize=(10, 3.4))
    _a.bar(shrinkage.index, shrinkage.err_spread_sd, color=BLUE)
    _a.set_title("Spread of readmission ratios (sd)")
    _a.set_xlabel("Condition volume quintile (1 = fewest patients)")
    _b.bar(by_volume.index, by_volume.share_top_quarter * 100, color=ORANGE)
    _b.set_title("Hospitals in the top penalty quarter, %")
    _b.set_xlabel("Hospital volume quintile, within each year")
    _fig.tight_layout()
    _fig.savefig(IMAGES / "07_volume_shrinkage.png")
    mo.vstack([mo.plain(shrinkage), mo.plain(by_volume), _fig])
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    **What we see:** ratios of the smallest conditions (25-119 patients) spread about 40% less
    than those of the largest. Only about half of the smallest hospitals are penalized at all
    (versus 82-91% in the other quintiles), and under 8% reach the top penalty quarter.

    ➡ **Implication:** volume (`eligible_discharges`, `conditions_with_25_cases`) will be one of
    the strongest features, and for a *mechanical* reason, not because big hospitals care for
    patients worse. The model card (7c) must say so, and the driver story should be told
    **after accounting for volume**.
    """)
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## 4 · Signal: which drivers move with the penalty?

    Rank (Spearman) correlation of each feature with the payment reduction, **training years
    only** (looking at the test year now would let it influence our choices). Rank correlation
    because the target is skewed, with many small penalties and a few large ones.
    """)
    return


@app.cell
def _(FEATURES, PRIOR, data, mo, pd, roles):
    _train = data[data.split == "train"].assign(
        ownership_for_profit=lambda d: (d.ownership == "Proprietary").astype(float))
    _group = dict(zip(roles.column, roles.group, strict=True)) | {"ownership_for_profit": "profile"}
    _columns = [c for c in FEATURES if c != "ownership"] + ["ownership_for_profit"] + PRIOR
    signal = pd.DataFrame([
        {"feature": c, "group": _group[c],
         "rank_correlation": _train[c].astype(float).rank().corr(_train.payment_reduction_pct.rank()),
         "missing_share": _train[c].isna().mean()}
        for c in _columns
    ]).round(3).sort_values("rank_correlation", key=abs, ascending=False).reset_index(drop=True)
    mo.plain(signal)
    return (signal,)


@app.cell
def _(IMAGES, INK, MUTED, plt, signal):
    from matplotlib.patches import Patch

    _palette = {"volume": "#7d7c78", "patient_mix": "#9b59b6", "survey": "#2a78d6", "profile": "#2e9e6a",
                "county": "#c9a227", "prior_results": "#eb6834"}
    _s = signal.head(20).iloc[::-1]
    _fig, _ax = plt.subplots(figsize=(8, 6))
    _ax.barh(_s.feature, _s.rank_correlation, color=[_palette[g] for g in _s.group])
    _ax.axvline(0, color=MUTED, lw=0.8)
    _ax.set_title("Rank correlation with payment reduction (train years), top 20")
    _ax.legend(handles=[Patch(color=_c, label=_g.replace("_", " ")) for _g, _c in _palette.items()],
               frameon=False, loc="lower right", labelcolor=INK)
    _fig.savefig(IMAGES / "08_feature_signal.png")
    _fig
    return


@app.cell
def _(data, mo):
    mo.plain(data[data.split == "train"].groupby("ownership").payment_reduction_pct
             .agg(["mean", "size"]).rename(columns={"mean": "mean_reduction_pct", "size": "hospital_years"})
             .sort_values("mean_reduction_pct").round(3))
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    **What we see:**

    - **The hospital's own past is the strongest single signal** (prior penalty, rank
      correlation 0.43), as expected from section 2. That is why it lives in a separate model
      variant: it says *that* a hospital is penalized again, not *why*.
    - **Volume comes next** (0.34-0.36), for the mechanical reason in section 3.
    - **Patient experience matters, in the expected direction:** hospitals whose patients rate
      the doctors' communication, the hospital overall and the discharge information lower get
      larger penalties (-0.14 to -0.20). This is an association, not proof of cause; both could
      come from, say, staffing levels.
    - **For-profit hospitals** have the highest average reduction (0.63% vs 0.50% for private
      non-profits).
    - **Dual proportion (poverty) shows almost nothing (-0.03), and that is by design:** since
      FY 2019, CMS compares each hospital only with peers serving a similar share of dual-eligible
      patients, which removes most of the poverty effect from the penalty.
    - **County health measures are weak** (|r| ≤ 0.17). Partly real (a county is a coarse
      proxy for a hospital's patients), partly because PLACES is one recent release used for every
      year (D-008).
    - **Missing values:** survey scores are missing for 8.5% of training rows and the social needs
      measures for 29% (not every state ran that survey module). Tree models (7c) handle missing
      values natively; the linear baseline (7b) will fill them with the training median plus a
      "was missing" flag.
    """)
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## 5 · Expectations, written down before training

    No single driver correlates above 0.36 (0.2 without volume), and a hospital's own past only
    reaches 0.43. A first linear model during exploration reached an **R² of about 0.07** and an
    **AUC of about 0.60** for the top penalty quarter. So for step 7b/7c:

    - **A realistic target:** AUC around 0.65-0.75 for the top penalty quarter. That is useful
      for ranking hospitals to review first, not for predicting one hospital's exact penalty.
    - **A red flag:** an AUC above about 0.85 without the prior-results variant would mean
      something leaks, and we would look for it before celebrating.
    - **The comparison that matters:** each model against the naive baselines (everyone gets the
      training average; or "same as three years ago"), on the FY 2026 test year only.

    ## Summary: what the data told us and what we do about it

    | # | Finding | What we do | Decision |
    |---|---|---|---|
    | 1 | 75-83% of hospitals are penalized every year | Judge on the top penalty quarter, not "penalized or not" | D-002 |
    | 2 | Penalties roughly halve from FY 2023 on | Ranking metrics within one year; top quarter defined per year | D-024 |
    | 3 | Periods one year apart share patients (r ≈ 0.85 vs 0.55 with none shared) | Train FY 2020-23, test FY 2026, FY 2024-25 unused; grouped CV | D-024 |
    | 4 | Small hospitals are shrunk toward 1.0 and rarely penalized | Volume features included and labelled mechanical | D-024 |
    | 5 | Survey scores and ownership go with penalties; poverty does not (peer groups) | Drivers-only model as the main one, explained with SHAP | D-009 |
    | 6 | A hospital's own past is the strongest signal | Separate "with prior results" variant, from a non-overlapping period | D-024 |
    | 7 | Each column has a role and a leakage review; dbt contract + pytest enforce it | The training code reads features from the dbt YAML | D-024 |

    **Next step (7b):** the training harness: naive and linear baselines, the grouped
    cross-validation, and the honest-versus-naive split comparison.
    """)
    return


if __name__ == "__main__":
    app.run()
