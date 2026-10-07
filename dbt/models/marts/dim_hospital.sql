-- Hospital dimension: every hospital any CMS source mentions, with its profile, its county
-- (D-022) and which programs it appears in (D-007).
-- Grain: one row per hospital (facility_id = CMS Certification Number).
--
-- The key set is the union of all CMS sources, not just the hospital profile file: 20 HRRP
-- hospitals have no row in the current profile file. Leaving them out would silently drop
-- their readmission rows from every join to this table.

with profiles as (
    select * from {{ ref('stg_cms__hospitals') }}
),

hrrp as (
    select facility_id, any_value(facility_name) as facility_name, any_value(state) as state
    from {{ ref('stg_cms__hrrp') }}
    group by facility_id
),

penalty_calc as (
    -- The supplemental files hold every fiscal year since FY 2020; this flag is about the latest.
    select facility_id
    from {{ ref('stg_cms__hrrp_payment_adjustments') }}
    where is_latest_fiscal_year
),

all_hospitals as (
    select facility_id from profiles
    union
    select facility_id from hrrp
    union
    select facility_id from penalty_calc
)

select
    a.facility_id,
    coalesce(p.facility_name, h.facility_name)                 as facility_name,
    p.address,
    p.city,
    coalesce(p.state, h.state)                                 as state,
    p.zip_code,
    p.county_name                                              as cms_county_name,

    -- Location on the PLACES county map (int_hospitals__county, D-022)
    l.county_fips,
    coalesce(l.link_method, 'no_hospital_profile')             as county_link_method,
    coalesce(l.is_high_confidence, false)                      as is_county_link_high_confidence,
    l.name_disagrees                                           as county_name_disagrees,

    -- Profile
    p.hospital_type,
    p.ownership,
    p.has_emergency_services,
    p.is_birthing_friendly,
    -- Leakage warning: the star rating already includes readmission measures. Use it to
    -- describe hospitals, never as a model input for predicting readmissions.
    p.overall_star_rating,

    -- Program membership
    p.facility_id is not null                                  as has_hospital_profile,
    h.facility_id is not null                                  as is_hrrp_hospital,
    c.facility_id is not null                                  as is_in_penalty_calculation,

    p.source_release                                           as profile_release
from all_hospitals as a
left join profiles as p on p.facility_id = a.facility_id
left join hrrp as h on h.facility_id = a.facility_id
left join penalty_calc as c on c.facility_id = a.facility_id
left join {{ ref('int_hospitals__county') }} as l on l.facility_id = a.facility_id
