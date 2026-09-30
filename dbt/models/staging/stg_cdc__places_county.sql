-- CDC PLACES county estimates, latest release.
-- Grain: one row per county x health measure x value type (crude or age-adjusted prevalence).
-- Measures come from different survey years (most 2023, some 2022); `data_year` says which.

with source as (
    select * from {{ latest_release('places_county') }}
    -- The file includes a national "US" row that is not a county.
    where "StateAbbr" <> 'US'
)

select
    "LocationID"                                                     as county_fips,
    "LocationName"                                                   as county_name,
    "StateAbbr"                                                      as state,
    "StateDesc"                                                      as state_name,
    {{ to_number('"Year"', 'integer') }}                             as data_year,

    "CategoryID"                                                     as category_id,
    "Category"                                                       as category,
    "MeasureId"                                                      as measure_id,
    "Measure"                                                        as measure_name,
    "Short_Question_Text"                                            as measure_short_name,
    "DataValueTypeID"                                                as value_type,

    -- Percent of adults, e.g. 12.3 means 12.3%. NULL when CDC suppresses tiny populations.
    {{ to_number('"Data_Value"') }}                                  as value_pct,
    {{ to_number('"Low_Confidence_Limit"') }}                        as value_pct_low,
    {{ to_number('"High_Confidence_Limit"') }}                       as value_pct_high,
    "Data_Value_Footnote_Symbol" = '*'                               as is_suppressed,

    {{ to_number('"TotalPopulation"', 'integer') }}                  as total_population,
    {{ to_number('"TotalPop18plus"', 'integer') }}                   as adult_population,
    -- 'POINT (-91.71 33.58)' -> longitude, latitude of the county centre (for maps)
    regexp_extract("Geolocation", 'POINT \(([-0-9.]+) ', 1)::double  as longitude,
    regexp_extract("Geolocation", ' ([-0-9.]+)\)$', 1)::double       as latitude,

    _release                                                         as source_release,
    _ingested_at::timestamptz                                        as ingested_at
from source
