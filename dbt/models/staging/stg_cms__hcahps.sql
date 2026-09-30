-- Patient survey (HCAHPS), latest release.
-- Grain: one row per hospital x survey measure (long format, as published).
-- Hospital name and address are dropped: they belong to stg_cms__hospitals.

with source as (
    select * from {{ latest_release('hcahps') }}
)

select
    "Facility ID"                                                        as facility_id,
    "HCAHPS Measure ID"                                                  as measure_id,
    "HCAHPS Question"                                                    as question,
    "HCAHPS Answer Description"                                          as answer_description,

    {{ to_number('"Patient Survey Star Rating"', 'integer') }}           as star_rating,
    nullif("Patient Survey Star Rating Footnote", '')                    as star_rating_footnote,
    {{ to_number('"HCAHPS Answer Percent"', 'integer') }}                as answer_pct,
    nullif("HCAHPS Answer Percent Footnote", '')                         as answer_pct_footnote,
    -- 0-100 score that summarizes all answers to a question; comparable across hospitals.
    {{ to_number('"HCAHPS Linear Mean Value"', 'integer') }}             as linear_mean_score,

    {{ to_number('"Number of Completed Surveys"', 'integer') }}          as completed_surveys,
    nullif("Number of Completed Surveys Footnote", '')                   as completed_surveys_footnote,
    {{ to_number('"Survey Response Rate Percent"', 'integer') }}         as response_rate_pct,
    nullif("Survey Response Rate Percent Footnote", '')                  as response_rate_footnote,

    strptime("Start Date", '%m/%d/%Y')::date                             as period_start,
    strptime("End Date", '%m/%d/%Y')::date                               as period_end,
    _release                                                             as source_release,
    _ingested_at::timestamptz                                            as ingested_at
from source
