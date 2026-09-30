-- HRRP Supplemental Data File: the condition-level part, reshaped from wide to long.
-- Grain: one row per hospital x condition.
--
-- The file has one block of five columns per condition ("ERR for HF", "Peer group median ERR
-- for HF", ...). The Jinja loop below writes one SELECT per condition and stacks them, so the
-- result lines up with stg_cms__hrrp (same condition codes, one row per hospital x condition).

{%- set conditions = {
    'AMI': 'AMI',
    'COPD': 'COPD',
    'HF': 'HF',
    'PN': 'pneumonia',
    'CABG': 'CABG',
    'HIP_KNEE': 'THA/TKA',
} %}

with source as (
    select * from {{ latest_release('hrrp_supplemental') }}
    where "Hospital CCN" <> 'End of worksheet'
)

{% for code, label in conditions.items() %}
select
    "Hospital CCN"                                                               as facility_id,
    _release                                                                     as fiscal_year,
    '{{ code }}'                                                                 as condition,
    -- '.' means the hospital had no eligible discharges for this condition.
    coalesce({{ to_number('"Number of eligible discharges for ' ~ label ~ '"', 'integer') }}, 0)
                                                                                 as eligible_discharges,
    {{ to_number('"ERR for ' ~ label ~ '"') }}                                   as excess_readmission_ratio,
    {{ to_number('"Peer group median ERR for ' ~ label ~ '"') }}                 as peer_group_median_err,
    "Penalty indicator for {{ label }}" = 'Y'                                    as is_above_peer_median,
    {{ to_number('"DRG payment ratio for ' ~ label ~ '"') }}                     as drg_payment_ratio
from source
{% if not loop.last %}union all{% endif %}
{% endfor %}
