-- Leakage guard (D-024): no training year's readmission period may overlap the test period.
-- Consecutive HRRP periods share two of their three years of patients, so an overlapping
-- training year would show the model part of the test answer. Returns the offending years.
--
-- Also fails if the split does not have exactly one test year.

with periods as (
    select distinct m.fiscal_year, m.split, f.readmission_period_start, f.readmission_period_end
    from {{ ref('ml_penalty_features') }} as m
    join {{ ref('dim_fiscal_year') }} as f using (fiscal_year)
),

test as (
    select * from periods where split = 'test'
)

select p.fiscal_year, p.readmission_period_end, t.readmission_period_start as test_period_start
from periods as p
cross join test as t
where p.split = 'train' and p.readmission_period_end >= t.readmission_period_start

union all

select 'test years: ' || count(*), null, null
from test
having count(*) <> 1
