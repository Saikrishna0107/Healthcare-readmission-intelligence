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
| [CMS HRRP Supplemental Data File](https://www.cms.gov/medicare/payment/prospective-payment-systems/acute-inpatient-pps/fy-2026-ipps-final-rule-home-page) (FY 2026) | hospital | Peer group, peer-group median ERRs, penalty indicators, actual payment reduction |
| [CMS Patient Survey (HCAHPS) – Hospital](https://data.cms.gov/provider-data/dataset/dgck-syfz) | hospital × survey answer | Drivers: discharge information, communication scores |
| [CMS Hospital General Information](https://data.cms.gov/provider-data/dataset/xubh-q36u) | hospital | Hospital profile: type, ownership, county, star rating |
| [CDC PLACES – County Data](https://data.cdc.gov/500-Cities-Places/PLACES-Local-Data-for-Better-Health-County-Data-20/swc5-untb) | county × health measure | Community context: chronic disease, insurance, transportation |
| [Census ZCTA–county relationship files](https://www.census.gov/geographies/reference-files/time-series/geo/relationship-files.html) (2020, plus Connecticut 2022) | ZIP area × county | Links each hospital's ZIP code to the county code PLACES uses ([why](docs/decisions.md#d-022--link-hospitals-to-counties-by-zip-code-checked-against-the-county-name--accepted-step-5)) |

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

- **The penalty formula is reproduced exactly.** Recomputing each hospital's FY 2026 payment
  reduction from CMS's published inputs matches all 2,945 hospitals within 0.01 percentage points.
  2,304 hospitals (78%) are penalized; 15 hit the 3% cap.
- **Being above the median is not enough.** A condition counts toward the penalty only with at
  least 25 eligible discharges; 1,547 hospital-condition pairs are above their peer median but
  too small to be penalized.

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
- [ ] 5. Hospital-to-county join with a match-rate test
- [ ] 6. Archived data to align time periods (prevents data leakage)
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
.venv/Scripts/hri ingest                 # download new releases of every source (skips unchanged ones)
.venv/Scripts/hri ingest --only hrrp     # just one source
.venv/Scripts/hri status                 # what is stored, which release, how many rows
.venv/Scripts/hri dbt build              # clean the data into data/hri.duckdb and run its 80 tests
.venv/Scripts/python -m pytest           # run the tests (no internet needed)
```

`hri dbt` passes its arguments to [dbt](https://docs.getdbt.com/) and runs it from the
[dbt/](dbt/) folder, for example `hri dbt debug` (check the setup) or
`hri dbt docs generate` then `hri dbt docs serve` (browse every table and the lineage graph).
dbt reads the raw Parquet files in place through DuckDB
([why](docs/decisions.md#d-019--dbt-reads-the-raw-parquet-files-as-sources-all-releases-at-once--accepted-step-4)).

The cleaned tables live in `data/hri.duckdb`, in the schemas `staging` and `intermediate`
([conventions](docs/decisions.md#d-020--staging-conventions-strict-conversion-tables-one-naming-scheme--accepted-step-4)).
Query them from Python or any DuckDB client:

```python
import duckdb
con = duckdb.connect("data/hri.duckdb", read_only=True)
con.sql("select score_status, count(*) from staging.stg_cms__hrrp group by 1").show()
```

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
