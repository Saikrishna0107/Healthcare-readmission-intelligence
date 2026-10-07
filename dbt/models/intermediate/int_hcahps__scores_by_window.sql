-- Patient survey scores pivoted from long to wide, for every survey window in the archive.
-- Grain: one row per hospital x survey window (26 windows since April 2017).
-- Same columns as int_hcahps__hospital_scores, plus the two topics CMS no longer publishes
-- (see hcahps_score_columns).

select
    facility_id,
    period_start,
    period_end,
    {{ hcahps_score_columns(with_retired_topics=true) }},
    max(source_release)                                                               as source_release
from {{ ref('stg_cms__hcahps_history') }}
group by facility_id, period_start, period_end
