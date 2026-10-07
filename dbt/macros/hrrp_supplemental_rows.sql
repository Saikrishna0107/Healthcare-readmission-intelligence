{#
    The hospital rows of every HRRP Supplemental Data File (FY 2020 - FY 2026).

    Removed, and nothing else: the footer line ("end of worksheet" in FY 2020-2021,
    "End of worksheet" later) and the empty rows some years end with (3 in FY 2023, 68 in
    FY 2025). Any other non-hospital row would fail the CCN format test in staging.
#}
{% macro hrrp_supplemental_rows() %}
    (
        select *
        from {{ source('raw', 'hrrp_supplemental') }}
        where lower(trim("Hospital CCN")) <> 'end of worksheet'
          and trim("Hospital CCN") <> ''
    )
{% endmacro %}
