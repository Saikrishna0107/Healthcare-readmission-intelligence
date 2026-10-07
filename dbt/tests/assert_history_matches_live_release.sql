-- For the period the live datasets show today, the archive history must agree with them row
-- for row. Returns the rows found on one side only.
--
-- Two independent downloads (the live dataset and the archive snapshot) of the same period
-- should be the same data. A difference means one of the two pipelines reads or cleans
-- something differently. When the live data moves to a period the archive does not have yet,
-- the join on the period makes this test compare nothing until the archive catches up.

with live_hrrp as (
    select facility_id, condition, period_start, period_end,
           discharges, readmissions, excess_readmission_ratio, footnote_code
    from {{ ref('stg_cms__hrrp') }}
),

history_hrrp as (
    select h.facility_id, h.condition, h.period_start, h.period_end,
           h.discharges, h.readmissions, h.excess_readmission_ratio, h.footnote_code
    from {{ ref('stg_cms__hrrp_history') }} as h
    where (h.period_start, h.period_end) in (select distinct period_start, period_end from live_hrrp)
),

live_hcahps as (
    select facility_id, measure_id, period_start, period_end,
           linear_mean_score, star_rating, completed_surveys
    from {{ ref('stg_cms__hcahps') }}
    where regexp_matches(measure_id, '_(LINEAR_SCORE|STAR_RATING)$')
),

history_hcahps as (
    select h.facility_id, h.measure_id, h.period_start, h.period_end,
           h.linear_mean_score, h.star_rating, h.completed_surveys
    from {{ ref('stg_cms__hcahps_history') }} as h
    where (h.period_start, h.period_end) in (select distinct period_start, period_end from live_hcahps)
),

differences as (
    (select 'hrrp: live only' as side, facility_id, condition as measure from (select * from live_hrrp except select * from history_hrrp))
    union all
    (select 'hrrp: archive only', facility_id, condition from (select * from history_hrrp except select * from live_hrrp))
    union all
    (select 'hcahps: live only', facility_id, measure_id from (select * from live_hcahps except select * from history_hcahps))
    union all
    (select 'hcahps: archive only', facility_id, measure_id from (select * from history_hcahps except select * from live_hcahps))
)

select * from differences
