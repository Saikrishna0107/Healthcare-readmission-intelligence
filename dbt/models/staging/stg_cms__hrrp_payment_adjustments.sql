-- HRRP Supplemental Data Files: the hospital-level part, every fiscal year (FY 2020 - FY 2026).
-- Grain: one row per hospital x fiscal year. The actual penalty and the inputs CMS used for it.

with source as (
    select * from {{ hrrp_supplemental_rows() }}
),

cleaned as (
    select
        "Hospital CCN"                                              as facility_id,
        _release                                                    as fiscal_year,
        {{ to_number('"Payment adjustment factor"') }}              as payment_adjustment_factor,
        -- Percent units: 0.12 means Medicare base payments are cut by 0.12%.
        -- Published from FY 2022 on, where it always equals (1 - factor) x 100 exactly.
        {{ to_number('"Payment reduction percentage"') }}           as published_reduction_pct,
        -- Share of Medicare patients who are also on Medicaid; decides the peer group.
        {{ to_number('"Dual proportion"') }}                        as dual_proportion,
        {{ to_number('"Peer group assignment"', 'integer') }}       as peer_group,
        {{ to_number('"Neutrality modifier"') }}                    as neutrality_modifier,
        _ingested_at::timestamptz                                   as ingested_at
    from source
)

select
    facility_id,
    fiscal_year,
    fiscal_year = max(fiscal_year) over ()                      as is_latest_fiscal_year,
    payment_adjustment_factor,
    -- FY 2020 and FY 2021 files have no percentage column, so it is computed from the factor
    -- the same way; payment_reduction_is_derived says which rows.
    coalesce(published_reduction_pct, round((1 - payment_adjustment_factor) * 100, 4))
                                                                as payment_reduction_pct,
    published_reduction_pct is null                             as payment_reduction_is_derived,
    payment_adjustment_factor < 1                               as is_penalized,
    dual_proportion,
    peer_group,
    neutrality_modifier,
    ingested_at
from cleaned
