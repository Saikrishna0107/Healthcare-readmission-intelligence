-- Census 2022 Connecticut ZCTA-to-town (county subdivision) relationship file.
-- Grain: one row per ZCTA x town overlap (as published).
-- Since 2022 Connecticut's county-level units are 9 planning regions; a town code's first five
-- digits are its region, the code CDC PLACES uses ('0911001080' -> '09110', Capitol).

select
    nullif("GEOID_ZCTA5_20", '')                     as zcta,
    "GEOID_COUSUB_22"                                as town_fips,
    "NAMELSAD_COUSUB_22"                             as town_name,
    left("GEOID_COUSUB_22", 5)                       as planning_region_fips,
    -- Water areas without towns are listed as 'County subdivisions not defined'.
    "NAMELSAD_COUSUB_22" <> 'County subdivisions not defined'
                                                     as is_town,
    {{ to_number('"AREALAND_PART"', 'bigint') }}     as land_area_part,
    _release                                         as source_release
from {{ latest_release('census_ct_zcta_cousub') }}
