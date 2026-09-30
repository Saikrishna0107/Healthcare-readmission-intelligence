{#
    Fails when a column has values outside [min_value, max_value]. NULLs are allowed; use
    `not_null` for that. Catches unit mistakes, e.g. a percentage stored as 0.12 in one release
    and 12 in the next.
#}
{% test accepted_range(model, column_name, min_value=none, max_value=none) %}
    select {{ column_name }}
    from {{ model }}
    where false
        {%- if min_value is not none %} or {{ column_name }} < {{ min_value }}{% endif %}
        {%- if max_value is not none %} or {{ column_name }} > {{ max_value }}{% endif %}
{% endtest %}
