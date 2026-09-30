{#
    Fails when a combination of columns appears more than once, e.g. a hospital with two rows
    for the same condition. dbt's built-in `unique` test only checks a single column.

    Every dbt test works the same way: it is a SELECT that returns the rows breaking the rule.
    No rows = pass. This one returns each duplicated combination and how often it appears.
#}
{% test unique_combination_of_columns(model, combination) %}
    select
        {{ combination | join(', ') }},
        count(*) as occurrences
    from {{ model }}
    group by {{ combination | join(', ') }}
    having count(*) > 1
{% endtest %}
