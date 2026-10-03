-- Every hospital in a CMS source must have a row in dim_hospital, or its facts would vanish
-- from any join to the dimension. Returns the hospitals that are missing.

select 'stg_cms__hospitals' as source, facility_id from {{ ref('stg_cms__hospitals') }}
union
select 'stg_cms__hrrp', facility_id from {{ ref('stg_cms__hrrp') }}
union
select 'stg_cms__hrrp_payment_adjustments', facility_id
from {{ ref('stg_cms__hrrp_payment_adjustments') }}
except
select s.source, d.facility_id
from {{ ref('dim_hospital') }} as d
cross join (values ('stg_cms__hospitals'), ('stg_cms__hrrp'),
                   ('stg_cms__hrrp_payment_adjustments')) as s(source)
