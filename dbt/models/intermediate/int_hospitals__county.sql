-- Each hospital's county, as the 5-digit FIPS code CDC PLACES uses (D-022).
-- Grain: one row per hospital (all hospital types).
--
-- Two independent signals: the ZIP code (where the hospital is) and the county name CMS writes.
-- The ladder below takes the best available answer, records which rung gave it (link_method),
-- and flags hospitals where the name points to a different county (name_disagrees).
--
--   1. zip_single_county    the ZIP area lies in one county
--   2. zip_name_agrees      the ZIP area spans several counties; one has the CMS county name
--   3. zip_largest_area     ... none has the name; take the largest share of the ZIP's land
--   4. ct_town              Connecticut, ZIP not a ZIP area: the hospital's city is a town,
--                           and towns lie inside exactly one planning region
--   5. name_only            ZIP not a ZIP area: the CMS county name (state + name)
--   6. single_county_state  the state has one county-level unit (Washington DC)
--   -  no_places_data       territories (PR, GU, ...): PLACES has no data there
--   -  unmatched            none of the above

with hospitals as (
    select
        facility_id,
        state,
        city,
        zip_code,
        county_name                                    as cms_county_name,
        {{ clean_county_name('county_name') }}         as name_key
    from {{ ref('stg_cms__hospitals') }}
),

-- State abbreviation <-> state FIPS code, and which states PLACES covers.
places_states as (
    select distinct state, left(county_fips, 2) as state_fips
    from {{ ref('stg_cdc__places_county') }}
),

places_counties as (
    select distinct county_fips, county_name
    from {{ ref('stg_cdc__places_county') }}
),

-- Every county with its full Census name, for matching by name. Only counties on the PLACES
-- map: Connecticut's old counties are in the 2020 Census file but no longer exist there.
census_counties as (
    select distinct county_fips, state_fips, {{ clean_county_name('county_name') }} as name_key
    from {{ ref('stg_census__zcta_county') }}
    where county_fips in (select county_fips from places_counties)
),

-- Rungs 1-3: every county the hospital's ZIP area touches, best candidate first.
zip_candidates as (
    select
        h.facility_id,
        z.county_fips,
        z.land_share,
        z.zcta_county_count,
        {{ clean_county_name('z.county_name') }} = h.name_key          as name_matches,
        row_number() over (
            partition by h.facility_id
            order by
                {{ clean_county_name('z.county_name') }} = h.name_key desc,
                z.state_fips = s.state_fips desc,                       -- ZIPs can cross state lines
                z.land_share desc
        )                                                               as preference
    from hospitals as h
    join {{ ref('int_census__zcta_county') }} as z on z.zcta = h.zip_code
    left join places_states as s on s.state = h.state
),

best_zip as (
    select * from zip_candidates where preference = 1
),

-- Rung 4: Connecticut town -> planning region.
ct_towns as (
    select distinct
        {{ clean_county_name("regexp_replace(town_name, ' town$', '')") }}  as town_key,
        planning_region_fips
    from {{ ref('stg_census__ct_zcta_town') }}
    where is_town
),

-- Rung 5 and the cross-check: the county the CMS name points to, if exactly one does.
by_name as (
    select h.facility_id, any_value(c.county_fips) as county_fips
    from hospitals as h
    join places_states as s on s.state = h.state
    join census_counties as c on c.state_fips = s.state_fips and c.name_key = h.name_key
    group by h.facility_id
    having count(*) = 1
),

-- Rung 6: states with a single county-level unit.
single_county_states as (
    select state_fips, any_value(county_fips) as county_fips
    from census_counties
    group by state_fips
    having count(*) = 1
),

linked as (
    select
        h.*,
        s.state is not null                                    as has_places_data,
        z.county_fips                                          as zip_county_fips,
        z.zcta_county_count,
        z.land_share                                           as zip_land_share,
        z.name_matches                                         as zip_name_matches,
        ct.planning_region_fips                                as ct_town_region_fips,
        n.county_fips                                          as name_county_fips,
        sc.county_fips                                         as single_county_fips
    from hospitals as h
    left join places_states as s on s.state = h.state
    left join best_zip as z on z.facility_id = h.facility_id
    left join ct_towns as ct
        on h.state = 'CT' and ct.town_key = {{ clean_county_name('h.city') }}
    left join by_name as n on n.facility_id = h.facility_id
    left join single_county_states as sc on sc.state_fips = s.state_fips
),

decided as (
    select
        *,
        case
            when not has_places_data              then 'no_places_data'
            when zcta_county_count = 1            then 'zip_single_county'
            when zip_name_matches                 then 'zip_name_agrees'
            when zip_county_fips is not null      then 'zip_largest_area'
            when ct_town_region_fips is not null  then 'ct_town'
            when name_county_fips is not null     then 'name_only'
            when single_county_fips is not null   then 'single_county_state'
            else 'unmatched'
        end as link_method
    from linked
)

select
    d.facility_id,
    d.state,
    d.zip_code,
    d.cms_county_name,
    case d.link_method
        when 'no_places_data'      then null
        when 'ct_town'             then d.ct_town_region_fips
        when 'name_only'           then d.name_county_fips
        when 'single_county_state' then d.single_county_fips
        when 'unmatched'           then null
        else d.zip_county_fips
    end                                                     as county_fips,
    d.link_method,
    d.link_method in ('zip_single_county', 'zip_name_agrees')
                                                            as is_high_confidence,
    d.zcta_county_count,
    d.zip_land_share,
    -- The county the CMS name alone points to (NULL when the name matches no single county,
    -- e.g. Connecticut's old county names).
    d.name_county_fips,
    -- TRUE: the name points to a different county than the one chosen. Worth a look.
    -- NULL: there is nothing to compare (name not resolvable, or no county chosen).
    case
        when d.name_county_fips is null or county_fips is null then null
        else d.name_county_fips <> county_fips
    end                                                     as name_disagrees
from decided as d
