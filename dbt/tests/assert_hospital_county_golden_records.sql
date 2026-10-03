-- Golden records: hospitals whose correct county was checked by hand, chosen because they are
-- the cases name matching gets wrong. Returns every hospital whose linked county differs.
--
--   210009  Johns Hopkins Hospital          Baltimore city (24510), not Baltimore County (24005)
--   260032  Barnes-Jewish Hospital          St. Louis city (29510), not St. Louis County (29189)
--   490007  Sentara Norfolk General         Norfolk city, Virginia (51710), an independent city
--   490009  University of Virginia Med Ctr  Charlottesville city (51540), not Albemarle County
--   070022  Yale-New Haven Hospital         South Central Connecticut planning region (09170);
--                                           its ZIP (06504) is not a ZIP area, so this checks
--                                           the Connecticut town fallback

with expected (facility_id, expected_county_fips) as (
    values
        ('210009', '24510'),
        ('260032', '29510'),
        ('490007', '51710'),
        ('490009', '51540'),
        ('070022', '09170')
)

select
    e.facility_id,
    e.expected_county_fips,
    h.county_fips  as actual_county_fips,
    h.link_method
from expected as e
left join {{ ref('int_hospitals__county') }} as h using (facility_id)
where h.county_fips is distinct from e.expected_county_fips
