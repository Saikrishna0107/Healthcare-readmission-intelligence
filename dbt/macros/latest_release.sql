{#
    The rows of the newest stored release of a raw source.

    Raw sources hold every release side by side (D-019). Staging works on the newest one;
    step 6 will read older releases on purpose to line up time periods.

    Usage:  select * from {{ latest_release('hrrp') }}
#}
{% macro latest_release(table_name) %}
    (
        select *
        from {{ source('raw', table_name) }}
        where _release = (select max(_release) from {{ source('raw', table_name) }})
    )
{% endmacro %}
