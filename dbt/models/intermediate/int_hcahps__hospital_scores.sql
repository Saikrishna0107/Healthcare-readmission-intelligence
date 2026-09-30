-- Patient survey scores pivoted from long to wide.
-- Grain: one row per hospital (from 68 rows per hospital in stg_cms__hcahps).
--
-- Keeps the linear mean score (0-100) and star rating (1-5) of each survey topic. The other 50
-- rows per hospital are the answer-level percentages ("always", "usually", ...) that these two
-- numbers already summarize.

{%- set topics = {
    'COMP_1': 'nurse_communication',
    'COMP_2': 'doctor_communication',
    'COMP_5': 'medicine_communication',
    'COMP_6': 'discharge_information',
    'CLEAN': 'cleanliness',
    'QUIET': 'quietness',
    'HSP_RATING': 'overall_rating',
    'RECMND': 'recommend',
} %}

select
    facility_id,
    {%- for measure, name in topics.items() %}
    max(linear_mean_score) filter (where measure_id = 'H_{{ measure }}_LINEAR_SCORE') as {{ name }}_score,
    max(star_rating)       filter (where measure_id = 'H_{{ measure }}_STAR_RATING')  as {{ name }}_stars,
    {%- endfor %}
    max(star_rating) filter (where measure_id = 'H_STAR_RATING')                      as summary_stars,

    -- The same value is repeated on every row of a hospital, so max() just picks it.
    max(completed_surveys)                                                            as completed_surveys,
    max(response_rate_pct)                                                            as response_rate_pct,
    max(period_start)                                                                 as period_start,
    max(period_end)                                                                   as period_end,
    max(source_release)                                                               as source_release
from {{ ref('stg_cms__hcahps') }}
group by facility_id
