-- Model input for the HRRP penalty model (step 7, D-024).
-- Grain: one row per hospital x fiscal year in a penalty file (FY 2020 - FY 2026).
--
-- Roles (also in _ml.yml, which the training code reads):
--   key       facility_id, fiscal_year
--   target    payment_reduction_pct (main); is_penalized and is_top_quarter_penalty are the
--             yes/no views of it used to judge how well the model ranks hospitals
--   split     train / test / overlap_unused, derived from the performance periods below
--   feature   drivers known for the same period: volume, patient mix, survey, hospital
--             profile, county health. Nothing computed from readmission outcomes.
--   variant   the hospital's results from the period three fiscal years earlier, which ends
--             exactly when this one starts: used only by the "with prior results" model.
--
-- The split: the test year is the latest fiscal year; training years are those whose period
-- ends before the test period begins. Consecutive HRRP periods share two of their three years
-- of patients, so a year that overlaps the test period (today FY 2024 and FY 2025) would let
-- the model see part of the answer; those rows are kept but marked overlap_unused.

with years as (
    select
        fiscal_year,
        readmission_period_start,
        readmission_period_end,
        cast(substr(fiscal_year, 3) as integer)                     as fiscal_year_number
    from {{ ref('dim_fiscal_year') }}
),

test_year as (
    select * from years
    where fiscal_year = (select max(fiscal_year) from {{ ref('stg_cms__hrrp_payment_adjustments') }})
),

-- Volume per hospital-year: how many patients, and in how many conditions the hospital can be
-- penalized at all (CMS counts a condition only with 25+ eligible discharges). Counts of
-- patients, not results.
volume as (
    select
        facility_id,
        fiscal_year,
        sum(eligible_discharges)::integer                           as eligible_discharges,
        (count(*) filter (where eligible_discharges >= 25))::integer as conditions_with_25_cases
    from {{ ref('fct_readmissions') }}
    where in_payment_file
    group by facility_id, fiscal_year
),

-- Variant features: results from the period three fiscal years earlier (no shared patients).
prior_results as (
    select
        r.facility_id,
        'FY' || (y.fiscal_year_number + 3)                          as fiscal_year,
        -- Weighted by patients, like the penalty itself: a condition with 600 discharges says
        -- more about the hospital than one with 30.
        sum(r.excess_readmission_ratio * r.discharges) / sum(r.discharges) as prior_weighted_err,
        count(r.excess_readmission_ratio)::integer                  as prior_conditions_scored
    from {{ ref('fct_readmissions') }} as r
    join years as y using (fiscal_year)
    where r.excess_readmission_ratio is not null and r.discharges > 0
    group by r.facility_id, y.fiscal_year_number
),

prior_penalty as (
    select
        a.facility_id,
        'FY' || (y.fiscal_year_number + 3)                          as fiscal_year,
        a.payment_reduction_pct                                     as prior_payment_reduction_pct
    from {{ ref('stg_cms__hrrp_payment_adjustments') }} as a
    join years as y using (fiscal_year)
)

select
    -- Keys
    h.facility_id,
    h.fiscal_year,

    -- Split
    case
        when h.fiscal_year = t.fiscal_year                          then 'test'
        when y.readmission_period_end < t.readmission_period_start  then 'train'
        else 'overlap_unused'
    end                                                             as split,

    -- Targets
    h.payment_reduction_pct,
    h.is_penalized,
    h.payment_reduction_pct >= quantile_cont(h.payment_reduction_pct, 0.75)
        over (partition by h.fiscal_year)                           as is_top_quarter_penalty,

    -- Features: volume and patient mix (same period)
    v.eligible_discharges,
    v.conditions_with_25_cases,
    h.dual_proportion,
    h.peer_group,

    -- Features: patient survey, window aligned in dim_fiscal_year
    h.has_survey_scores,
    h.nurse_communication_score,
    h.doctor_communication_score,
    h.staff_responsiveness_score,
    h.medicine_communication_score,
    h.discharge_information_score,
    h.care_transition_score,
    h.cleanliness_score,
    h.quietness_score,
    h.overall_rating_score,
    h.recommend_score,
    h.completed_surveys,
    h.response_rate_pct,

    -- Features: hospital profile at the time
    h.ownership,
    h.has_emergency_services,

    -- Features: county health (one current CDC release, D-008 known limit)
    c.total_population                                              as county_population,
    {%- for measure in ['diabetes', 'obesity', 'copd', 'heart_disease', 'high_blood_pressure',
                        'stroke', 'depression', 'smoking', 'physical_inactivity', 'fair_poor_health',
                        'disability', 'uninsured_18_64', 'routine_checkup', 'lack_transportation',
                        'food_insecurity', 'housing_insecurity', 'loneliness'] %}
    c.{{ measure }}_pct                                              as county_{{ measure }}_pct,
    {%- endfor %}

    -- Variant features: the period three fiscal years earlier
    pr.prior_weighted_err,
    pr.prior_conditions_scored,
    pp.prior_payment_reduction_pct
from {{ ref('fct_hospital_year') }} as h
join years as y using (fiscal_year)
cross join test_year as t
join volume as v using (facility_id, fiscal_year)
join {{ ref('dim_hospital') }} as d using (facility_id)
left join {{ ref('dim_county') }} as c using (county_fips)
left join prior_results as pr using (facility_id, fiscal_year)
left join prior_penalty as pp using (facility_id, fiscal_year)
where h.in_payment_file
