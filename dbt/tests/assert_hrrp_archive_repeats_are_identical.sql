-- When CMS shows the same HRRP performance period in several archive snapshots, every copy
-- must carry the same values. Returns the hospital-condition-periods whose copies differ.
--
-- stg_cms__hrrp_history keeps only the latest copy of each period. This test is what makes
-- that choice lossless. (Survey copies do differ slightly, so stg_cms__hcahps_history keeps
-- the latest, corrected copy on purpose; see D-023.) Footnotes are compared by code, because
-- early 2019 snapshots spell them out ('1 - The number of cases ...').

with copies as (
    select
        coalesce("Facility ID", "Provider ID")                as facility_id,
        replace("Measure Name", '_', '-')                     as measure_id,
        "Start Date"                                          as period_start,
        "End Date"                                            as period_end,
        "Number of Discharges"                                as discharges,
        "Number of Readmissions"                               as readmissions,
        "Excess Readmission Ratio"                            as err,
        "Predicted Readmission Rate"                          as predicted,
        "Expected Readmission Rate"                           as expected,
        regexp_extract("Footnote", '^\s*(\d*)', 1)            as footnote_code
    from {{ source('raw', 'hrrp_archive') }}
)

select facility_id, measure_id, period_start, period_end, count(*) as distinct_versions
from (select distinct * from copies)
group by facility_id, measure_id, period_start, period_end
having count(*) > 1
