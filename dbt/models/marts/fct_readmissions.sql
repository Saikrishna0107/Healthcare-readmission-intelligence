-- Readmission results and their penalty inputs, every fiscal year.
-- Grain: one row per hospital x condition x fiscal year (FY 2019 - FY 2026).
--
-- Two CMS publications describe the same thing and are joined here:
--   public    the HRRP results on Provider Data (stg_cms__hrrp_history): counts, rates, ratio.
--             Hides the ratio when a hospital has fewer than 25 cases.
--   payment   the Supplemental Data File of that fiscal year (stg_cms__hrrp_peer_comparisons):
--             the ratio CMS used for the penalty, also for small hospitals, with the peer
--             group median and whether the condition counted. From FY 2020 on.
-- A full outer join keeps rows found in only one of them; in_public_file / in_payment_file say
-- which. Where both have a ratio they agree (to rounding), which a test checks.

with public as (
    select
        'FY' || (year(period_start) + 5)  as fiscal_year,  -- mapping explained in dim_fiscal_year
        *
    from {{ ref('stg_cms__hrrp_history') }}
),

payment as (
    select * from {{ ref('stg_cms__hrrp_peer_comparisons') }}
)

select
    coalesce(pub.fiscal_year, pay.fiscal_year)                  as fiscal_year,
    -- FY 2026 starts 2025-10-01. A date column, because the semantic layer ties every measure
    -- to a time column (D-025); same value as dim_fiscal_year.fiscal_year_start.
    make_date(substr(coalesce(pub.fiscal_year, pay.fiscal_year), 3)::integer - 1, 10, 1)
                                                                as fiscal_year_start,
    coalesce(pub.facility_id, pay.facility_id)                  as facility_id,
    coalesce(pub.condition, pay.condition)                      as condition,

    pub.facility_id is not null                                 as in_public_file,
    pay.facility_id is not null                                 as in_payment_file,

    -- Public results
    pub.discharges,
    pub.readmissions,
    pub.readmissions_suppressed,
    pub.predicted_readmission_rate,
    pub.expected_readmission_rate,
    pub.excess_readmission_ratio,
    pub.score_status,
    pub.footnote_code,

    -- Penalty inputs
    pay.eligible_discharges,
    pay.excess_readmission_ratio                                as payment_excess_readmission_ratio,
    pay.peer_group_median_err,
    pay.is_above_peer_median                                    as counts_toward_penalty,
    pay.drg_payment_ratio,
    -- This condition's share of the penalty before the neutrality modifier and the 3% cap:
    -- DRG payment ratio x (ratio - peer median), only when the condition counts.
    case
        when pay.is_above_peer_median
            then pay.drg_payment_ratio * (pay.excess_readmission_ratio - pay.peer_group_median_err)
        when pay.facility_id is not null then 0
    end                                                         as penalty_contribution
from public as pub
full join payment as pay
    on pay.facility_id = pub.facility_id
   and pay.condition = pub.condition
   and pay.fiscal_year = pub.fiscal_year
