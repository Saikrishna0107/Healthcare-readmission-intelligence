-- Each staged CMS measure table must cover exactly one performance period.
-- Returns the tables that mix periods.
--
-- Live staging reads only the latest release, so this holds today. It guards the time alignment in
-- step 6 (D-008): comparing readmissions from one period with survey scores from another is
-- how data leakage creeps in, and a table silently mixing periods would hide it.

select 'stg_cms__hrrp' as model, count(distinct (period_start, period_end)) as periods
from {{ ref('stg_cms__hrrp') }}
having count(distinct (period_start, period_end)) <> 1

union all

select 'stg_cms__hcahps', count(distinct (period_start, period_end))
from {{ ref('stg_cms__hcahps') }}
having count(distinct (period_start, period_end)) <> 1

-- History models hold many periods, but each archive snapshot they read must hold exactly one:
-- that is what lets a snapshot stand for a period (latest_snapshot_per_period, D-023).
union all

select 'stg_cms__hrrp_history ' || source_release, count(distinct (period_start, period_end))
from {{ ref('stg_cms__hrrp_history') }}
group by source_release
having count(distinct (period_start, period_end)) <> 1

union all

select 'stg_cms__hcahps_history ' || source_release, count(distinct (period_start, period_end))
from {{ ref('stg_cms__hcahps_history') }}
group by source_release
having count(distinct (period_start, period_end)) <> 1
