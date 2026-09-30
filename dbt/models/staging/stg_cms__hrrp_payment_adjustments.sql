-- HRRP Supplemental Data File: the hospital-level part.
-- Grain: one row per hospital. The actual FY 2026 penalty and the inputs CMS used for it.

with source as (
    select * from {{ latest_release('hrrp_supplemental') }}
    -- The file's last line is a footer, not a hospital.
    where "Hospital CCN" <> 'End of worksheet'
)

select
    "Hospital CCN"                                              as facility_id,
    _release                                                    as fiscal_year,
    {{ to_number('"Payment adjustment factor"') }}              as payment_adjustment_factor,
    -- Percent units: 0.12 means Medicare base payments are cut by 0.12%.
    {{ to_number('"Payment reduction percentage"') }}           as payment_reduction_pct,
    {{ to_number('"Payment reduction percentage"') }} > 0       as is_penalized,
    -- Share of Medicare patients who are also on Medicaid; decides the peer group.
    {{ to_number('"Dual proportion"') }}                        as dual_proportion,
    {{ to_number('"Peer group assignment"', 'integer') }}       as peer_group,
    {{ to_number('"Neutrality modifier"') }}                    as neutrality_modifier,
    _ingested_at::timestamptz                                   as ingested_at
from source
