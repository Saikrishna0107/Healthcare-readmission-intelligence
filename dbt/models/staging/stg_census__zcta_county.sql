-- Census 2020 ZCTA-to-county relationship file.
-- Grain: one row per ZIP Code Tabulation Area x county overlap (as published).
-- Rows without a ZCTA are parts of a county outside every ZCTA (often water); zcta is NULL there.

select
    nullif("GEOID_ZCTA5_20", '')                     as zcta,
    "GEOID_COUNTY_20"                                as county_fips,
    left("GEOID_COUNTY_20", 2)                       as state_fips,
    -- Full legal name with its type: 'Baltimore County' vs 'Baltimore city'. CDC PLACES drops
    -- the type ('Baltimore' for both), so this is the name to compare against.
    "NAMELSAD_COUNTY_20"                             as county_name,
    {{ to_number('"AREALAND_PART"', 'bigint') }}     as land_area_part,
    {{ to_number('"AREAWATER_PART"', 'bigint') }}    as water_area_part,
    _release                                         as source_release
from {{ latest_release('census_zcta_county') }}
