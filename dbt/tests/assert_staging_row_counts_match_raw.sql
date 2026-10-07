-- Every raw row a staging model reads must arrive in it, except rows removed on purpose.
-- Returns the models whose count differs from what the raw data says it should be.
--
-- Catches rows lost or duplicated by a filter, a reshape or a join going wrong. The expected
-- counts are written independently of the models, straight from the raw files.
-- Rows removed on purpose, and why:
--   hrrp_supplemental: the footer line and empty rows (all fiscal years)
--   places_county:     the national "US" row
--   hcahps_archive:    answer-percentage rows (only summary scores are kept), and every
--                      snapshot except the latest one of each survey window
--   hrrp_archive:      every snapshot except the latest one of each performance period
-- The supplemental condition columns are reshaped to one row per hospital x condition, for
-- the conditions present in that year's file (5 in FY 2023, 6 otherwise).

with raw_counts as (
    select
        (select count(*) from {{ latest_release('hrrp') }})                                   as hrrp,
        (select count(*) from {{ source('raw', 'hrrp_supplemental') }}
            where trim("Hospital CCN") not in ('', 'end of worksheet', 'End of worksheet'))  as supplemental,
        (select count(*) filter (where "Number of eligible discharges for pneumonia" is not null) * 1
              + count(*) * 5
            from {{ source('raw', 'hrrp_supplemental') }}
            where trim("Hospital CCN") not in ('', 'end of worksheet', 'End of worksheet'))  as supplemental_conditions,
        (select count(*) from {{ source('raw', 'hrrp_archive') }}
            where _release in (select max(_release) from {{ source('raw', 'hrrp_archive') }}
                               group by "Start Date", "End Date"))                           as hrrp_history,
        (select count(*) from {{ source('raw', 'hcahps_archive') }}
            where regexp_matches("HCAHPS Measure ID", '_(LINEAR_SCORE|STAR_RATING)$')
              and _release in (select max(_release) from {{ source('raw', 'hcahps_archive') }}
                               group by coalesce("Start Date", "Measure Start Date"),
                                        coalesce("End Date", "Measure End Date")))           as hcahps_history,
        (select count(*) from {{ source('raw', 'hospital_info_archive') }})                   as hospitals_history,
        (select count(*) from {{ latest_release('hospital_info') }})                          as hospitals,
        (select count(*) from {{ latest_release('hcahps') }})                                 as hcahps,
        (select count(*) from {{ latest_release('footnotes') }})                              as footnotes,
        (select count(*) from {{ latest_release('places_county') }} where "StateAbbr" <> 'US') as places,
        (select count(*) from {{ latest_release('census_zcta_county') }})                     as zcta_county,
        (select count(*) from {{ latest_release('census_ct_zcta_cousub') }})                  as ct_zcta_town
),

comparison as (
    select 'stg_cms__hrrp' as model, hrrp as expected,
           (select count(*) from {{ ref('stg_cms__hrrp') }}) as actual from raw_counts
    union all
    select 'stg_cms__hrrp_payment_adjustments', supplemental,
           (select count(*) from {{ ref('stg_cms__hrrp_payment_adjustments') }}) from raw_counts
    union all
    select 'stg_cms__hrrp_peer_comparisons', supplemental_conditions,
           (select count(*) from {{ ref('stg_cms__hrrp_peer_comparisons') }}) from raw_counts
    union all
    select 'stg_cms__hospitals', hospitals,
           (select count(*) from {{ ref('stg_cms__hospitals') }}) from raw_counts
    union all
    select 'stg_cms__hcahps', hcahps,
           (select count(*) from {{ ref('stg_cms__hcahps') }}) from raw_counts
    union all
    select 'stg_cms__hrrp_history', hrrp_history,
           (select count(*) from {{ ref('stg_cms__hrrp_history') }}) from raw_counts
    union all
    select 'stg_cms__hcahps_history', hcahps_history,
           (select count(*) from {{ ref('stg_cms__hcahps_history') }}) from raw_counts
    union all
    select 'stg_cms__hospitals_history', hospitals_history,
           (select count(*) from {{ ref('stg_cms__hospitals_history') }}) from raw_counts
    union all
    select 'stg_cms__footnotes', footnotes,
           (select count(*) from {{ ref('stg_cms__footnotes') }}) from raw_counts
    union all
    select 'stg_cdc__places_county', places,
           (select count(*) from {{ ref('stg_cdc__places_county') }}) from raw_counts
    union all
    select 'stg_census__zcta_county', zcta_county,
           (select count(*) from {{ ref('stg_census__zcta_county') }}) from raw_counts
    union all
    select 'stg_census__ct_zcta_town', ct_zcta_town,
           (select count(*) from {{ ref('stg_census__ct_zcta_town') }}) from raw_counts
)

select *
from comparison
where expected <> actual
