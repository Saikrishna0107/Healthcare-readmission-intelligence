-- Fiscal year dimension: which data belongs to which HRRP year, lined up without leakage (D-008).
-- Grain: one row per HRRP fiscal year with readmission results in the archive (FY 2019 - FY 2026).
--
-- Three clocks have to be lined up:
--   1. The fiscal year the penalty applies to (FY 2026 = Oct 2025 - Sep 2026).
--   2. The readmission performance period it is based on: three years of discharges, starting
--      July 1 five calendar years earlier (FY 2026: Jul 2021 - Jun 2024). The test
--      supplemental_err_matches_public_err in fct_readmissions proves this mapping: shifted by
--      one year, almost no ratio would match.
--   3. The patient survey window used to explain it: the latest window that ends on or before
--      the end of the readmission period. A later window would describe care that happened
--      after the readmissions it is meant to explain, which is data leakage.
--
-- FY 2022's period ends 2019-12-01, not 12-31: CMS stopped 30 days early so that no follow-up
-- claims from 2020 (COVID-19) count. The rule uses that date as published, so FY 2022 gets the
-- window ending June 2019, the same one as FY 2021. FY 2019 has no window (the archive starts
-- with April 2017 - March 2018).

with readmission_periods as (
    select
        'FY' || (year(period_start) + 5)                  as fiscal_year,
        period_start                                      as readmission_period_start,
        period_end                                        as readmission_period_end,
        any_value(period_first_release)::date             as readmission_results_published
    from {{ ref('stg_cms__hrrp_history') }}
    group by period_start, period_end
),

survey_windows as (
    select distinct period_start, period_end
    from {{ ref('stg_cms__hcahps_history') }}
),

aligned as (
    select
        r.*,
        -- Latest window ending in time; on a tie, the longer window.
        arg_max(s.period_start, (s.period_end, -epoch(s.period_start)))  as survey_period_start,
        max(s.period_end)                                                as survey_period_end
    from readmission_periods as r
    left join survey_windows as s on s.period_end <= r.readmission_period_end
    group by all
)

select
    fiscal_year,
    make_date(year(readmission_period_start) + 4, 10, 1)                   as fiscal_year_start,
    make_date(year(readmission_period_start) + 5, 9, 30)                   as fiscal_year_end,

    readmission_period_start,
    readmission_period_end,
    readmission_results_published,

    survey_period_start,
    survey_period_end,
    -- 12 for a normal window; 6 and 9 for the shortened windows around 2020 (COVID-19).
    datediff('month', survey_period_start, survey_period_end + 1)         as survey_period_months,
    readmission_period_end - survey_period_end                            as survey_ends_days_before_readmissions,

    fiscal_year in (
        select fiscal_year from {{ ref('stg_cms__hrrp_payment_adjustments') }}
    )                                                                     as has_payment_file,
    fiscal_year = max(fiscal_year) over ()                                as is_latest_fiscal_year
from aligned
