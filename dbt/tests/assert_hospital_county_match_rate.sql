-- At least 99.5% of HRRP hospitals in places with PLACES data must be linked to a county.
-- Returns one row (the failure) when the share drops below that.
--
-- Today it is 100% (3,035 of 3,035). The threshold leaves room for a few hospitals with a new
-- or unusual ZIP in a future release, without letting a broken join (which would drop many
-- at once) pass. Step 2's name matching reached 95.9%.

with hrrp_hospitals as (
    select h.*
    from {{ ref('int_hospitals__county') }} as h
    where h.link_method <> 'no_places_data'
      and h.facility_id in (select facility_id from {{ ref('stg_cms__hrrp') }})
)

select
    count(*)                                      as hospitals,
    count(county_fips)                            as linked,
    round(100.0 * count(county_fips) / count(*), 2) as linked_pct
from hrrp_hospitals
having count(county_fips) < 0.995 * count(*)
