-- The pivot in dim_county must neither lose nor invent values.
-- For each chosen measure, the number of counties with a value in dim_county must equal the
-- number of non-suppressed age-adjusted rows in staging. Returns the measures that differ.

{%- set measures = {
    'DIABETES': 'diabetes_pct', 'OBESITY': 'obesity_pct', 'COPD': 'copd_pct',
    'CHD': 'heart_disease_pct', 'BPHIGH': 'high_blood_pressure_pct', 'STROKE': 'stroke_pct',
    'DEPRESSION': 'depression_pct', 'CSMOKING': 'smoking_pct', 'LPA': 'physical_inactivity_pct',
    'GHLTH': 'fair_poor_health_pct', 'DISABILITY': 'disability_pct',
    'ACCESS2': 'uninsured_18_64_pct', 'CHECKUP': 'routine_checkup_pct',
    'LACKTRPT': 'lack_transportation_pct', 'FOODINSECU': 'food_insecurity_pct',
    'HOUSINSECU': 'housing_insecurity_pct', 'LONELINESS': 'loneliness_pct',
} %}

with expected as (
    select measure_id, count(value_pct) as n
    from {{ ref('stg_cdc__places_county') }}
    where value_type = 'AgeAdjPrv'
    group by measure_id
),

actual as (
    {%- for measure_id, column in measures.items() %}
    select '{{ measure_id }}' as measure_id, count({{ column }}) as n from {{ ref('dim_county') }}
    {%- if not loop.last %} union all{% endif %}
    {%- endfor %}
)

select a.measure_id, e.n as expected, a.n as actual
from actual as a
left join expected as e on e.measure_id = a.measure_id
where e.n is distinct from a.n
