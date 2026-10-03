-- ZIP area (ZCTA) to county crosswalk on the county map CDC PLACES uses.
-- Grain: one row per ZCTA x county, with the county's share of the ZCTA's land area.
--
-- The national 2020 file has Connecticut's old counties; PLACES has the 2022 planning regions.
-- So Connecticut rows are replaced: ZCTA-to-town overlaps summed per planning region.

with national as (
    select zcta, county_fips, county_name, land_area_part
    from {{ ref('stg_census__zcta_county') }}
    where zcta is not null
      and county_fips not like '09%'      -- Connecticut comes from the 2022 file below
),

-- Census towns carry no region name; take it from PLACES ('Capitol', ...). PLACES has one row
-- per county x measure, so reduce it to one row per county first, or the join below would
-- multiply every land area by the number of measures.
region_names as (
    select distinct county_fips, county_name
    from {{ ref('stg_cdc__places_county') }}
    where state = 'CT'
),

connecticut as (
    select
        t.zcta,
        t.planning_region_fips                    as county_fips,
        any_value(r.county_name) || ' Planning Region'
                                                  as county_name,
        sum(t.land_area_part)                     as land_area_part
    from {{ ref('stg_census__ct_zcta_town') }} as t
    left join region_names as r on r.county_fips = t.planning_region_fips
    where t.zcta is not null and t.is_town
    group by t.zcta, t.planning_region_fips
),

combined as (
    select * from national
    union all
    select * from connecticut
)

select
    zcta,
    county_fips,
    left(county_fips, 2)                                                    as state_fips,
    county_name,
    land_area_part,
    land_area_part / sum(land_area_part) over (partition by zcta)          as land_share,
    count(*) over (partition by zcta)                                       as zcta_county_count
from combined
-- An overlap with no land (a shared lake or river) would make a ZCTA look like it spans a
-- county it does not reach. 7 such rows nationally.
where land_area_part > 0
