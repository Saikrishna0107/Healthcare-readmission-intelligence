-- Each hospital's latest known profile: the current Hospital General Information file, or,
-- for hospitals no longer in it, their last CMS archive snapshot (D-023).
-- Grain: one row per hospital that appears in any profile, current or archived.
--
-- History reaches back to FY 2019, and hundreds of hospitals in those years have since closed,
-- merged or changed their CCN. Without their old profile they would have no name, type or
-- county, and every county-level analysis of past years would quietly drop them.

with current_profiles as (
    select
        facility_id, facility_name, address, city, state, zip_code, county_name,
        hospital_type, ownership, has_emergency_services, is_birthing_friendly,
        overall_star_rating,
        'current'                       as profile_source,
        source_release::date            as profile_date
    from {{ ref('stg_cms__hospitals') }}
),

archived_profiles as (
    select
        facility_id, facility_name, address, city, state, zip_code, county_name,
        hospital_type, ownership, has_emergency_services,
        null::boolean                   as is_birthing_friendly,    -- not in older snapshots
        overall_star_rating,
        'archive'                       as profile_source,
        snapshot_date                   as profile_date
    from {{ ref('stg_cms__hospitals_history') }}
    where facility_id not in (select facility_id from current_profiles)
    qualify snapshot_date = max(snapshot_date) over (partition by facility_id)
)

select * from current_profiles
union all
select * from archived_profiles
