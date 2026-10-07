-- Patient survey scores pivoted from long to wide, latest release.
-- Grain: one row per hospital (from 68 rows per hospital in stg_cms__hcahps).
--
-- Keeps the linear mean score (0-100) and star rating (1-5) of each survey topic. The other 50
-- rows per hospital are the answer-level percentages ("always", "usually", ...) that these two
-- numbers already summarize. Topics: hcahps_score_columns macro.

select
    facility_id,
    {{ hcahps_score_columns() }},
    max(period_start)                                                                 as period_start,
    max(period_end)                                                                   as period_end,
    max(source_release)                                                               as source_release
from {{ ref('stg_cms__hcahps') }}
group by facility_id
