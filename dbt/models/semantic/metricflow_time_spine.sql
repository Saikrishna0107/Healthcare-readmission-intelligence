-- Calendar of days that MetricFlow (the dbt Semantic Layer engine) requires to resolve time
-- (D-025). Every measure is tied to a fiscal year's start date; the spine covers all of them.
-- Grain: one row per day, FY 2019 (starts 2018-10-01) to beyond FY 2026.

select cast(range as date) as date_day
from range(date '2018-01-01', date '2031-01-01', interval 1 day)
