-- Hospital General Information, latest release.
-- Grain: one row per hospital (all hospital types, not only the ones HRRP covers).

{%- set measure_groups = {'mort': 'MORT', 'safety': 'Safety', 'readm': 'READM'} %}

with source as (
    select * from {{ latest_release('hospital_info') }}
)

select
    "Facility ID"                                                    as facility_id,
    "Facility Name"                                                  as facility_name,
    "Address"                                                        as address,
    "City/Town"                                                      as city,
    "State"                                                          as state,
    "ZIP Code"                                                       as zip_code,
    -- Name only, no FIPS code: matching it to CDC counties is step 5.
    "County/Parish"                                                  as county_name,
    "Hospital Type"                                                  as hospital_type,
    "Hospital Ownership"                                             as ownership,
    case "Emergency Services" when 'Yes' then true when 'No' then false end
                                                                     as has_emergency_services,
    "Meets criteria for birthing friendly designation" = 'Y'         as is_birthing_friendly,

    -- CMS overall star rating (1-5). It already includes readmission measures, so it must not be
    -- used as a model input for readmissions (it would leak the answer).
    {{ to_number('"Hospital overall rating"', 'integer') }}          as overall_star_rating,
    nullif("Hospital overall rating footnote", '')                   as overall_star_rating_footnote,

    -- How many measures in each group the hospital reports, and how many are better / no
    -- different / worse than the national rate.
    {%- for prefix, label in measure_groups.items() %}
    {{ to_number('"Count of Facility ' ~ label ~ ' Measures"', 'integer') }}      as {{ prefix }}_measures_reported,
    {{ to_number('"Count of ' ~ label ~ ' Measures Better"', 'integer') }}        as {{ prefix }}_measures_better,
    {{ to_number('"Count of ' ~ label ~ ' Measures No Different"', 'integer') }}  as {{ prefix }}_measures_no_different,
    {{ to_number('"Count of ' ~ label ~ ' Measures Worse"', 'integer') }}         as {{ prefix }}_measures_worse,
    {%- endfor %}

    _release                                                         as source_release,
    _ingested_at::timestamptz                                        as ingested_at
from source
