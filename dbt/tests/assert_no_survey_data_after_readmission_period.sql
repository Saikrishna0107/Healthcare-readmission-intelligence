-- Leakage guard (D-008): no hospital-year may carry survey scores from a window that ends after
-- its readmission period. Returns the offending hospital-years.
--
-- dim_fiscal_year applies the rule and has its own test; this one checks the fact table, so a
-- change to how fct_hospital_year joins the survey (say, to "the latest scores") is caught too.

select
    y.facility_id,
    y.fiscal_year,
    y.survey_period_end,
    f.readmission_period_end
from {{ ref('fct_hospital_year') }} as y
join {{ ref('dim_fiscal_year') }} as f using (fiscal_year)
where y.has_survey_scores
  and (y.survey_period_end is null or y.survey_period_end > f.readmission_period_end)
