-- Hospital Readmissions Reduction Program, latest release.
-- Grain: one row per hospital x condition (the target variable lives here).

with source as (
    select * from {{ latest_release('hrrp') }}
),

cleaned as (
    select
        "Facility ID"                                            as facility_id,
        "Facility Name"                                          as facility_name,
        "State"                                                  as state,
        "Measure Name"                                           as measure_id,
        -- 'READM-30-HIP-KNEE-HRRP' -> 'HIP_KNEE'; the same codes are used for every source
        replace(regexp_extract("Measure Name", '^READM-30-(.+)-HRRP$', 1), '-', '_')
                                                                 as condition,

        {{ to_number('"Number of Discharges"', 'integer') }}     as discharges,
        {{ to_number('"Number of Readmissions"', 'integer') }}   as readmissions,
        -- CMS hides readmission counts between 1 and 10 for privacy. The ratio is still published.
        "Number of Readmissions" = 'Too Few to Report'           as readmissions_suppressed,

        {{ to_number('"Excess Readmission Ratio"') }}            as excess_readmission_ratio,
        {{ to_number('"Predicted Readmission Rate"') }}          as predicted_readmission_rate,
        {{ to_number('"Expected Readmission Rate"') }}           as expected_readmission_rate,

        nullif("Footnote", '')                                   as footnote_code,
        strptime("Start Date", '%m/%d/%Y')::date                 as period_start,
        strptime("End Date", '%m/%d/%Y')::date                   as period_end,

        _release                                                 as source_release,
        _ingested_at::timestamptz                                as ingested_at
    from source
)

select
    *,
    {{ hrrp_score_status('excess_readmission_ratio', 'footnote_code') }} as score_status
from cleaned
