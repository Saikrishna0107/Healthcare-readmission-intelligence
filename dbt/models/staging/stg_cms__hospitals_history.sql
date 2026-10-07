-- Hospital General Information as it was in every CMS archive snapshot since March 2019.
-- Grain: one row per hospital x snapshot (32 snapshots).
--
-- Unlike readmissions and surveys, a hospital profile has no performance period: each snapshot
-- is the profile on that date. Keeping every snapshot lets later models ask "what was this
-- hospital's type, ownership or star rating at the time?", instead of using today's values for
-- 2018 results.
--
-- Only the columns present in every snapshot are kept. Name changes handled here:
-- "Provider ID"/"Hospital Name" (early 2019), "City"/"County Name"/"Phone Number" became
-- "City/Town"/"County/Parish"/"Telephone Number" (July 2023).

with source as (
    select * from {{ source('raw', 'hospital_info_archive') }}
)

select
    coalesce("Facility ID", "Provider ID")                           as facility_id,
    _release::date                                                   as snapshot_date,
    coalesce("Facility Name", "Hospital Name")                       as facility_name,
    "Address"                                                        as address,
    coalesce("City/Town", "City")                                    as city,
    "State"                                                          as state,
    "ZIP Code"                                                       as zip_code,
    coalesce("County/Parish", "County Name")                         as county_name,
    "Hospital Type"                                                  as hospital_type,
    "Hospital Ownership"                                             as ownership,
    case "Emergency Services" when 'Yes' then true when 'No' then false end
                                                                     as has_emergency_services,
    -- Includes readmission measures: describes the hospital, never a model input (leakage).
    {{ to_number('"Hospital overall rating"', 'integer') }}          as overall_star_rating,
    _ingested_at::timestamptz                                        as ingested_at
from source
