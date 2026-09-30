-- Recompute every hospital's HRRP payment reduction from the inputs CMS publishes, and return
-- the hospitals where it does not match the published reduction.
--
-- CMS formula (FY2019 onward):
--   reduction = neutrality modifier x sum over penalized conditions of
--               DRG payment ratio x (ERR - peer group median ERR),     capped at 3%
-- A condition counts only when CMS flags it (ERR above the peer median and at least 25
-- eligible discharges).
--
-- Passing means we understand the penalty exactly, which the dollar-impact estimates in later
-- steps rely on. The published inputs are rounded to 4 decimals, so a difference of up to
-- 0.01 percentage points is rounding, not an error (the largest seen is 0.0063).

with condition_penalties as (
    select
        facility_id,
        coalesce(
            sum(drg_payment_ratio * (excess_readmission_ratio - peer_group_median_err))
                filter (where is_above_peer_median),
            0
        ) as unadjusted_penalty
    from {{ ref('stg_cms__hrrp_peer_comparisons') }}
    group by facility_id
),

recomputed as (
    select
        a.facility_id,
        a.payment_reduction_pct                                                  as published_pct,
        least(p.unadjusted_penalty * a.neutrality_modifier * 100, 3)             as recomputed_pct
    from {{ ref('stg_cms__hrrp_payment_adjustments') }} as a
    join condition_penalties as p using (facility_id)
)

select *
from recomputed
where abs(recomputed_pct - published_pct) > 0.01
