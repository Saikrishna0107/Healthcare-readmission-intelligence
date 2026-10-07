-- HRRP readmission results for every performance period since 2014-2017, from the CMS archive.
-- Grain: one row per hospital x condition x performance period (8 periods, FY 2019 - FY 2026).
--
-- Same columns as stg_cms__hrrp. Each period comes from the latest archive snapshot that showed
-- it (latest_snapshot_per_period); the copies of a period are identical, which a test checks.
-- Name changes handled here: "Provider ID"/"Hospital Name" (early 2019) became
-- "Facility ID"/"Facility Name"; measure codes used '_' instead of '-' in the 2014-2017 period;
-- footnotes were full sentences ("1 - The number of cases ...") before October 2019.

with source as (
    select * from {{ latest_snapshot_per_period('hrrp_archive', '"Start Date"', '"End Date"') }}
),

cleaned as (
    select
        coalesce("Facility ID", "Provider ID")                   as facility_id,
        coalesce("Facility Name", "Hospital Name")               as facility_name,
        "State"                                                  as state,
        replace("Measure Name", '_', '-')                        as measure_id,
        replace(regexp_extract(replace("Measure Name", '_', '-'), '^READM-30-(.+)-HRRP$', 1), '-', '_')
                                                                 as condition,

        {{ to_number('"Number of Discharges"', 'integer') }}     as discharges,
        {{ to_number('"Number of Readmissions"', 'integer') }}   as readmissions,
        "Number of Readmissions" = 'Too Few to Report'           as readmissions_suppressed,

        {{ to_number('"Excess Readmission Ratio"') }}            as excess_readmission_ratio,
        {{ to_number('"Predicted Readmission Rate"') }}          as predicted_readmission_rate,
        {{ to_number('"Expected Readmission Rate"') }}           as expected_readmission_rate,

        -- '1 - The number of cases ...' and '1' are the same footnote: keep the code.
        nullif(regexp_extract("Footnote", '^\s*(\d+)', 1), '')   as footnote_code,
        strptime("Start Date", '%m/%d/%Y')::date                 as period_start,
        -- Published as 12/01/2019 for the FY 2022 period; kept as published (see D-023).
        strptime("End Date", '%m/%d/%Y')::date                   as period_end,

        _release                                                 as source_release,
        _period_first_release                                    as period_first_release,
        _period_snapshots                                        as period_snapshots,
        _ingested_at::timestamptz                                as ingested_at
    from source
)

select
    *,
    {{ hrrp_score_status('excess_readmission_ratio', 'footnote_code') }} as score_status
from cleaned
