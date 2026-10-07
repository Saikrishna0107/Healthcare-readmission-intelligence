{#
    The rows of a CMS archive source, one snapshot per performance period (D-023).

    Every archive snapshot publishes one period, and CMS keeps showing the same period for
    several quarters (3 to 5 snapshots). Readmission copies are identical; survey copies differ
    in a few dozen corrected values. The latest snapshot of each period is kept whole: it is
    CMS's final word on that period, and its rows stay a consistent published file.

    Adds two columns: _period_first_release (when the period was first published) and
    _period_snapshots (how many snapshots showed it).

    Usage:  select * from {{ latest_snapshot_per_period('hrrp_archive', '"Start Date"', '"End Date"') }}
#}
{% macro latest_snapshot_per_period(table_name, start_column, end_column) %}
    (
        with snapshot_periods as (
            select distinct
                _release,
                {{ start_column }} as _period_start,
                {{ end_column }}   as _period_end
            from {{ source('raw', table_name) }}
        ),

        chosen as (
            select
                _period_start,
                _period_end,
                max(_release)   as _release,
                min(_release)   as _period_first_release,
                count(*)        as _period_snapshots
            from snapshot_periods
            group by _period_start, _period_end
        )

        select raw.*, chosen._period_first_release, chosen._period_snapshots
        from {{ source('raw', table_name) }} as raw
        join chosen
            on raw._release = chosen._release
           and {{ start_column }} = chosen._period_start
           and {{ end_column }} = chosen._period_end
    )
{% endmacro %}
