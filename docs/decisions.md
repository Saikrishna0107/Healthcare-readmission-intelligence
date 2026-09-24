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

## D-005 · DuckDB as the warehouse · Proposed (step 3–4)

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

---

## D-006 · dbt for transformations · Proposed (step 4)

**Decision.** Write all cleaning and modeling as dbt models (SQL files) on top of DuckDB.

**Why.** dbt is the industry standard for analytics engineering. It adds automated data tests,
documentation and a lineage graph showing how every table was built, which is what makes a
pipeline production-ready rather than a pile of scripts.

**Alternatives considered.** Plain SQL scripts or pandas: faster to start, but no tests, no
lineage and harder to maintain.

---

## D-007 · Star schema for the marts · Proposed (step 4–5)

**Decision.** Model the cleaned data as facts (readmissions, survey scores, community health)
and dimensions (hospital, condition, county).

**Why.** Power BI performs best on a star schema, the LLM agent writes more accurate SQL against
clean, well-named tables, and hospital BI job descriptions ask for dimensional modeling.

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

## D-012 · Python command-line runner instead of a Makefile · Proposed (step 3)

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
HRRP file, and define "penalised" and "dollars at risk" with the official formula.

**Why.** Using 1.0 as the line would misclassify hospitals near the threshold, which is exactly
where most hospitals are, and would ignore the adjustment CMS makes for hospitals that serve
lower-income patients.

**Also learned.** Because ERR is relative to an average hospital, about half of scored hospitals
are above 1.0 for every condition. "Share above 1.0" therefore cannot rank conditions; conditions
are compared by money at stake instead.

---

## D-015 · Notebooks are committed with their outputs · Accepted (step 2)

**Decision.** Exploration notebooks are run from start to finish on the project's own Python
environment and committed with their outputs (tables and charts). Key charts are also saved to
`images/` for the README.

**Why.** GitHub displays notebook outputs, so a reviewer can read the analysis and results
without installing anything. Running from start to finish before each commit proves the notebook
works in order, not only in a lucky sequence of manually run cells.

**Alternative considered.** Stripping outputs keeps diffs small, but then nobody can see the
results on GitHub, which defeats the purpose of a portfolio notebook.
