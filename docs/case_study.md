# Case study: Hospital Readmission Intelligence

**In one paragraph.** Medicare cuts payments to hospitals whose patients come back too often
within 30 days. I built an end-to-end analytics project on the public CMS, CDC and Census data
behind that program: a tested warehouse that reproduces Medicare's penalty for every hospital
and year, an analysis of what goes with higher penalties, a model that ranks hospitals by
next-year risk, a Power BI dashboard, and an AI assistant that answers questions in plain
English without ever making up a number. It took about three weeks, in ten steps, each
committed and explained.

[Code](https://github.com/Saikrishna0107/Healthcare-readmission-intelligence) ·
[Decision log](decisions.md) · [Model card](model_card.md) ·
[Notebooks](index.md#notebooks-with-results)

---

## 1. The business problem

The **Hospital Readmissions Reduction Program (HRRP)** compares each hospital's 30-day
readmissions for six conditions (heart attack, heart failure, pneumonia, COPD, hip/knee
replacement, bypass surgery) with what CMS expects for its patients. That comparison is the
**Excess Readmission Ratio (ERR)**. A hospital above its peer group's median ERR, with enough
cases, loses up to **3% of its Medicare base payments** for the whole year. In FY2026, 2,304 of
2,945 hospitals (78%) were penalized.

The people who care: hospital quality and finance teams (how big is our cut, and what drives
it?), health plans and consultants (which hospitals are at risk?), and analysts asked to answer
quick questions about the program. The project answers three questions:

1. **Who is penalized, and by how much?**
2. **Why?** Which hospital, patient-experience and community factors go with higher penalties?
3. **Who is at risk next year?**

## 2. The data, and the traps in it

Eleven public sources, about 3,000 hospitals, FY2019 to FY2026: the HRRP results and CMS's
supplemental penalty files, the HCAHPS patient survey, hospital profiles, CDC PLACES county
health measures, Census ZIP-to-county files and the CMS archive of past releases. No
patient-level data, no accounts, nothing that can't be downloaded again
([D-001](decisions.md#d-001--real-public-data-only--accepted)).

Most of the work was not modeling. It was finding where the data would give a wrong answer
without any error:

| Trap | What would have gone wrong | What I did |
|---|---|---|
| Penalties are judged against the **peer-group median**, not 1.0 | 1.0 as the threshold misclassifies hospitals near the line, where half of all results sit (ERR 0.96-1.04) | Use CMS's peer medians; reproduce the formula exactly ([D-014](decisions.md#d-014--penalties-are-judged-against-the-peer-group-median-not-10--accepted-step-2)) |
| **36% of results are missing**, mostly too few cases | Treated as zero, small hospitals look perfect | Keep missing as missing, with the reason ([D-003](decisions.md#d-003--missing-values-are-reasons-not-zeros--accepted)) |
| The current survey was collected **after** the readmissions it would explain | A driver that "predicts" the past: leakage | Pull archived survey releases and match each year's survey to a window that ends before its readmission period ([D-008](decisions.md#d-008--align-time-periods-to-prevent-data-leakage--accepted-implemented-at-step-6)) |
| A county name is not an ID: "Baltimore" is both a county and a city | 18 hospitals matched to two counties, so duplicated rows | Link by ZIP code, checked against the name: 100% of the 3,035 hospitals with a profile ([D-022](decisions.md#d-022--link-hospitals-to-counties-by-zip-code-checked-against-the-county-name--accepted-step-5)) |
| Each penalty uses **three years of patients**, sliding by one | A random train/test split tests the model on patients it already saw | Train FY2020-2023, test FY2026, whose period starts the day after FY2023's ends ([D-024](decisions.md#d-024--validation-by-time-without-shared-patients-and-a-leakage-review-for-every-feature--accepted-step-7)) |

**Proof the data is right:** recomputing every hospital's payment reduction from CMS's own
inputs (for each condition that counts, the DRG payment ratio times the ERR's distance above the
peer median; summed, times the neutrality modifier, capped at 3%) matches all **21,263
hospital-years** within 0.01 percentage points. It is a dbt test, so it runs on every rebuild.

## 3. What I built

```
CMS · CDC · Census ─► Python ingestion ─► raw Parquet ─► dbt + DuckDB ─► star schema
                                                         (211 tests)        │
               ┌──────────────────────────┬──────────────────────────────────┼─────────────┐
               ▼                          ▼                                  ▼             ▼
       penalty-risk model         semantic layer (MetricFlow)          Power BI     GitHub Actions
       ridge · EBM · LightGBM     ─► AI assistant (local LLM)          dashboard    CI + refresh
```

- **Pipeline.** Python downloads each release once, validates it and stores it untouched; dbt
  cleans and models it in DuckDB into a star schema. 211 data tests, with known gaps reported
  as warnings rather than hidden. DuckDB because it is a free, file-based analytical database
  that needs no server ([D-005](decisions.md#d-005--duckdb-as-the-warehouse--accepted-step-4)).
- **Analysis.** Three marimo notebooks, published with their results.
- **Model.** Three models against two baselines, explained with SHAP, documented in a model card.
- **AI assistant.** Questions in plain English, answered through a semantic layer (below).
- **Dashboard.** Five Power BI pages, kept as text files in git (PBIP), with a page that checks
  its own numbers.
- **Automation.** CI on every push; a scheduled rebuild from the sources twice a week that opens
  an issue when CMS publishes new data.

## 4. Findings

- **Patient experience at discharge goes with fewer readmissions, every year.** Hospitals in the
  lowest quarter of "care transition" scores average a heart-failure ERR of 1.020-1.032; the top
  quarter 0.979-0.985, in each year from FY2020 to FY2026, with the survey taken before the
  readmission period. It is an association, not proof of cause, but it is stable.
- **Poverty barely moves the penalty** (rank correlation -0.03), because CMS already compares
  each hospital only with peers serving a similar share of low-income patients. Without the peer
  groups, the analysis would have "found" the wrong driver.
- **Community conditions matter at first sight.** Where most adults lack reliable transportation,
  hospitals average a heart-failure ERR of 1.021; where fewest do, 0.986.
- **Penalties shrank after FY2022 and stayed lower.** The average cut fell from 0.53% to 0.32% in
  FY2023, when CMS left pneumonia out because of COVID-19, and has stayed near 0.33% since.
- **Pneumonia and heart failure drive the most penalties** (1,322 and 1,292 penalty-counting
  results in FY2026), bypass surgery the fewest (438).

## 5. The model: honest validation first

The model predicts each hospital's payment reduction and is judged on finding the **top quarter
of penalties**. "Penalized or not" is a weak question when 75-83% are penalized every year.

| Model | AUC, top quarter (FY2026) |
|---|---|
| Training average for everyone | 0.500 |
| The hospital's own penalty 3 years earlier | 0.697 |
| Ridge regression | 0.715 |
| Explainable Boosting Machine | 0.724 |
| **LightGBM (chosen by cross-validation, before looking at the test year)** | **0.745** |

- **In practice:** of the 737 hospitals it flags, 50% really are in the top quarter, against 25%
  by chance. It is a screening list, not a verdict.
- **The validation design mattered more than the algorithm.** On a random split, LightGBM would
  have reported 0.776, and "last year's penalty" 0.90, because neighbouring years share patients.
- **Drivers:** hospital volume first (partly mechanical: CMS shrinks small hospitals' ratios toward
  1.0), then county conditions, then patient experience. Both LightGBM (SHAP) and the EBM agree.
- **Known limit, stated in the model card:** the predicted level is too high (0.46% against an
  actual 0.34%) because penalties halved after most training years. The ranking holds; the
  amounts should not be used.

## 6. The AI assistant: numbers from the data, never from the model

The risk with an LLM on business data is a confident, wrong number. The design removes that risk
by construction ([D-010](decisions.md#d-010--llm-agent-through-a-semantic-layer-with-an-evaluation-set--accepted-step-8)):

1. **One definition per metric.** 17 metrics are defined once in a semantic layer (dbt
   MetricFlow), each reconciled with hand-written SQL in a test. "Average penalty" alone can be
   0.344% (all hospitals) or 0.440% (penalized only); the definition decides, not the model.
2. **The model writes a plan, not SQL and not the answer:** which metric, broken down by what,
   filtered how. Code checks and corrects the plan ("Maryland" becomes "MD"), MetricFlow writes
   the SQL, DuckDB runs it read-only, and code writes the answer from the result table.
3. **A local model** (IBM Granite 4.1, 3B parameters, via Ollama on a laptop CPU): no data leaves
   the machine and no API key is needed. Questions take 8-18 seconds.
4. **Measured, not assumed.** 42 test questions, written apart from the ones used to tune it: 34
   with answers from hand-written SQL, 8 that must be declined (patients, causes, forecasts,
   advice). The assistant gets **83%** right. Turning parts off shows what each adds: without
   the prompt examples 67%, without the code rules 69%.

What the evaluation found: picking the wrong metric is the main error (4 of 7). A "repair"
step that sent errors back to the model never saved an answer and five times turned a failure
into a confident answer to a different question. Both are reported rather than tuned away on
the test questions, which would make the score meaningless.

## 7. Making the dashboard trustworthy

The dashboard reads a Parquet copy of the star schema. Every DAX measure exists once per
semantic-layer metric, and a **Checks** page compares each one with MetricFlow for every year:
**0 mismatches in 136**. The dashboard, the assistant and the notebooks therefore give the same
number for the same question.

## 8. What did not work, and what I learned

- **Prior results helped the linear model but not the trees.** Cross-validation said they would
  help LightGBM (0.771); on the test year they did not, because the trees learned cut points on
  the pre-FY2023 penalty scale. Cross-validation cannot see a change between years; a later test
  year can.
- **The assistant's repair round was worse than no repair.** Letting the model retry after an
  error made it change the question to one it could answer.
- **Running the real app found real bugs.** One hospital in the payment file has no CMS profile,
  so no state; it ranked as "the lowest state" at 0%. The test set's own answer key had the
  same bug. Both are fixed and tested.
- **A dashboard title is a claim.** A table titled "hospitals at the 3% cap" was really a top-20
  filter and listed hospitals at 2.62%. Titles now say what the filter does.

## 9. What I would do next

- Rank-based prior features, tested on a new year (FY2027), not the one already seen.
- A fairness check of model errors across hospital types and regions before any real use.
- Dollar amounts: adding Medicare inpatient payments would turn percentages into money at stake.
- A second evaluation set for the assistant, and metric-choice improvements tested on it.

## 10. Skills shown

| Area | Where |
|---|---|
| SQL and data modeling | dbt models, star schema, 211 tests, penalty formula reproduced |
| Python | Ingestion package, CLI, 84 pytest tests, lint |
| Healthcare domain | HRRP rules, peer groups, ERR, HCAHPS, time alignment of releases |
| Statistics and ML | Time-based validation, bootstrap intervals, baselines, SHAP, model card |
| BI | Power BI (DAX, drill-through, PBIP in git), reconciled with the semantic layer |
| AI / LLM | Semantic-layer agent, local LLM, JSON-schema plans, evaluation with ablations |
| Engineering | GitHub Actions CI and scheduled refresh, reproducible from a fresh clone |
| Communication | Decision log with alternatives, model card, this case study |
