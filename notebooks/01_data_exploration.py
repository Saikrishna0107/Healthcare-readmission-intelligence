import marimo

__generated_with = "0.25.0"
app = marimo.App(width="medium", app_title="01 · Data exploration")


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    # 01 · Data exploration

    **Goal of this notebook:** understand the raw data *before* building anything on it.
    For each dataset we answer four questions:

    1. **Grain**: what does one row represent?
    2. **Key columns**: which fields matter for the project?
    3. **Traps**: missing values, codes, mismatches that would silently break an analysis.
    4. **Implication**: what the finding means for the pipeline and the model.

    Every finding at the end is linked to a decision in
    [`docs/decisions.md`](https://github.com/Saikrishna0107/Healthcare-readmission-intelligence/blob/main/docs/decisions.md).

    | Dataset | Source | Role |
    |---|---|---|
    | Hospital Readmissions Reduction Program (HRRP) | CMS | **Target**: Excess Readmission Ratio |
    | Hospital General Information | CMS | Hospital profile |
    | Patient survey (HCAHPS) – Hospital | CMS | Candidate drivers |
    | PLACES – County Data | CDC | Community health context |

    *This is a [marimo](https://marimo.io) notebook: cells re-run automatically when something
    they depend on changes, so the results always match the code.*
    """)
    return


@app.cell
def _():
    import re
    from pathlib import Path

    import marimo as mo
    import matplotlib.pyplot as plt
    import numpy as np
    import pandas as pd

    from hri import PROJECT_ROOT
    from hri.ingest import RawStore, ingest, load_sources
    return PROJECT_ROOT, RawStore, ingest, load_sources, mo, np, pd, plt, re


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Setup

    The data comes from the project's ingestion step (`hri ingest`, code in `src/hri/ingest/`).
    The cell below runs it for the sources this notebook needs: releases that are already stored
    are skipped, so after the first run this takes about a second.

    **How ingestion finds the current file.** CMS puts a changing code in each file's URL
    (for example `.../a171bc36..._1770163617/FY_2026_...csv`) and the code changes with every
    refresh. Hard-coding the link would break at the next quarterly update. Instead ingestion asks
    the CMS *metastore* API for the current link, using the dataset's permanent ID (e.g. `9n3s-kdb3`),
    and stores each release as a Parquet file in `data/raw/` (ignored by Git).
    """)
    return


@app.cell
def _(PROJECT_ROOT, RawStore, ingest, load_sources):
    IMAGES = PROJECT_ROOT / "images"
    IMAGES.mkdir(exist_ok=True)

    _sources = load_sources()
    _needed = ["hrrp", "hospital_info", "hcahps", "footnotes", "places_county"]
    ingest([_sources[name] for name in _needed])  # downloads only releases not stored yet
    store = RawStore()
    return IMAGES, store


@app.cell
def _(mo, pd, store):
    hrrp = store.read_latest("hrrp")
    hospital_info = store.read_latest("hospital_info")
    hcahps = store.read_latest("hcahps")
    footnotes = store.read_latest("footnotes")
    places = store.read_latest("places_county")

    _manifest = store.load_manifest()
    mo.plain(pd.DataFrame([
        {"source": name, "release": _manifest[name]["latest"],
         "rows": _manifest[name]["releases"][_manifest[name]["latest"]]["rows"]}
        for name in ["hrrp", "hospital_info", "hcahps", "footnotes", "places_county"]
    ]))
    return footnotes, hcahps, hospital_info, hrrp, places


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    **Why is every column stored as text?** The raw layer keeps values exactly as published:

    - **Hospital IDs have leading zeros.** `010001` is a real ID; read as a number it becomes
      `10001` and no longer joins to other files.
    - **Number columns contain words.** `Number of Readmissions` contains values like
      `Too Few to Report`, and missing values appear as `N/A` or `Not Available`. We convert to
      numbers deliberately, one column at a time, so every conversion is visible.
    """)
    return


@app.cell
def _(plt):
    # Shared chart style: recessive axes, one accent colour, text in neutral ink.
    BLUE, ORANGE, INK, MUTED, GRID = "#2a78d6", "#eb6834", "#0b0b0b", "#52514e", "#e4e3df"
    plt.rcParams.update({
        "figure.dpi": 110, "savefig.dpi": 150, "savefig.bbox": "tight",
        "axes.spines.top": False, "axes.spines.right": False,
        "axes.edgecolor": MUTED, "axes.labelcolor": MUTED, "xtick.color": MUTED, "ytick.color": MUTED,
        "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.8, "axes.axisbelow": True,
        "axes.titlesize": 12, "axes.titleweight": "bold", "axes.titlecolor": INK, "axes.titlelocation": "left",
        "font.size": 10,
    })

    CONDITIONS = {
        "READM-30-AMI-HRRP": "Heart attack (AMI)",
        "READM-30-HF-HRRP": "Heart failure",
        "READM-30-PN-HRRP": "Pneumonia",
        "READM-30-COPD-HRRP": "COPD",
        "READM-30-HIP-KNEE-HRRP": "Hip/knee replacement",
        "READM-30-CABG-HRRP": "Bypass surgery (CABG)",
    }
    return BLUE, CONDITIONS, INK, MUTED, ORANGE


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## 1 · HRRP: the target

    ### Grain
    We expect **one row per hospital per condition**. Checking the grain first matters: if a
    hospital-condition pair appeared twice, every later join and average would be quietly wrong.
    """)
    return


@app.cell
def _(hrrp, mo):
    _dupes = hrrp.duplicated(["Facility ID", "Measure Name"]).sum()
    mo.vstack([
        mo.md(
            f"**rows:** {len(hrrp):,} · **hospitals:** {hrrp['Facility ID'].nunique():,} · "
            f"**conditions:** {hrrp['Measure Name'].nunique()} · "
            f"**duplicate hospital × condition rows:** {_dupes}"
        ),
        mo.plain(hrrp.head(3)),
    ])
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ### Key columns

    | Column | Meaning |
    |---|---|
    | `Predicted Readmission Rate` | Rate this hospital is expected to have, given its own patients |
    | `Expected Readmission Rate` | Rate an *average* hospital would have with the same patients |
    | **`Excess Readmission Ratio` (ERR)** | Predicted ÷ Expected. **Above 1.0 = more readmissions than expected** |
    | `Footnote` | Code explaining why a value is missing |
    | `Start Date` / `End Date` | The discharge period the numbers cover |

    CMS risk-adjusts ERR for how sick each hospital's patients are, so a hospital that treats
    sicker patients is not penalised for that alone.

    **How the penalty is actually decided.** Since fiscal year 2019 (21st Century Cures Act) the
    line is **not** 1.0. CMS places hospitals in **five peer groups** by their share of patients who
    are eligible for both Medicare and Medicaid, a marker of lower-income patients, and compares
    each hospital's ERR with the **median ERR of its peer group**:

    > penalty for a condition = neutrality modifier × DRG payment ratio × (ERR − peer-group median ERR)

    The total is capped at 3% of Medicare base payments. The peer group is not in this file, so
    the ingestion step adds CMS's HRRP supplemental data (Decision D-014).

    We convert ERR to a number in a **new** table (`hrrp_scored`) rather than adding a column to
    `hrrp` in place. In a reactive notebook every table is built in exactly one cell, so it is
    always clear where a value comes from.
    """)
    return


@app.cell
def _(CONDITIONS, hrrp, mo, pd):
    hrrp_scored = hrrp.assign(
        err=pd.to_numeric(hrrp["Excess Readmission Ratio"], errors="coerce"),
        condition=hrrp["Measure Name"].map(CONDITIONS),
    )
    mo.plain(hrrp_scored["err"].describe().round(3).to_frame())
    return (hrrp_scored,)


@app.cell
def _(BLUE, IMAGES, INK, ORANGE, hrrp_scored, np, plt):
    _scored = hrrp_scored["err"].dropna()
    _fig, _ax = plt.subplots(figsize=(8, 3.8))
    _counts, _edges, _patches = _ax.hist(_scored, bins=np.arange(0.45, 1.66, 0.02), edgecolor="white", linewidth=0.6)
    for _patch, _left in zip(_patches, _edges[:-1]):
        _patch.set_facecolor(ORANGE if _left >= 1.0 else BLUE)
    _ax.axvline(1.0, color=INK, linewidth=1)
    _ax.set_ylim(0, _counts.max() * 1.15)
    _ax.text(1.01, _counts.max() * 1.07, "1.0 = as expected", color=INK, fontsize=9)
    _ax.text(0.62, _counts.max() * 0.55, "better than\nexpected", color=BLUE, fontsize=9, ha="center")
    _ax.text(1.30, _counts.max() * 0.55, "worse than\nexpected", color=ORANGE, fontsize=9, ha="center")
    _ax.set_title("Most hospitals sit close to 1.0, so small differences decide penalties")
    _ax.set_xlabel("Excess Readmission Ratio (hospital x condition)")
    _ax.set_ylabel("Number of hospital-conditions")
    _fig.savefig(IMAGES / "01_err_distribution.png")
    _fig
    return


@app.cell(hide_code=True)
def _(hrrp_scored, mo):
    _q = hrrp_scored["err"].quantile([0.25, 0.75])
    mo.md(rf"""
    **What we see:** ERR clusters tightly around 1.0; half of all scores fall between
    **{_q[0.25]:.3f} and {_q[0.75]:.3f}**. A hospital at 1.03 and one at 0.97 look similar, but they
    sit on opposite sides of the penalty line. The model has to be precise in a narrow range, which
    is one reason to validate it carefully (step 7).

    ### Which conditions are worst? A trap in the obvious calculation

    The tempting calculation is "share of hospitals above 1.0, per condition". But if hospitals
    **without** a score stay in the denominator, conditions with many missing values look better
    than they are. We compute it only over hospitals that have a score, and look at coverage
    separately.
    """)
    return


@app.cell
def _(hrrp_scored, mo):
    n_hospitals = hrrp_scored["Facility ID"].nunique()
    by_condition = (
        hrrp_scored.groupby("condition")["err"]
        .agg(hospitals_scored="count", mean_err="mean",
             share_above_1_of_scored=lambda s: (s.dropna() > 1).mean())
        .assign(coverage=lambda d: d["hospitals_scored"] / n_hospitals)
        .sort_values("coverage")
    )
    mo.plain(by_condition.round(3))
    return by_condition, n_hospitals


@app.cell
def _(BLUE, IMAGES, INK, by_condition, n_hospitals, plt):
    _fig, _ax = plt.subplots(figsize=(8, 3.4))
    _ax.barh(by_condition.index, by_condition["coverage"] * 100, color=BLUE, height=0.6)
    for _y, _v in enumerate(by_condition["coverage"] * 100):
        _ax.text(_v + 0.8, _y, f"{_v:.0f}%", va="center", color=INK, fontsize=9)
    _ax.set_title("Bypass surgery is scored for fewer than a third of HRRP hospitals")
    _ax.set_xlabel(f"% of the {n_hospitals:,} HRRP hospitals with enough cases to receive a score")
    _ax.set_xlim(0, 100)
    _ax.grid(axis="y", visible=False)
    _fig.savefig(IMAGES / "02_scored_coverage_by_condition.png")
    _fig
    return


@app.cell(hide_code=True)
def _(hrrp_scored, mo):
    _above = hrrp_scored.groupby("Facility ID")["err"].apply(lambda s: (s > 1).any())
    mo.md(rf"""
    **What we see:**

    - Among hospitals that have a score, **about half are above 1.0 for every condition**, and the
      average ERR is about 1.00 everywhere. That is by design: ERR compares each hospital with what
      an average hospital would achieve, so roughly half land on each side. **The share above 1.0
      cannot tell us which condition is "worst".** The better question is where the most money is
      lost, which needs payment data (a later step).
    - What differs is **coverage**: pneumonia and heart failure are scored at most hospitals, while
      bypass surgery is scored at under a third, because only larger hospitals perform enough
      of them.
    - **{_above.sum():,} of {len(_above):,} hospitals ({_above.mean():.0%})** are above 1.0 on at
      least one condition. Part of that is arithmetic: with a coin-flip chance on each of several
      conditions, most hospitals land above 1.0 somewhere. Penalties are therefore common, which
      makes *how much* and *why* more useful questions than *who*.

    ### Trap: missing values are *reasons*, not zeros
    """)
    return


@app.cell
def _(footnotes, hrrp_scored, mo):
    _fn_text = footnotes.set_index("Footnote")["Footnote Text"]
    _missing = hrrp_scored[hrrp_scored["err"].isna()]
    mo.vstack([
        mo.md(f"**rows without an ERR:** {len(_missing):,} of {len(hrrp_scored):,} "
              f"({len(_missing) / len(hrrp_scored):.0%})"),
        mo.plain(_missing["Footnote"].replace("", "(none)").value_counts().rename("rows").to_frame()
                 .assign(meaning=lambda d: d.index.map(_fn_text))),
    ])
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    **What we see:** over a third of rows have no ERR, and CMS says why: mostly *too few cases to
    report* (small hospitals) or *results not available*. If these were filled with 0, those
    hospitals would look like they had **zero readmissions**, the best score possible, and the model
    would learn that small hospitals are excellent.

    ➡ **Decision D-003:** keep missing as missing, carry the footnote reason alongside it.

    ## 2 · Hospital General Information: the hospital profile

    **Grain:** one row per hospital (including hospitals that are not part of HRRP).
    """)
    return


@app.cell
def _(hospital_info, hrrp, mo, pd):
    hrrp_ids = set(hrrp["Facility ID"])
    in_hrrp = hospital_info[hospital_info["Facility ID"].isin(hrrp_ids)]
    mo.vstack([
        mo.md(f"**hospitals:** {len(hospital_info):,} · "
              f"**duplicate IDs:** {hospital_info['Facility ID'].duplicated().sum()}"),
        mo.plain(pd.DataFrame({
            "all hospitals": hospital_info["Hospital Type"].value_counts(),
            "in HRRP": in_hrrp["Hospital Type"].value_counts(),
        }).fillna(0).astype(int)),
    ])
    return hrrp_ids, in_hrrp


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    **What we see:** HRRP covers essentially only **acute care hospitals**. Critical access
    hospitals (small rural hospitals), psychiatric and children's hospitals are exempt from the
    program, so they are out of scope for the model (Decision D-002).
    """)
    return


@app.cell
def _(hospital_info, hrrp_ids, in_hrrp, mo):
    _missing_from_info = hrrp_ids - set(hospital_info["Facility ID"])
    mo.vstack([
        mo.md(f"**HRRP hospitals with no row in General Information:** {len(_missing_from_info)}  \n"
              "**Star rating availability among HRRP hospitals:**"),
        mo.plain(in_hrrp["Hospital overall rating"].value_counts().to_frame()),
    ])
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    **What we see:**

    - A few HRRP hospitals have **no profile row**, most likely hospitals that closed or merged
      after the readmission period. The pipeline must report them (a test), not drop them silently.
    - Some hospitals show **"Not Available"** for the star rating: another missing value that must
      not become a number.

    ## 3 · HCAHPS patient survey: candidate drivers

    **Grain:** one row per hospital per survey *answer*. That is why the file has over 300,000
    rows. Most rows are answer percentages ("always", "usually", "sometimes or never"). For
    modelling we only need the **linear mean scores**: one 0–100 summary score per topic per
    hospital.
    """)
    return


@app.cell
def _(hcahps, mo, pd):
    linear = (
        hcahps[hcahps["HCAHPS Measure ID"].str.endswith("LINEAR_SCORE")]
        .assign(score=lambda d: pd.to_numeric(d["HCAHPS Linear Mean Value"], errors="coerce"))
    )
    mo.vstack([
        mo.md(f"**all rows:** {len(hcahps):,} · **linear-score rows:** {len(linear):,}"),
        mo.plain(linear.groupby(["HCAHPS Measure ID", "HCAHPS Question"])["score"]
                 .agg(hospitals="count", mean="mean", min="min", max="max").round(1)),
    ])
    return (linear,)


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    **What we see:** eight topic scores per hospital. Scores are high and close together
    (discharge information averages about 86 out of 100), so, like ERR, the useful signal is in
    small differences.

    ## 4 · Trap: the time periods don't line up

    Each file states the period its numbers cover. Before combining files, check that they
    describe the **same time**.
    """)
    return


@app.cell
def _(BLUE, IMAGES, INK, ORANGE, hcahps, hrrp, pd, plt):
    periods = pd.DataFrame({
        "dataset": ["HRRP readmissions (target)", "HCAHPS survey (drivers)"],
        "start": pd.to_datetime([hrrp["Start Date"].iloc[0], hcahps["Start Date"].iloc[0]], format="%m/%d/%Y"),
        "end": pd.to_datetime([hrrp["End Date"].iloc[0], hcahps["End Date"].iloc[0]], format="%m/%d/%Y"),
    })

    _fig, _ax = plt.subplots(figsize=(8, 1.9))
    for _i, _row in periods.iterrows():
        _ax.barh(_i, _row["end"] - _row["start"], left=_row["start"], height=0.45,
                 color=BLUE if _i == 0 else ORANGE)
        _ax.text(_row["start"], _i + 0.38,
                 f"{_row['dataset']}:  {_row['start']:%b %Y} to {_row['end']:%b %Y}", color=INK, fontsize=9)
    _ax.set_yticks([])
    _ax.set_ylim(-0.5, 1.9)
    _ax.grid(axis="y", visible=False)
    _ax.set_title("The current survey was collected after the readmissions it would 'explain'")
    _fig.savefig(IMAGES / "03_period_mismatch.png")
    _fig
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    **What we see:** the readmissions happened **July 2021 – June 2024**; the current survey was
    collected **October 2024 – September 2025**, *after* those patients were discharged.

    Using later information to explain an earlier outcome is **data leakage**. The model would
    score well in testing but could never work in real life, because at prediction time the future
    survey doesn't exist yet.

    ➡ **Decision D-008:** use CMS's archived releases (step 6) so each hospital's survey scores come
    from the same period as, or before, the readmissions.

    ## 5 · A first look at a driver: discharge information vs heart-failure readmissions

    A quick sanity check that the drivers carry signal. **Caveat:** because of the period mismatch
    above, this is only a rough look, not a result. Hospital survey scores change slowly, so a
    relationship should still be visible.

    We split hospitals into five groups (quintiles) by their *discharge information* score and
    compare the average heart-failure ERR in each group. Scores are whole numbers and many
    hospitals share the same score, so the groups are not exactly equal in size.
    """)
    return


@app.cell
def _(hrrp_scored, linear, mo, np, pd):
    _hf = hrrp_scored.loc[hrrp_scored["Measure Name"] == "READM-30-HF-HRRP", ["Facility ID", "err"]].dropna()
    _discharge = linear.loc[linear["HCAHPS Measure ID"] == "H_COMP_6_LINEAR_SCORE", ["Facility ID", "score"]].dropna()
    joined = _hf.merge(_discharge, on="Facility ID").assign(
        quintile=lambda d: pd.qcut(d["score"], 5, labels=["Lowest 20%", "2nd", "3rd", "4th", "Highest 20%"])
    )
    quintiles = (
        joined.groupby("quintile", observed=True)
        .agg(hospitals=("err", "size"), mean_err=("err", "mean"), sd=("err", "std"),
             score_range=("score", lambda s: f"{s.min():.0f}" if s.min() == s.max() else f"{s.min():.0f}-{s.max():.0f}"))
        .assign(ci95=lambda d: 1.96 * d["sd"] / np.sqrt(d["hospitals"]))
    )
    mo.plain(quintiles.drop(columns="sd").round(3))
    return joined, quintiles


@app.cell
def _(BLUE, IMAGES, MUTED, np, plt, quintiles):
    _fig, _ax = plt.subplots(figsize=(8, 3.6))
    _x = np.arange(len(quintiles))
    _ax.errorbar(_x, quintiles["mean_err"], yerr=quintiles["ci95"], fmt="o", color=BLUE,
                 markersize=8, capsize=4, linewidth=1.5)
    _ax.axhline(1.0, color=MUTED, linewidth=1, linestyle="--")
    _ax.set_xticks(_x, [f"{q}\n(score {r})" for q, r in zip(quintiles.index, quintiles["score_range"])])
    _ax.set_ylabel("Mean heart-failure ERR")
    _ax.set_title("Hospitals with better discharge information have fewer excess readmissions")
    _ax.grid(axis="x", visible=False)
    _fig.savefig(IMAGES / "04_discharge_info_vs_hf_err.png")
    _fig
    return


@app.cell(hide_code=True)
def _(joined, mo):
    mo.md(rf"""
    **What we see** ({len(joined):,} hospitals, correlation **{joined['err'].corr(joined['score']):.2f}**):
    average heart-failure ERR falls from the lowest-scoring to the highest-scoring group, and the
    error bars (95% confidence intervals) of the two extremes do not overlap. The correlation is
    modest, so discharge information is **one driver among several**, not the whole story.

    **This is association, not causation.** Well-run hospitals may simply do many things well at
    once. The model (step 7) will measure each driver while accounting for the others.

    ## 6 · Linking hospitals to their county (CDC PLACES)

    CDC PLACES gives community health measures (diabetes, obesity, uninsured adults, lack of
    transportation…) **per county**. To attach them to a hospital we need the hospital's county.

    **The problem:** the hospital file has a county *name* (`HOUSTON`, state `AL`); PLACES has a
    county *code* (FIPS `01069`) and a mixed-case name (`Houston`). We try the simplest approach
    first, matching on state + cleaned-up name, and measure how well it works.
    """)
    return


@app.cell
def _(in_hrrp, mo, places, re):
    places_counties = (
        places[["StateAbbr", "LocationName", "LocationID"]]
        .drop_duplicates()
        .rename(columns={"StateAbbr": "stateabbr", "LocationName": "locationname", "LocationID": "locationid"})
    )


    def clean_county(name: str) -> str:
        # Upper-case, drop punctuation, 'SAINT' -> 'ST', and drop words like COUNTY / PARISH.
        s = re.sub(r"[.'’]", "", str(name).upper().strip()).replace("SAINT ", "ST ")
        s = re.sub(r"\s+(COUNTY|PARISH|BOROUGH|CENSUS AREA|MUNICIPALITY|CITY AND BOROUGH)$", "", s)
        return re.sub(r"\s+", " ", s)


    places_counties["key"] = places_counties["stateabbr"] + "|" + places_counties["locationname"].map(clean_county)
    _hospitals = in_hrrp[["Facility ID", "State", "County/Parish"]].assign(
        key=lambda d: d["State"] + "|" + d["County/Parish"].map(clean_county)
    )
    county_match = _hospitals.merge(
        places_counties.drop_duplicates("key")[["key", "locationid"]], on="key", how="left"
    )
    _rate = county_match["locationid"].notna()
    mo.vstack([
        mo.md(f"**PLACES counties:** {len(places_counties):,} · **HRRP hospitals matched to a county:** "
              f"{_rate.sum():,} of {len(county_match):,} (**{_rate.mean():.1%}**)  \n"
              "**Most common unmatched counties:**"),
        mo.plain(county_match.loc[county_match["locationid"].isna(), ["State", "County/Parish"]]
                 .value_counts().head(12).rename("hospitals").to_frame()),
    ])
    return (places_counties,)


@app.cell
def _(mo, places_counties):
    mo.vstack([
        mo.md("**County names that exist twice in the same state (a county and an independent city):**"),
        mo.plain(places_counties[places_counties.duplicated("key", keep=False)]
                 .sort_values("key")[["stateabbr", "locationname", "locationid"]]),
    ])
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    **What we see:** simple name cleanup links about **96%** of hospitals, and the failures follow
    clear patterns:

    - **Spelling variants:** `DU PAGE` vs `DuPage`, `MC HENRY` vs `McHenry`, `E. BATON ROUGE`.
    - **Connecticut:** since 2022 the Census uses *planning regions* instead of counties in
      Connecticut, so CT county names don't exist in PLACES at all.
    - **Independent cities:** *Baltimore* is both a county (`24005`) and a separate city (`24510`)
      with the same name. This is the most dangerous case: a name match can **silently pick the
      wrong one**, and no error would ever appear.

    ➡ **Implication for step 5:** matching on names is not reliable enough for production. Step 5
    will use a more robust key, such as the hospital's ZIP code mapped to a county code through a
    public Census crosswalk, and a test will report the match rate on every run.

    ## Summary: what the data told us and what we do about it

    | # | Finding | What we do | Decision |
    |---|---|---|---|
    | 1 | ERR clusters tightly around 1.0; small differences decide penalties | Validate the model carefully on precision near 1.0 | D-009 |
    | 2 | Penalties compare ERR with the **peer-group median**, not 1.0; peer groups are not in this file | Add CMS's HRRP supplemental data at ingestion | D-014 |
    | 3 | About half of scored hospitals are above 1.0 for *every* condition (by design); conditions differ in coverage, not severity | Rank conditions by money at stake, not by share above 1.0 | D-002 |
    | 4 | Over a third of ERR values are missing, each with a stated reason | Keep as missing, carry the reason, never fill with 0 | D-003 |
    | 5 | HRRP covers essentially only acute care hospitals; 20 have no profile row | Scope to acute care; test for unmatched hospitals | D-002 |
    | 6 | The current survey comes *after* the readmission period | Use archived releases to align periods (no leakage) | D-008 |
    | 7 | Better discharge information goes with fewer heart-failure readmissions (association) | Include survey scores as drivers; test properly in the model | D-009 |
    | 8 | Name-based county matching reaches ~96% but can silently pick the wrong county | Use a code-based crosswalk plus a match-rate test | Step 5 |

    **Next step (3):** turn the download code above into a proper ingestion module that saves raw
    files, records when each was downloaded, and skips files that haven't changed.
    """)
    return


if __name__ == "__main__":
    app.run()
