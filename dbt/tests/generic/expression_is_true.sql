{#
    Fails for every row where a SQL condition is false. Used for rules that involve several
    columns, e.g. "a scored row has ERR = predicted / expected".

    A condition that evaluates to NULL is not counted as a failure (SQL's `not null` is NULL,
    not true), so write the expression to handle NULLs explicitly when they matter.

    It can be attached to a model or to a column. On a column, dbt also passes `column_name`;
    it is accepted but not needed, because the expression names its columns itself.
#}
{% test expression_is_true(model, expression, column_name=none) %}
    select *
    from {{ model }}
    where not ({{ expression }})
{% endtest %}
