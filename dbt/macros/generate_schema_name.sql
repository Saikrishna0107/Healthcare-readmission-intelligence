{#
    Put each layer in a schema named exactly after it (staging, intermediate, marts).

    dbt's default prefixes the target schema ("main_staging"), which is meant for teams where
    each developer builds into their own schema. With one local DuckDB file, plain names are
    easier to query: select * from staging.stg_cms__hrrp
#}
{% macro generate_schema_name(custom_schema_name, node) -%}
    {%- if custom_schema_name is none -%}
        {{ target.schema }}
    {%- else -%}
        {{ custom_schema_name | trim }}
    {%- endif -%}
{%- endmacro %}
