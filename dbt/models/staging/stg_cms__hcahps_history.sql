-- Patient survey (HCAHPS) summary scores for every survey window since 2017, from the CMS archive.
-- Grain: one row per hospital x summary measure x survey window (26 windows).
--
-- Kept: the 0-100 linear mean scores and the star ratings, about a fifth of the rows (2.6
-- million). The rest are answer percentages ("always", "usually", ...) that the linear scores
-- already summarize; across 26 windows they would add about 9 million rows that no model uses.
-- The live model stg_cms__hcahps keeps every row of the latest release.
--
-- Each window comes from the latest archive snapshot that showed it: copies of a window differ
-- in a few dozen values that CMS corrected. Name changes handled here: "Provider ID" and
-- "Measure Start/End Date" (early 2019).

with source as (
    select *
    from {{ latest_snapshot_per_period(
        'hcahps_archive',
        'coalesce("Start Date", "Measure Start Date")',
        'coalesce("End Date", "Measure End Date")'
    ) }}
    where "HCAHPS Measure ID" like '%\_LINEAR\_SCORE' escape '\'
       or "HCAHPS Measure ID" like '%\_STAR\_RATING' escape '\'
)

select
    coalesce("Facility ID", "Provider ID")                               as facility_id,
    "HCAHPS Measure ID"                                                  as measure_id,
    "HCAHPS Question"                                                    as question,

    {{ to_number('"Patient Survey Star Rating"', 'integer') }}           as star_rating,
    {{ to_number('"HCAHPS Linear Mean Value"', 'integer') }}             as linear_mean_score,
    {{ to_number('"Number of Completed Surveys"', 'integer') }}          as completed_surveys,
    {{ to_number('"Survey Response Rate Percent"', 'integer') }}         as response_rate_pct,

    strptime(coalesce("Start Date", "Measure Start Date"), '%m/%d/%Y')::date  as period_start,
    strptime(coalesce("End Date", "Measure End Date"), '%m/%d/%Y')::date      as period_end,
    _release                                                             as source_release,
    _period_first_release                                                as period_first_release,
    _period_snapshots                                                    as period_snapshots,
    _ingested_at::timestamptz                                            as ingested_at
from source
