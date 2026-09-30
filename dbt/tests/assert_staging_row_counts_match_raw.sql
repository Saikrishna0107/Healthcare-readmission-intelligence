-- Every raw row of the latest release must arrive in staging, except rows removed on purpose.
-- Returns the models whose count differs from what the raw data says it should be.
--
-- Catches rows lost or duplicated by a filter, a reshape or (later) a join going wrong.
-- Rows removed on purpose, and why:
--   hrrp_supplemental: the "End of worksheet" footer line
--   places_county:     the national "US" row
-- The supplemental condition columns are reshaped to 6 rows per hospital.

with raw_counts as (
    select
        (select count(*) from {{ latest_release('hrrp') }})                                   as hrrp,
        (select count(*) from {{ latest_release('hrrp_supplemental') }}
            where "Hospital CCN" <> 'End of worksheet')                                       as supplemental,
        (select count(*) from {{ latest_release('hospital_info') }})                          as hospitals,
        (select count(*) from {{ latest_release('hcahps') }})                                 as hcahps,
        (select count(*) from {{ latest_release('footnotes') }})                              as footnotes,
        (select count(*) from {{ latest_release('places_county') }} where "StateAbbr" <> 'US') as places
),

comparison as (
    select 'stg_cms__hrrp' as model, hrrp as expected,
           (select count(*) from {{ ref('stg_cms__hrrp') }}) as actual from raw_counts
    union all
    select 'stg_cms__hrrp_payment_adjustments', supplemental,
           (select count(*) from {{ ref('stg_cms__hrrp_payment_adjustments') }}) from raw_counts
    union all
    select 'stg_cms__hrrp_peer_comparisons', supplemental * 6,
           (select count(*) from {{ ref('stg_cms__hrrp_peer_comparisons') }}) from raw_counts
    union all
    select 'stg_cms__hospitals', hospitals,
           (select count(*) from {{ ref('stg_cms__hospitals') }}) from raw_counts
    union all
    select 'stg_cms__hcahps', hcahps,
           (select count(*) from {{ ref('stg_cms__hcahps') }}) from raw_counts
    union all
    select 'stg_cms__footnotes', footnotes,
           (select count(*) from {{ ref('stg_cms__footnotes') }}) from raw_counts
    union all
    select 'stg_cdc__places_county', places,
           (select count(*) from {{ ref('stg_cdc__places_county') }}) from raw_counts
)

select *
from comparison
where expected <> actual
