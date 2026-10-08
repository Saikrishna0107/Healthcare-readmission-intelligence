-- Leakage guard (D-024): the prior_* features must come from a readmission period that ends
-- before the target period starts. Recomputes the FY-3 mapping independently of the model and
-- returns every fiscal year with prior features whose source period overlaps its own.

with years as (
    select
        fiscal_year,
        cast(substr(fiscal_year, 3) as integer) as year_number,
        readmission_period_start,
        readmission_period_end
    from {{ ref('dim_fiscal_year') }}
)

select distinct
    m.fiscal_year,
    prior.fiscal_year             as prior_fiscal_year,
    prior.readmission_period_end  as prior_period_end,
    target.readmission_period_start
from {{ ref('ml_penalty_features') }} as m
join years as target using (fiscal_year)
left join years as prior on prior.year_number = target.year_number - 3
where (m.prior_weighted_err is not null or m.prior_payment_reduction_pct is not null)
  and (prior.fiscal_year is null or prior.readmission_period_end >= target.readmission_period_start)
