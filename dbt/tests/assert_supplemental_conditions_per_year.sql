-- Every hospital-year in the supplemental files has a payment row and its condition rows:
-- 6 conditions, or 5 in FY 2023 when CMS suppressed pneumonia because of COVID-19.
-- Returns the hospital-years that break this.
--
-- Catches a condition silently dropped by the wide-to-long reshape (for example a column
-- renamed in a new year's file), and pneumonia rows appearing for FY 2023.

with conditions as (
    select
        facility_id,
        fiscal_year,
        count(*)                                  as condition_rows,
        count(*) filter (where condition = 'PN')  as pneumonia_rows
    from {{ ref('stg_cms__hrrp_peer_comparisons') }}
    group by facility_id, fiscal_year
)

select
    coalesce(a.facility_id, c.facility_id)  as facility_id,
    coalesce(a.fiscal_year, c.fiscal_year)  as fiscal_year,
    a.facility_id is not null               as has_payment_row,
    c.condition_rows,
    c.pneumonia_rows
from {{ ref('stg_cms__hrrp_payment_adjustments') }} as a
full join conditions as c using (facility_id, fiscal_year)
where a.facility_id is null
   or c.facility_id is null
   or c.condition_rows <> case when a.fiscal_year = 'FY2023' then 5 else 6 end
   or (a.fiscal_year = 'FY2023' and c.pneumonia_rows > 0)
