# Hospital Readmission Intelligence

> **Status: work in progress.** The project is built in public, step by step. Every important
> decision is committed separately and explained in [docs/decisions.md](docs/decisions.md).

## The problem

Medicare's **Hospital Readmissions Reduction Program (HRRP)** cuts up to **3% of a hospital's
Medicare base payments** when too many patients come back within 30 days of discharge for
heart attack, heart failure, pneumonia, COPD, hip/knee replacement or bypass surgery.

This project uses **real, public CMS and CDC data** on about 3,000 US hospitals to answer
three questions a hospital or health plan would pay for:

1. **Which hospitals are at risk** of a readmission penalty?
2. **Why?** Which drivers (patient experience, hospital profile, community health) explain the risk?
3. **What is it worth?** How many Medicare dollars are at stake, and what would improvement save?

## Data (all public, no patient-level data)

| Source | Grain (one row =) | Role in the project |
|---|---|---|
| [CMS Hospital Readmissions Reduction Program](https://data.cms.gov/provider-data/dataset/9n3s-kdb3) | hospital × condition | **Target**: Excess Readmission Ratio (ERR) |
| [CMS HRRP Supplemental Data Files](https://www.cms.gov/medicare/payment/prospective-payment-systems/acute-inpatient-pps/archived-supplemental-data-files) (FY 2020–2026) | hospital × fiscal year | Peer group, peer-group median ERRs, penalty indicators, actual payment reduction |
| [CMS Patient Survey (HCAHPS) – Hospital](https://data.cms.gov/provider-data/dataset/dgck-syfz) | hospital × survey answer | Drivers: discharge information, communication scores |
| [CMS Hospital General Information](https://data.cms.gov/provider-data/dataset/xubh-q36u) | hospital | Hospital profile: type, ownership, county, star rating |
| [CDC PLACES – County Data](https://data.cdc.gov/500-Cities-Places/PLACES-Local-Data-for-Better-Health-County-Data-20/swc5-untb) | county × health measure | Community context: chronic disease, insurance, transportation |
| [Census ZCTA–county relationship files](https://www.census.gov/geographies/reference-files/time-series/geo/relationship-files.html) (2020, plus Connecticut 2022) | ZIP area × county | Links each hospital's ZIP code to the county code PLACES uses ([why](docs/decisions.md#d-022--link-hospitals-to-counties-by-zip-code-checked-against-the-county-name--accepted-step-5)) |

| [CMS hospital data archive](https://data.cms.gov/provider-data/archived-data/hospitals) (quarterly snapshots since 2019) | snapshot × the rows above | Past releases of HRRP, the patient survey and hospital profiles, to line up time periods ([why](docs/decisions.md#d-023--historical-releases-from-the-cms-archive-matched-by-period--accepted-step-6)) |

More sources (Medicare inpatient payments, complications, spending per beneficiary) are added
when the project reaches the step that needs them.

## What the data shows so far

From the data exploration notebook
([read it with results](https://saikrishna0107.github.io/Healthcare-readmission-intelligence/notebooks/01_data_exploration.html)
· [source](notebooks/01_data_exploration.py)):

- **Small differences decide penalties.** Half of all hospital-condition scores fall between an
  Excess Readmission Ratio of 0.96 and 1.04.
- **Penalties are common.** 77% of HRRP hospitals are above 1.0 on at least one condition.
  CMS judges each hospital against the median of its peer group (hospitals with a similar
  share of low-income patients), not against 1.0.
- **Missing is not zero.** 36% of scores are missing, mostly because a hospital had too few
  cases. Treating them as zero would make small hospitals look perfect.
- **A data-leakage trap.** The current patient survey was collected *after* the readmission
  period it would explain, so archived survey releases are needed to line the periods up.
- **A first driver.** Hospitals with the best discharge-information scores average a
  heart-failure ratio of 0.98; those with the lowest average 1.02 (association, not causation).

![Discharge information vs heart-failure readmissions](images/04_discharge_info_vs_hf_err.png)

From the cleaned, tested data ([D-021](docs/decisions.md#d-021--data-tests-every-staging-rule-is-tested-known-gaps-warn--accepted-step-4)):

- **The penalty formula is reproduced exactly, every year.** Recomputing each hospital's payment
  reduction from CMS's published inputs matches all 21,263 hospital-years from FY 2020 to FY 2026
  within 0.01 percentage points. In FY 2026, 2,304 hospitals (78%) are penalized; 15 hit the 3% cap.
- **Penalties shrank after FY 2022 and stayed lower.** The average cut fell from 0.53% of
  Medicare base payments (FY 2022) to 0.32% (FY 2023), when CMS left pneumonia out because of
  COVID-19, and has stayed between 0.32% and 0.34% since; the share penalized went from 82% to
  75-79%. Why it stayed low is a question for the time-aligned data in step 6c
  ([D-023](docs/decisions.md#d-023--historical-releases-from-the-cms-archive-matched-by-period--accepted-step-6)).
- **Being above the median is not enough.** A condition counts toward the penalty only with at
  least 25 eligible discharges; 1,547 hospital-condition pairs are above their peer median but
  too small to be penalized.
- **Every HRRP hospital with a profile has a county.** Linking by ZIP code, checked against the
  county name, reaches all 3,035 HRRP hospitals that have a hospital profile (20 have none, so
  no ZIP code), up from 95.9% by name alone. Names
  alone also matched 18 hospitals to *two* counties (Baltimore, St. Louis and Fairfax are each
  both a county and an independent city), which would have duplicated them in any analysis
  ([D-022](docs/decisions.md#d-022--link-hospitals-to-counties-by-zip-code-checked-against-the-county-name--accepted-step-5)).
- **Community context matters, at first sight.** Hospitals in the quarter of counties where most
  adults lack reliable transportation average a heart-failure ERR of 1.021; in the quarter where
  fewest do, 0.986 (association, not causation; 1,880 hospitals with that measure).
- **A driver that holds year after year, without leakage.** With each year's survey taken from
  a window that ends before its readmission period does
  ([D-008](docs/decisions.md#d-008--align-time-periods-to-prevent-data-leakage--accepted-implemented-at-step-6)),
  hospitals in the lowest quarter of "care transition" scores (were the patient's needs
  considered when planning discharge) average a heart-failure ERR of 1.020 - 1.032, the top
  quarter 0.979 - 0.985, in every fiscal year from FY 2020 to FY 2026 (correlation about -0.25
  each year; association, not causation).
- **Community data has gaps.** Kentucky and Pennsylvania have no 2023 chronic disease estimates
  in the current PLACES release (190 HRRP hospitals), and social needs measures cover 2,299 of
  3,144 counties. They stay NULL, flagged, never filled in
  ([D-007](docs/decisions.md#d-007--star-schema-for-the-marts--accepted-step-5)).

## Planned architecture

```
CMS / CDC APIs ──► Python ingestion ──► raw Parquet ──► dbt + DuckDB (staging ► marts, tested)
                                                               │
                        ┌──────────────────────────────────────┼─────────────────────┐
                        ▼                                      ▼                     ▼
             ML: penalty-risk model               LLM agent: questions in       Power BI
             (3-model comparison + SHAP)          plain English ► governed SQL   dashboard
```

## Roadmap

- [x] 1. Project skeleton, README and decision log
- [x] 2. Data exploration: what each dataset contains and its traps
- [x] 3. Ingestion from the CMS and CDC APIs
- [x] 4. Cleaning (dbt staging models), missing-value reasons and 80 data tests
- [x] 5. Hospital-to-county join with a match-rate test, first star-schema tables
- [x] 6. Archived data to align time periods (prevents data leakage)
- [ ] 7. Baseline model, then a three-model comparison
- [ ] 8. LLM question-answering agent with an evaluation set
- [ ] 9. Power BI dashboard
- [ ] 10. CI and scheduled data refresh

## Running it yourself

Requires Python 3.12. From the project folder:

```bash
python -m venv .venv
.venv/Scripts/pip install -e ".[dev]"      # macOS/Linux: .venv/bin/pip
```

This installs the project's own package (`src/hri`) plus the development tools (pytest, ruff).

### Pipeline commands

```bash
.venv/Scripts/hri ingest                 # download new releases of every source (skips stored ones)
.venv/Scripts/hri ingest --only hrrp     # just one source
.venv/Scripts/hri status                 # what is stored, which release, how many rows
.venv/Scripts/hri dbt build              # clean the data into data/hri.duckdb and run its 192 checks
.venv/Scripts/python -m pytest           # run the tests (no internet needed)
```

`hri dbt` passes its arguments to [dbt](https://docs.getdbt.com/) and runs it from the
[dbt/](dbt/) folder, for example `hri dbt debug` (check the setup) or
`hri dbt docs generate` then `hri dbt docs serve` (browse every table and the lineage graph).
dbt reads the raw Parquet files in place through DuckDB
([why](docs/decisions.md#d-019--dbt-reads-the-raw-parquet-files-as-sources-all-releases-at-once--accepted-step-4)).

The cleaned tables live in `data/hri.duckdb`, in the schemas `staging`, `intermediate` and `marts`
([conventions](docs/decisions.md#d-020--staging-conventions-strict-conversion-tables-one-naming-scheme--accepted-step-4)).
Query them from Python or any DuckDB client:

```python
import duckdb
con = duckdb.connect("data/hri.duckdb", read_only=True)
con.sql("select score_status, count(*) from staging.stg_cms__hrrp group by 1").show()
con.sql("select state, count(*), avg(diabetes_pct) from marts.dim_county group by 1").show()
con.sql("select fiscal_year, avg(payment_reduction_pct) from marts.fct_hospital_year group by 1 order by 1").show()
```

The first `hri ingest` also downloads every archived CMS snapshot since 2019 (about 500 MB,
a few minutes); later runs only fetch snapshots published since.
Sources are listed in [config/sources.yaml](config/sources.yaml). Each release is stored untouched
as `data/raw/<source>/<release>.parquet`, with a download log in `data/raw/manifest.json`
([why](docs/decisions.md#d-018--raw-layer-untouched-text-one-parquet-file-per-release--accepted-step-3)).

Notebooks use [marimo](https://marimo.io) and are plain `.py` files:

```bash
.venv/Scripts/marimo edit notebooks/01_data_exploration.py     # open as an interactive notebook
.venv/Scripts/python notebooks/01_data_exploration.py          # or run it as a script
```

The notebook runs `hri ingest` for the sources it needs, so the first run downloads the data
(about 110 MB) and later runs reuse it.
After changing a notebook, refresh its published page:

```bash
.venv/Scripts/marimo export html notebooks/01_data_exploration.py -o docs/notebooks/01_data_exploration.html
```

## Following the progress

- **Commit history**: one commit per step, each message says what was decided and why.
- **[docs/decisions.md](docs/decisions.md)**: every major decision with its reasoning and the
  alternatives that were considered.
