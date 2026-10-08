# Model card · HRRP penalty-risk model

A model that ranks US hospitals by how large a Medicare readmission penalty they are likely to
receive, from public data about the hospital and its county. Built in step 7 of
[Hospital Readmission Intelligence](https://github.com/Saikrishna0107/Healthcare-readmission-intelligence);
decisions in [D-009](decisions.md) and [D-024](decisions.md); results in
[notebook 03](notebooks/03_model_results.html).

## What it predicts

- **Target:** `payment_reduction_pct`, the cut to a hospital's Medicare inpatient payments
  under the Hospital Readmissions Reduction Program (HRRP) for one fiscal year (0% to 3%).
- **Main use of the output:** the **ranking** within a year: which hospitals are most likely to
  fall in the **top quarter** of penalties.
- **One row** = one hospital in one fiscal year (`ml.ml_penalty_features`, 21,263 rows).

## Intended use

- **For:** analysts and quality teams who want to see which hospitals look like they are at high
  penalty risk, and which kinds of factors (volume, county conditions, patient survey) go with it,
  as a starting point for review.
- **Not for:** predicting a hospital's exact penalty, judging the quality of care at any single
  hospital, setting payments, or drawing conclusions about cause. The factors are associations
  in public data, not levers proven to change readmissions.

## Data

All public, no patient-level data:

- CMS HRRP files (target, discharge volumes, patient mix, FY 2020 - FY 2026)
- CMS Hospital General Information (ownership, emergency services)
- CMS HCAHPS patient survey (10 hospital scores)
- CDC PLACES county health measures (17 measures and the county population)
- US Census ZIP-to-county files, to link each hospital to its county (D-022)

37 features in five families: **volume** (2), **survey** (13), **county** (18), **patient mix**
(2: dual-eligible share and CMS peer group), **profile** (2: ownership, emergency services). Every column has a recorded role and a leakage review in
`dbt/models/ml/_ml.yml`, enforced by a test. Excluded on purpose: star ratings and other CMS
outputs that already use readmission results.

## How it was tested (D-024)

- **Train** on FY 2020 - 2023 (12,301 rows); **test once** on FY 2026 (2,945 hospitals).
  HRRP fiscal years use three-year overlapping patient periods, so FY 2024 - 2025 (which share
  patients with FY 2026) are left out entirely. A dbt test fails if any training period overlaps
  the test period.
- **Settings were tuned and the model was chosen** with 5-fold cross-validation grouped by
  hospital, on the training years only. Rule: best CV AUC; a simpler family (ridge < EBM <
  LightGBM) wins if it is within 0.01.
- **Metrics** are computed within the test year: AUC for the top quarter (main), AUC for any
  penalty, Spearman rank correlation, mean absolute error. 95% intervals come from 1,000 bootstrap
  resamples of hospitals; model differences use paired resamples.

## Results (FY 2026)

| Model | CV AUC | Test AUC top quarter | Spearman | MAE (pp) |
|---|---|---|---|---|
| Training average for everyone | - | 0.500 | - | 0.385 |
| Own penalty 3 years earlier | - | 0.697 [0.67-0.72] | 0.404 | 0.316 |
| Ridge regression | 0.683 | 0.715 [0.69-0.74] | 0.463 | 0.332 |
| EBM | 0.674 | 0.724 [0.70-0.74] | 0.423 | 0.334 |
| **LightGBM (chosen)** | **0.723** | **0.745** [0.73-0.76] | **0.502** | **0.314** |
| *Reference: own penalty 1 year earlier (shares 2/3 of patients)* | - | *0.898* | *0.766* | *0.171* |

- LightGBM beats ridge by **+0.030 AUC** (paired 95% interval +0.014 to +0.046) and the
  hospital's own history by **+0.048** (+0.025 to +0.070).
- **In practice:** of the 737 hospitals it flags as its top quarter, **50%** really are in the top
  quarter (25% by chance). Their average actual reduction is 0.60% against 0.26% for the others.
  About half of the flagged hospitals are therefore not top-quarter: this is a screening list,
  not a verdict.

## What drives the predictions

Explained two ways, grouped by feature family (per hospital, contributions summed within a
family, then the mean absolute value):

| Family | LightGBM (SHAP, pp) | EBM (pp) |
|---|---|---|
| Volume | 0.157 | 0.157 |
| County | 0.082 | 0.177 |
| Survey | 0.044 | 0.115 |
| Profile | 0.040 | 0.050 |
| Patient mix | 0.031 | 0.069 |

Both models put **volume** and **county conditions** first. Volume is partly mechanical: CMS
shrinks small hospitals' ratios toward 1.0, so they rarely get large penalties. Individual
county or survey features should not be read alone: they are highly correlated (county housing
and food insecurity correlate at 0.97) and the models split or offset their effects.

## Limits and known issues

- **Level bias.** The model predicts an average 0.46% for FY 2026; the actual average is 0.34%.
  Penalties roughly halved from FY 2023, and three of the four training years come before that.
  The ranking is unaffected; the predicted percentages should not be used as amounts.
- **Prior results do not carry across the FY 2023 change for LightGBM.** Adding the hospital's
  results from 3 years earlier helped ridge (+0.045 AUC) but not LightGBM (-0.007 [-0.021 to
  +0.006]), although it looked strongly better in cross-validation (0.771). The prior penalty in
  training comes from before the halving, the one for FY 2026 from after, and the trees learned
  cut points on the old scale. Cross-validation cannot catch this because its folds come from the
  same years. A candidate fix (prior penalty as a within-year rank) is noted for later; it was
  not tried, so that the test year is not used to pick it.
- **County data is a single recent PLACES release**, applied to all years. County conditions
  change slowly, but this is an approximation.
- **Missing survey data** (mostly small hospitals) is treated as information, not filled from
  elsewhere; the models learn what "no survey" tends to mean.
- **Association, not cause.** Nothing here shows that changing a feature would change a penalty.
- **Fairness.** Penalties are already adjusted by CMS for the share of patients with dual
  Medicare-Medicaid coverage (peer groups), which is why patient mix shows little signal on its
  own (notebook 02). The
  model has not been audited for differences in error across hospital types or regions; that
  would be needed before any real use.
- **Disclosure about the test year.** While sizing the EBM for run time, scratch experiments
  printed FY 2026 scores for a few EBM settings, and the 10-interaction setting was kept. Every
  setting and the final choice in the committed code come from cross-validation only, and the
  EBM was not chosen, so this did not affect the selected model. It is recorded for completeness.

## How to reproduce

```
hri model train
marimo edit notebooks/03_model_results.py
```

Outputs: `reports/model/metrics.json` (all numbers), `data/model/models.joblib` (fitted models,
not in git), `data/model/test_predictions.parquet`. Seeds are fixed (`--seed 0`).
