-- County dimension: one row per county on the CDC PLACES map, with the community health
-- measures that plausibly drive readmissions as columns (D-007).
-- Grain: one row per county (county_fips).
--
-- Values are age-adjusted percentages of adults, so counties with older populations do not
-- look sicker just because of age. NULL means CDC has no estimate for that county:
--   - Kentucky and Pennsylvania have no 2023 survey data in this release, so their chronic
--     disease and behaviour measures are NULL (has_chronic_measures = false).
--   - The social needs measures (transportation, food, housing, loneliness) come from an
--     optional survey module that not every state ran: 2,299 of 3,144 counties have them.

{%- set measures = [
    ('DIABETES',   'diabetes_pct',                'chronic'),
    ('OBESITY',    'obesity_pct',                 'chronic'),
    ('COPD',       'copd_pct',                    'chronic'),
    ('CHD',        'heart_disease_pct',           'chronic'),
    ('BPHIGH',     'high_blood_pressure_pct',     'chronic'),
    ('STROKE',     'stroke_pct',                  'chronic'),
    ('DEPRESSION', 'depression_pct',              'chronic'),
    ('CSMOKING',   'smoking_pct',                 'chronic'),
    ('LPA',        'physical_inactivity_pct',     'chronic'),
    ('GHLTH',      'fair_poor_health_pct',        'chronic'),
    ('DISABILITY', 'disability_pct',              'chronic'),
    ('ACCESS2',    'uninsured_18_64_pct',         'chronic'),
    ('CHECKUP',    'routine_checkup_pct',         'chronic'),
    ('LACKTRPT',   'lack_transportation_pct',     'social'),
    ('FOODINSECU', 'food_insecurity_pct',         'social'),
    ('HOUSINSECU', 'housing_insecurity_pct',      'social'),
    ('LONELINESS', 'loneliness_pct',              'social'),
] %}

with places as (
    select *
    from {{ ref('stg_cdc__places_county') }}
    where value_type = 'AgeAdjPrv'
),

counties as (
    -- Name, population and location repeat on every measure row with the same value.
    select
        county_fips,
        any_value(county_name)       as county_name,
        any_value(state)             as state,
        any_value(state_name)        as state_name,
        any_value(total_population)  as total_population,
        any_value(adult_population)  as adult_population,
        any_value(latitude)          as latitude,
        any_value(longitude)         as longitude,
        any_value(source_release)    as source_release
    from {{ ref('stg_cdc__places_county') }}
    group by county_fips
),

pivoted as (
    select
        county_fips,
        {%- for measure_id, column, _ in measures %}
        max(value_pct) filter (where measure_id = '{{ measure_id }}')  as {{ column }},
        {%- endfor %}
        max(data_year) filter (where measure_id = 'DIABETES')         as chronic_data_year,
        max(data_year) filter (where measure_id = 'LACKTRPT')         as social_data_year
    from places
    group by county_fips
)

select
    c.county_fips,
    c.county_name,
    c.state,
    c.state_name,
    c.total_population,
    c.adult_population,
    c.latitude,
    c.longitude,
    {%- for _, column, _ in measures %}
    p.{{ column }},
    {%- endfor %}
    p.chronic_data_year,
    p.social_data_year,
    p.chronic_data_year is not null  as has_chronic_measures,
    p.social_data_year is not null   as has_social_measures,
    c.source_release
from counties as c
left join pivoted as p on p.county_fips = c.county_fips
