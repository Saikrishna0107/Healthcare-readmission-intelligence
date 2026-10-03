# Decision log

Every major decision in this project, with the reasoning behind it and the alternatives that
were considered. **Accepted** decisions are in effect. **Proposed** decisions are the current
plan and will be confirmed (or changed, with a note explaining why) when the project reaches
that step.

---

## D-001 · Real public data only · Accepted

**Context.** Healthcare analytics roles work with claims, quality and patient-experience data.
A portfolio project needs data that is realistic but shareable.

**Decision.** Use real public data from CMS (Provider Data Catalog) and the CDC (PLACES).

**Why.**
- It is the same data CMS uses to decide real Medicare payments, so the findings mean something.
- It is aggregated at hospital or county level: no protected health information (PHI), so
  there are no HIPAA concerns and the data can be shared freely.
- It is refreshed on a schedule, which makes an automated pipeline genuinely useful.

**Alternatives considered.**
- *Synthea (synthetic patients)*: realistic structure, but not real, so findings can't be trusted.
- *MIMIC-IV (real ICU records)*: real patient-level data, but it needs credentialed access and
  can't be published. It may be added later as an optional extension.
- *Kaggle readmission datasets*: old, static and heavily reused in other portfolios.

---

## D-002 · Target: HRRP Excess Readmission Ratio for acute care hospitals · Accepted

**Context.** We need one clear outcome to predict and explain.

**Decision.** The target is the **Excess Readmission Ratio (ERR)** from HRRP, at the grain of
hospital × condition. ERR = predicted ÷ expected readmission rate; above 1.0 means worse than
expected.

**Why.**
- ERR is what drives the actual payment penalty, so it ties directly to money (the penalty
  compares ERR with a peer-group median, see D-014).
- CMS already adjusts it for how sick each hospital's patients are, so hospitals can be compared
  fairly.
- HRRP only applies to acute care hospitals (critical access hospitals are exempt), so the
  scope is naturally limited to about 3,000 hospitals.

**Still open (decided at step 7).** Whether to predict ERR as a number (regression) or
"ERR above 1.0" as yes/no (classification). The number carries more information; the yes/no
is closer to the penalty decision.

---

## D-003 · Missing values are reasons, not zeros · Accepted

**Context.** About 36% of HRRP rows have no ERR. CMS explains each gap with a footnote code
(1 = too few cases, 5 = results not available, 7 = no cases met the criteria). Many hospitals
also show "Not Available" for their star rating.

**Decision.** Keep missing values as missing (NULL), store the footnote reason next to them,
and never fill them with zero.

**Why.** A zero ERR would mean "no readmissions at all", which is the best possible score. Filling
gaps with zeros would make small hospitals look excellent and would badly distort the model.

---

## D-004 · Separate repository · Accepted

**Decision.** This project has its own repository instead of living inside an earlier project's
repository.

**Why.** Each portfolio project should stand on its own: its own README, its own history and a
name that says what it is. A reviewer should not have to dig through unrelated work.

---

## D-005 · DuckDB as the warehouse · Accepted (step 4)

**Decision.** Store and query the data in DuckDB, a single-file analytical database.

**Why.**
- The data is a few GB at most. DuckDB handles that on a laptop, fast, at no cost.
- Anyone can clone the repo and rebuild everything with one command. No server, no cloud account.
- It reads Parquet files directly.

**Alternatives considered.**
- *Postgres*: built for transactional apps; more setup and no advantage for analytics here.
- *Snowflake / Databricks*: what many employers use, but free tiers expire and a reviewer
  couldn't run the project. Because the transformations are written in dbt, moving to either
  later is mostly a configuration change.

**Implemented.** The database is one file, `data/hri.duckdb` (gitignored, rebuilt by dbt).
Raw Parquet files are not copied into it; DuckDB reads them in place.

---

## D-006 · dbt for transformations · Accepted (step 4)

**Decision.** Write all cleaning and modeling as dbt models (SQL files) on top of DuckDB.

**Why.** dbt is the industry standard for analytics engineering. It adds automated data tests,
documentation and a lineage graph showing how every table was built, which is what makes a
pipeline production-ready rather than a pile of scripts.

**Alternatives considered.** Plain SQL scripts or pandas: faster to start, but no tests, no
lineage and harder to maintain.

**Implemented.** dbt-core with the `dbt-duckdb` adapter, in the `dbt/` folder. See D-019 for how
it is wired to the raw layer.

---

## D-007 · Star schema for the marts · Accepted (step 5)

**Decision.** Model the cleaned data as facts (readmissions, survey scores, community health)
and dimensions (hospital, condition, county). Step 5 builds the first two dimensions in the
`marts` schema: `dim_county` and `dim_hospital`. Facts follow once step 6 has lined up the time
periods.

**Why.** Power BI performs best on a star schema, the LLM agent writes more accurate SQL against
clean, well-named tables, and hospital BI job descriptions ask for dimensional modeling.

**Choices made while building them.**
- *County measures as columns, not rows.* PLACES arrives long (one row per county × measure).
  `dim_county` pivots 17 chosen measures into named columns (`diabetes_pct`,
  `lack_transportation_pct`, ...). A column name is self-explaining for a dashboard user and for
  the LLM agent; the long form stays available in staging for anything else. A test checks the
  pivot loses and invents no values.
- *Age-adjusted, not crude, percentages.* Age-adjusted values compare counties fairly; crude
  values would make counties with older residents look sicker. HRRP's ERR is already
  risk-adjusted for patient age, so the community context should be too.
- *Missing stays missing.* Kentucky and Pennsylvania have no 2023 survey data in this PLACES
  release (190 HRRP hospitals), and the social needs measures exist for 2,299 of 3,144 counties.
  These are NULL with `has_chronic_measures` / `has_social_measures` flags, never filled in.
- *Every hospital any source mentions is in `dim_hospital`.* The key set is the union of the
  hospital profile, HRRP and the penalty file. 20 HRRP hospitals have no profile row; building
  the dimension from the profile alone would make their readmissions vanish from every join.
  A test checks every source's hospitals reach the dimension.

**Alternative considered.** One wide table: simpler, but repeats data and makes each metric
harder to define in one place.

---

## D-008 · Align time periods to prevent data leakage · Accepted (implemented at step 6)

**Context.** The current HRRP file covers discharges from **July 2021 to June 2024**, but the
current HCAHPS survey covers **October 2024 to September 2025**, after those readmissions
happened.

**Decision.** Use CMS's archived releases so each hospital's drivers come from the same period
as (or before) the readmissions they are used to explain.

**Why.** Using information from after the outcome is **data leakage**: the model would look good
in testing and fail in real use. Several archived years also make time-based validation
possible (see D-009).

---

## D-009 · Compare three models, validate on a later year · Proposed (step 7)

**Decision.** Train and compare:
1. **Linear / logistic regression**: the baseline. If a complex model can't beat it, keep the simple one.
2. **Gradient boosting (LightGBM or XGBoost)**: usually the most accurate on tabular data.
3. **Explainable Boosting Machine (EBM)**: close to boosting accuracy, with built-in
   per-feature explanations.

Train on earlier years and test on the most recent year. If the scores are close, choose the
simpler or more explainable model; if boosting clearly wins, explain it with SHAP.

**Why.** Healthcare leaders act on risk scores they can understand. Comparing models shows
judgment; using one popular algorithm only shows familiarity with a tool.

**Alternative considered.** Neural networks: overkill for about 3,000 hospitals, prone to
overfitting and hard to explain.

---

## D-010 · LLM agent through a semantic layer, with an evaluation set · Proposed (step 8)

**Decision.** Build an agent that answers plain-English questions by writing SQL, but only
against a semantic layer of approved metric definitions, with read-only access and row limits.
Measure it on a fixed set of questions with known correct answers.

**Why.** Healthcare employers are moving LLM analytics into production and need them to be
trustworthy. The semantic layer stops the model from inventing its own metric definitions, and
the evaluation set turns "it seems to work" into a measured accuracy.

**Alternative considered.** Letting the LLM query raw tables freely: quick to demo, but
unreliable and not something a healthcare organization would deploy.

---

## D-011 · Power BI dashboard, Streamlit for the agent · Proposed (step 9)

**Why.** Power BI appears in more healthcare job descriptions than Tableau, especially at health
plans. Power BI can't host a chat interface, so the agent gets a small Streamlit app.

---

## D-012 · Python command-line runner instead of a Makefile · Accepted (step 3)

**Why.** `make` isn't available on Windows by default. A small Python CLI (`python -m hri ...`)
runs the same way on Windows, macOS and in CI.

---

## D-013 · GitHub Actions for CI and scheduled refresh · Proposed (step 10)

**Why.** One free tool runs the tests on every push and refreshes the data on a schedule.
Airflow would be too heavy for a one-person project.

---

## D-014 · Penalties are judged against the peer-group median, not 1.0 · Accepted (step 2)

**Context.** Found while exploring the data (step 2). An early version of the analysis treated
ERR above 1.0 as "penalised". Since fiscal year 2019 (21st Century Cures Act), CMS places
hospitals in five peer groups by their share of patients eligible for both Medicare and
Medicaid, and compares each hospital's ERR with the **median ERR of its peer group**:
penalty for a condition = neutrality modifier × DRG payment ratio × (ERR − peer-group median ERR),
capped at 3% of Medicare base payments.

**Decision.** Ingest CMS's HRRP supplemental data (peer group and payment details) alongside the
HRRP file, and define "penalised" and "dollars at risk" with the official formula. *(Done in step 3:
the FY 2026 supplemental file also contains each hospital's penalty indicators and actual payment
reduction; about 78% of the 2,945 hospitals in it receive a reduction.)*

**Why.** Using 1.0 as the line would misclassify hospitals near the threshold, which is exactly
where most hospitals are, and would ignore the adjustment CMS makes for hospitals that serve
lower-income patients.

**Also learned.** Because ERR is relative to an average hospital, about half of scored hospitals
are above 1.0 for every condition. "Share above 1.0" therefore cannot rank conditions; conditions
are compared by money at stake instead.

---

## D-015 · Notebooks are committed with their outputs · Superseded by D-016

**Decision.** Exploration notebooks are run from start to finish on the project's own Python
environment and committed with their outputs (tables and charts). Key charts are also saved to
`images/` for the README.

**Why.** GitHub displays notebook outputs, so a reviewer can read the analysis and results
without installing anything. Running from start to finish before each commit proves the notebook
works in order, not only in a lucky sequence of manually run cells.

**Alternative considered.** Stripping outputs keeps diffs small, but then nobody can see the
results on GitHub, which defeats the purpose of a portfolio notebook.

---

## D-016 · marimo instead of Jupyter for notebooks · Accepted (after step 2)

**Context.** Step 2 was first written as a Jupyter notebook. Two problems showed up: `.ipynb`
files are JSON with embedded outputs, so each commit's diff is unreadable, and Jupyter cells can
run in any order, so a notebook can appear to work only because of the order cells happened to
be run in.

**Decision.** Write notebooks in [marimo](https://marimo.io). Each notebook is a plain `.py`
file. A static HTML export (code, tables and charts) is published from `docs/notebooks/` with
GitHub Pages so results can be read without installing anything.

**Why.**
- **Reactive:** when a cell changes, every cell that depends on it re-runs, so the outputs always
  match the code. marimo also requires each variable to be defined in exactly one cell, which
  rules out hidden state.
- **Readable history:** a `.py` file diffs like normal code, so every commit shows exactly what
  changed. This matters for a project built in public.
- **One file, three uses:** the same notebook opens as an editable notebook (`marimo edit`), runs
  as a script (`python notebook.py`) and can be served as an interactive app (`marimo run`).

**Trade-off.** GitHub shows only the code of a `.py` notebook, not its outputs. The HTML export
on GitHub Pages fixes this, at the cost of one export command per notebook. Key charts stay in
`images/` for the README.

**Alternatives considered.**
- *Jupyter*: the most widely used, and GitHub renders outputs, but the diff and hidden-state
  problems above remain.
- *Quarto*: excellent for polished reports, less suited to exploration.
- *Plain `.py` scripts with `# %%` cells*: diff-friendly, but not reactive and no app mode.
- *Hex / Deepnote*: polished hosted notebooks, but the work would live outside this repository.

---

## D-017 · Installable package with `pyproject.toml` and a `src/` layout · Accepted (step 3)

**Decision.** The pipeline code lives in an installable package, `src/hri/`, described by
`pyproject.toml` and installed with `pip install -e ".[dev]"`. `pyproject.toml` replaces
`requirements.txt`.

**Why.**
- **One copy of every function.** The pipeline, notebooks and tests all `import hri`, so logic
  such as "download the current CMS file" is written once instead of being copied into notebooks.
- **One source of truth for setup.** Dependencies, development tools (pytest, ruff), lint rules
  and the `hri` command are all declared in one standard file.
- **The `src/` layout** means tests run against the installed package, not against whatever
  happens to be in the current folder, which catches packaging mistakes early.

**Alternative considered.** Loose scripts plus `requirements.txt`: quicker to start, but code
gets duplicated between scripts and notebooks, and there is no single command to run the pipeline.

---

## D-018 · Raw layer: untouched text, one Parquet file per release · Accepted (step 3)

**Decision.** `hri ingest` stores every source exactly as published:

- **Sources are configuration.** `config/sources.yaml` lists each source with its downloader,
  required columns and minimum row count. Adding a source is a config change, not new code.
- **Every value stays text**, and markers such as `N/A`, `Not Available` or `.` are kept
  literally. Converting to numbers and deciding what counts as missing happens in the staging
  models (step 4), where it is visible and tested.
- **One Parquet file per release** (`data/raw/<source>/<release>.parquet`), old releases kept, plus a
  manifest recording download time, URL, SHA-256 fingerprint and row count. Each row also carries
  lineage columns (`_source`, `_release`, `_ingested_at`).
- **Skip unchanged releases.** Before downloading, ingestion asks the publisher for the current
  version (CMS "modified" date, CDC "rows updated" date, or the fiscal year for yearly zip files).
  A rerun with nothing new takes under two seconds.
- **Fail loudly, fail alone.** Missing required columns or too few rows stop that source with a
  clear error; retries handle brief outages; files are written under a temporary name and renamed
  only when complete; one failing source does not stop the others.

**Why.**
- If a cleaning rule turns out to be wrong, it can be fixed and rebuilt from the raw layer without
  downloading again, and nothing about the original data was lost.
- Keeping releases makes results reproducible and supplies the history needed to align time
  periods (D-008).
- Parquet is compressed and columnar: the 101 MB HCAHPS CSV is 848 KB as Parquet, and DuckDB
  reads it directly.
- Silent schema changes are the most common way public-data pipelines break; stopping on them
  turns a subtle wrong answer into an obvious error.

**Known raw-data quirks for the staging step** (found on the first real run):
`N/A`, `Not Available` and `Too Few to Report` in numeric columns; `.` for "no eligible
discharges" and percentages stored as text (`0.12%`) in the supplemental file; and a footer row
reading `End of worksheet` as the supplemental file's last line.

**Alternatives considered.**
- *Clean while downloading*: fewer steps, but mistakes in cleaning would be baked into the only
  copy of the data.
- *Overwrite with the latest file*: simpler storage, but history is lost and results cannot be
  reproduced.
- *CSV instead of Parquet*: readable in any editor, but large, slow and without column types.

---

## D-019 · dbt reads the raw Parquet files as sources, all releases at once · Accepted (step 4)

**Decision.**
- **Raw files are dbt sources.** `dbt/models/staging/_sources.yml` declares the six raw tables.
  Each one points DuckDB at `data/raw/<source>/*.parquet`, so `{{ source('raw', 'hrrp') }}` in a
  model becomes a direct read of the Parquet files. Nothing is loaded or copied first.
- **Every release, not only the latest.** The glob reads all stored releases together
  (`union_by_name`, so an added or reordered column in a new release does not break the read).
  Staging models filter to the release they need using the `_release` lineage column.
- **Layers and materialization.** `staging` models were planned as *views* (cheap, always
  reflect the raw files) and `marts` as *tables* (queried often by the model, the agent and
  Power BI). Each layer gets its own DuckDB schema. Staging was changed to tables in step 4b;
  see D-020.
- **One way to run it.** `hri dbt <command>` runs dbt from inside `dbt/`, so the relative paths
  in `profiles.yml` and the `raw_dir` variable resolve the same way from any folder. Running plain
  `dbt` inside `dbt/` works too. `profiles.yml` is committed because a local DuckDB file has no
  secrets.
- **A test keeps the two sides in sync**: every source in `config/sources.yaml` must be declared in
  dbt, and the reverse.

**Why.**
- Reading Parquet in place means no extra load step and no second copy of the data to keep fresh.
- Keeping all releases visible is what step 6 needs to line up time periods (D-008), without
  changing the sources later.
- Declaring sources (instead of hard-coding file paths in each model) puts them in dbt's lineage
  graph and documentation, and gives one place to change if the storage location moves (for
  example to S3, which DuckDB reads the same way).

**Alternatives considered.**
- *Load raw files into DuckDB tables with Python first*: a familiar "EL" step, but a duplicate
  copy of the data and one more thing to keep in sync.
- *Point sources only at the latest file*: simpler SQL, but step 6 would have to rewire every
  source to reach the older releases.
- *A `.dbt/profiles.yml` in the home folder* (dbt's default): standard for cloud warehouses with
  passwords, but a reviewer cloning the repo would have to create it by hand.

---

## D-020 · Staging conventions: strict conversion, tables, one naming scheme · Accepted (step 4)

**Decision.**
- **Layers.** `staging` (one model per raw source: rename, convert types, recode, drop
  non-data rows; no joins), `intermediate` (reshaping and joining, e.g. pivoting the survey to one
  row per hospital), `marts` (the star schema, from step 5). Names say the layer and the source:
  `stg_cms__hrrp`, `int_hcahps__hospital_scores`.
- **Staging tables pick the latest release** through the `latest_release()` macro.
- **Missing markers become NULL; everything else must convert.** The `to_number()` macro maps the
  known markers (`''`, `N/A`, `Not Available`, `Not Applicable`, `Too Few to Report`, `.`) to NULL,
  removes `,` and `%`, and then uses a strict `CAST`. An unknown marker stops the build.
- **The reason for a missing value is kept as data**: `score_status` in HRRP
  (`scored` / `too_few_cases` / `not_available` / `no_cases`), `readmissions_suppressed`,
  `is_suppressed` in PLACES, and the footnote codes.
- **One set of condition codes everywhere**: AMI, HF, PN, COPD, HIP_KNEE, CABG. The supplemental
  file's `pneumonia` and `THA/TKA` are recoded to match.
- **Staging models are tables, not views.**
- **Percentages stay in percent units** (`0.12%` becomes 0.12) and column names end in `_pct`.

**Why.**
- *Strict casts:* `TRY_CAST` would have turned the unexpected `Not Applicable` in HCAHPS into
  NULL without a word. The strict cast stopped the first build and named the value, which is how
  it was found and documented. Public data changes without notice; this is the cheapest defense.
- *Tables:* a view only stores the query, so its conversions run when someone reads it, not when
  dbt builds it. A bad value would pass `dbt build` and fail later in Power BI. A view also keeps
  the relative path to `data/raw`, so it breaks when queried from another folder. The data is
  about 580,000 rows and builds in about a second, so storing it costs nothing noticeable.
- *Reasons as data:* D-003. Small hospitals are missing for a reason, and the model and
  dashboard need to be able to tell "no data" from "good result".

**Reconciliation at build time** (step 4b): 18,330 HRRP rows (3,055 hospitals x 6 conditions),
11,720 scored and 6,610 missing, none with an unknown reason; ERR equals predicted / expected
within rounding; 2,304 of 2,945 hospitals penalized, 15 at the 3% cap; the payment reduction
percentage equals (1 - payment adjustment factor) x 100.

**Found while building.** For 3,123 hospital x condition pairs the public HRRP file shows N/A but
the supplemental file has the ratio (hospitals under the 25-case publishing threshold). Where both
have a value they are identical. This can widen the training data in step 7, with care: ratios
based on a handful of cases are noisy.

**Alternatives considered.**
- *`TRY_CAST` everywhere*: never fails, which is exactly the problem.
- *Views for staging* (dbt's usual default): fine on a cloud warehouse where tables are loaded
  first; here it moves failures to query time and ties results to the working folder.
- *Clean in pandas before dbt*: puts the rules in Python where analysts cannot review them as SQL,
  and loses dbt's lineage and tests.

---

## D-021 · Data tests: every staging rule is tested, known gaps warn · Accepted (step 4)

**Decision.** `hri dbt build` builds each model and then runs its tests; a failing test stops the
models that depend on it. 80 checks run in about 5 seconds:

- **Structure**: primary keys are unique and not null, including combined keys
  (hospital x condition, county x measure x value type).
- **Allowed values**: condition codes, `score_status` (a new CMS footnote code makes it
  `unknown`, which fails), peer groups 1-5, star ratings 1-5.
- **Ranges**: ERR 0.3-3, rates and survey scores 0-100, penalty 0-3%, dual proportion 0-1.
  Ranges catch unit changes (a percentage published as 0.12 one year and 12 the next).
- **Relationships**: every survey hospital has a profile; every peer comparison has a payment row.
- **Business rules**:
  - ERR = predicted / expected readmission rate.
  - Penalty reduction = (1 - payment adjustment factor) x 100.
  - CMS flags a condition exactly when ERR is above the peer median *and* the hospital had at
    least 25 eligible discharges (ties at 4 decimals allowed).
  - **The published penalty of all 2,945 hospitals is recomputed from its inputs**
    (neutrality modifier x sum of DRG ratio x (ERR - peer median), capped at 3%) and matches
    within 0.01 percentage points (largest difference 0.0063, from rounding).
  - Every raw row reaches staging except the rows removed on purpose.
  - Each measure table covers exactly one performance period (guards D-008).
- **Known gaps are warnings, not errors**, each explained where it is declared: 20 hospitals with
  HRRP results but no profile in the newer hospital file, and 8 penalized hospitals missing from
  the latest public HRRP release.
- **Failing rows are stored** in the `dbt_test__audit` schema, so a failure can be inspected
  with a query.
- Three generic tests (`unique_combination_of_columns`, `accepted_range`, `expression_is_true`)
  are written in the project (`dbt/tests/generic/`) instead of installing the `dbt_utils` package.

**Why.**
- Public data changes without notice. A test that fails is cheaper than a dashboard that is
  quietly wrong.
- Recomputing the penalty proves the project understands the program's formula exactly. The
  dollar-impact estimates in later steps depend on that formula.
- `warn` keeps real but understood gaps visible on every run without blocking it; an `error` for
  them would train everyone to ignore failures.
- Writing the three generic tests takes about 30 lines and shows how a test works: a SELECT that
  returns the rows breaking the rule. It also avoids a package download before the first build.

**Verified by breaking it.** Removing the footnote-7 mapping from `stg_cms__hrrp` made
205 rows `unknown`; the `score_status` test failed, the build reported an error, and the stored
failure row showed `('unknown', 205)`.

**Alternatives considered.**
- *`dbt_utils` / `dbt_expectations` packages*: more ready-made tests. Worth adding when the
  project needs more than these three; for now they add a dependency for little gain.
- *Great Expectations or Soda*: separate data-quality tools with their own config and reports;
  more than a dbt project of this size needs, and the checks would live outside the models they test.
- *Only row counts and not-null checks*: easy, but would miss every business-rule error above.

---

## D-022 · Link hospitals to counties by ZIP code, checked against the county name · Accepted (step 5)

**Problem.** CDC PLACES is keyed by 5-digit county FIPS code; the CMS hospital file has only a
county *name*. Matching names (step 2) reached 95.9% but cannot be trusted case by case:
"Baltimore" is both a county (24005) and an independent city (24510); Connecticut's 8 counties
were replaced in 2022 by 9 planning regions, which PLACES uses and CMS does not; spellings differ
(ST. LOUIS / Saint Louis). Nothing in a name match says when it picked the wrong county.

**Decision.**
- **Sources** (new ingestion kind `static_file`: a fixed file at a fixed URL, release set in the
  config, like `cms_zip` without the zip):
  - `census_zcta_county`: Census 2020 ZIP Code Tabulation Area (ZCTA) to county relationship
    file, with the land area of every overlap.
  - `census_ct_zcta_cousub`: Census 2022 Connecticut ZCTA to town file. Town codes start with
    the planning-region code, so it maps Connecticut ZIPs to the regions PLACES uses.
- **A ladder of methods** (built in step 5b), best first, with the method recorded per hospital:
  ZIP in one county → ZIP in several counties, pick the one whose name matches CMS → largest land
  share → name only (ZIP is not a ZCTA; in Connecticut, the hospital's city is matched to its
  town) → territory without PLACES data → unmatched.
- **Disagreements are flagged, not hidden**: where the ZIP's county and the CMS name differ, the
  row says so.

**What the data showed before building** (3,035 HRRP hospitals in US states): the ZIP lies in one
county for 2,139 (70%), spans several counties for 804 (26%), and is not a ZCTA for 92 (3%, e.g.
PO-box or single-organization ZIPs). Nationally 30% of ZCTAs cross a county line, so the ZIP
alone is not enough. 7 of 36 Connecticut hospitals have ZIPs outside the Connecticut file, which
is why the Connecticut fallback uses the town.

**Why.**
- Two independent signals (ZIP and name) that agree are far more trustworthy than either one,
  and where they disagree we know exactly which rows to review.
- Census files are public and need no account, so anyone can rebuild the project.
- Recording the method lets the model and dashboard treat medium-confidence links differently.

**Alternatives considered.**
- *HUD USPS ZIP-county crosswalk*: covers real ZIP codes including PO boxes and is updated
  quarterly, but needs a registered API token; a reviewer could not rebuild without signing up.
- *Name matching only*: simple, 95.9%, but silently wrong in the cases above.
- *Geocoding each address*: most precise, but depends on an external service for ~5,400
  addresses, which is more than the remaining few percent of hard cases justify.

**Known limits.** ZCTAs approximate ZIP codes and the 2020 file has land area but no population,
so "largest land share" can pick a large rural county over a smaller city where most people
live. That is why the name check comes before the land-share rule.

**Result (step 5b).** Models `stg_census__zcta_county`, `stg_census__ct_zcta_town`,
`int_census__zcta_county` (crosswalk on the PLACES map) and `int_hospitals__county` (the ladder),
plus the `clean_county_name()` macro.

- All 3,035 HRRP hospitals in US states are linked (100%): 2,139 by a single-county ZIP,
  798 by ZIP + agreeing name, 85 by name only, 6 by largest land share, 6 by Connecticut town,
  1 by single-county state (DC). Every linked code exists in PLACES.
- Against step 2's name matching: same county for 2,892; step 2 found no county for 124 and
  **two counties for 18** (Baltimore, St. Louis, Fairfax: county vs independent city), which a
  join would have turned into duplicate rows; it disagreed for 1.
- Names are compared using Census names, which keep the type ("Baltimore city" vs "Baltimore
  County"). CDC PLACES calls both "Baltimore", which is why step 2 could not tell them apart.
- 4 hospitals (1 in HRRP) have a CMS county name pointing elsewhere than their ZIP; two are in
  ZIPs entirely inside St. Louis city while CMS writes the county. They are a warning, for review.
- Some CMS county names cannot be resolved at all ("JEFFRSON DAVIS", "E. BATON ROUGE",
  "SCOTT BLUFF", "THE DISTRICT"); the ZIP links them anyway. No fuzzy matching was added: the
  ZIP already covers these, and fuzzy rules would create new silent errors.
- Tests: match rate at least 99.5% of HRRP hospitals (today 100%), golden records for five
  hand-checked hospitals (Baltimore city, St. Louis city, two Virginia independent cities,
  Yale-New Haven through the Connecticut fallback), crosswalk uniqueness and land shares.
  Removing the Connecticut rung on purpose failed the golden-record test while the match-rate
  test still passed (99.8%): a rate catches large breaks, golden records catch specific ones.
