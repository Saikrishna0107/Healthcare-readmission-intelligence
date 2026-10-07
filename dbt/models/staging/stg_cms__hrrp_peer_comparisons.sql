-- HRRP Supplemental Data Files: the condition-level part, every fiscal year, wide to long.
-- Grain: one row per hospital x fiscal year x condition.
--
-- The file has one block of five columns per condition ("ERR for HF", "Peer group median ERR
-- for HF", ...). The Jinja loop below writes one SELECT per condition and stacks them, so the
-- result lines up with stg_cms__hrrp (same condition codes).
--
-- Capitalization differs by year ("ERR for Pneumonia" in FY 2020, "ERR for pneumonia" later);
-- DuckDB matches column names case-insensitively, so one name reads every year.
-- CMS left pneumonia out of FY 2023 because of COVID-19: that file has no pneumonia columns,
-- and a condition whose columns are missing from a year's file gets no rows for that year
-- (rather than rows that look like "no discharges").

{%- set conditions = {
    'AMI': 'AMI',
    'COPD': 'COPD',
    'HF': 'HF',
    'PN': 'pneumonia',
    'CABG': 'CABG',
    'HIP_KNEE': 'THA/TKA',
} %}

with source as (
    select * from {{ hrrp_supplemental_rows() }}
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
-- NULL (not '.' or '') only when the column is absent from that year's file.
where "Number of eligible discharges for {{ label }}" is not null
{% if not loop.last %}union all{% endif %}
{% endfor %}
