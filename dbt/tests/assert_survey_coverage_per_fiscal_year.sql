-- At least 99% of the hospitals in each year's penalty file must have survey scores from the
-- aligned window. Returns the fiscal years below that.
--
-- Today it is 99.8% - 100% (FY 2020 - FY 2026). A wrong window (one that does not exist in the
-- archive, or a join on mismatched dates) leaves a whole year without scores, which this catches;
-- the 1% margin allows for hospitals that do not run the survey.

select
    y.fiscal_year,
    count(*)                                                as hospitals,
    count(*) filter (where y.has_survey_scores)             as with_scores
from {{ ref('fct_hospital_year') }} as y
join {{ ref('dim_fiscal_year') }} as f using (fiscal_year)
where y.in_payment_file and f.survey_period_end is not null
group by y.fiscal_year
having count(*) filter (where y.has_survey_scores) < 0.99 * count(*)
