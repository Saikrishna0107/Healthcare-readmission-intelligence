{#
    The pivot from long HCAHPS rows to one column per survey topic: the 0-100 linear score
    (<topic>_score) and the 1-5 star rating (<topic>_stars). Used with GROUP BY a hospital
    (and, for history, a survey window).

    with_retired_topics adds two topics that CMS no longer publishes (responsiveness of staff,
    care transition): they are missing from every archive snapshot from 2026-02-25 on, but exist
    in every survey window used for FY 2020 - FY 2026, so the history keeps them.
    Care transition ("did staff consider my needs and preferences when planning discharge")
    is the topic most directly about leaving the hospital.
#}
{% macro hcahps_score_columns(with_retired_topics=false) %}
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
    {%- if with_retired_topics %}
        {%- do topics.update({'COMP_3': 'staff_responsiveness', 'COMP_7': 'care_transition'}) %}
    {%- endif %}
    {%- for measure, name in topics.items() %}
    max(linear_mean_score) filter (where measure_id = 'H_{{ measure }}_LINEAR_SCORE') as {{ name }}_score,
    max(star_rating)       filter (where measure_id = 'H_{{ measure }}_STAR_RATING')  as {{ name }}_stars,
    {%- endfor %}
    max(star_rating) filter (where measure_id = 'H_STAR_RATING')                      as summary_stars,
    -- The same value is repeated on every row of a hospital, so max() just picks it.
    max(completed_surveys)                                                            as completed_surveys,
    max(response_rate_pct)                                                            as response_rate_pct
{% endmacro %}
