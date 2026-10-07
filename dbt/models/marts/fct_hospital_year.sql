-- One row per hospital and fiscal year: the penalty, the readmission results behind it, and the
-- hospital's survey scores and profile from the matching time (D-008). The table step 7 models.
-- Grain: one row per hospital x fiscal year (FY 2019 - FY 2026).
--
-- Time alignment, so nothing describes a later time than the readmissions it sits next to:
--   survey scores   from the survey window dim_fiscal_year assigns to the year (ends on or
--                   before the readmission period ends).
--   profile         hospital type, ownership and emergency services from the hospital's first
--                   archive snapshot after the readmission period ended (the archive starts in
--                   March 2019, so FY 2019 - FY 2021 use that one). These are structural facts
--                   that rarely change; the star rating is left out on purpose (it contains the
--                   readmission measures themselves).

with hospital_years as (
    select
        fiscal_year,
        facility_id,
        count(excess_readmission_ratio)                         as conditions_with_public_ratio,
        count(*) filter (where counts_toward_penalty)           as conditions_counting_toward_penalty,
        sum(discharges)                                         as public_discharges,
        sum(penalty_contribution)                               as unadjusted_penalty
    from {{ ref('fct_readmissions') }}
    group by fiscal_year, facility_id
),

profiles as (
    select
        y.fiscal_year,
        y.facility_id,
        h.snapshot_date,
        h.hospital_type,
        h.ownership,
        h.has_emergency_services
    from hospital_years as y
    join {{ ref('dim_fiscal_year') }} as f using (fiscal_year)
    join {{ ref('stg_cms__hospitals_history') }} as h using (facility_id)
    -- The first snapshot after the period; failing that (the hospital had left by then),
    -- the last one before it.
    qualify row_number() over (
        partition by y.fiscal_year, y.facility_id
        order by h.snapshot_date >= f.readmission_period_end desc,
                 abs(h.snapshot_date - f.readmission_period_end)
    ) = 1
)

select
    y.fiscal_year,
    y.facility_id,

    -- Readmission results (fct_readmissions)
    y.conditions_with_public_ratio,
    y.conditions_counting_toward_penalty,
    y.public_discharges,

    -- Penalty (Supplemental Data File; NULL for FY 2019 and hospitals not in the file)
    a.facility_id is not null                                   as in_payment_file,
    a.payment_adjustment_factor,
    a.payment_reduction_pct,
    a.payment_reduction_is_derived,
    a.is_penalized,
    a.dual_proportion,
    a.peer_group,
    a.neutrality_modifier,
    y.unadjusted_penalty,

    -- Patient survey, aligned window
    f.survey_period_start,
    f.survey_period_end,
    s.facility_id is not null                                   as has_survey_scores,
    {%- for topic in ['nurse_communication', 'doctor_communication', 'staff_responsiveness',
                      'medicine_communication', 'discharge_information', 'care_transition',
                      'cleanliness', 'quietness', 'overall_rating', 'recommend'] %}
    s.{{ topic }}_score,
    s.{{ topic }}_stars,
    {%- endfor %}
    s.summary_stars,
    s.completed_surveys,
    s.response_rate_pct,

    -- Profile at the time
    p.snapshot_date                                             as profile_snapshot_date,
    p.hospital_type,
    p.ownership,
    p.has_emergency_services
from hospital_years as y
join {{ ref('dim_fiscal_year') }} as f using (fiscal_year)
left join {{ ref('stg_cms__hrrp_payment_adjustments') }} as a
    on a.facility_id = y.facility_id and a.fiscal_year = y.fiscal_year
left join {{ ref('int_hcahps__scores_by_window') }} as s
    on s.facility_id = y.facility_id
   and s.period_start = f.survey_period_start
   and s.period_end = f.survey_period_end
left join profiles as p
    on p.facility_id = y.facility_id and p.fiscal_year = y.fiscal_year
