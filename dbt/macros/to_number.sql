{#
    Convert a raw text column to a number.

    - The publishers' "no value" markers become NULL: empty text, 'N/A', 'Not Available',
      'Not Applicable', 'Too Few to Report' and '.'. Why a value is missing is kept in separate
      columns (footnotes, status flags), never by turning it into 0.
      'Not Applicable' (HCAHPS) is structural: the column does not apply to that kind of row,
      e.g. a star rating on an answer-percentage row. 'Not Available' means the hospital's
      value is missing.
    - Thousands separators ('1,360') and percent signs ('0.12%') are removed.
      A percentage stays in percent units: '0.12%' becomes 0.12.
    - Anything else goes through a strict CAST, not TRY_CAST. If CMS or CDC starts publishing a
      new marker such as 'Suppressed', the build fails and shows the value, instead of silently
      turning it into NULL.

    Usage:  {{ to_number('"Number of Discharges"', 'integer') }}
#}
{% macro to_number(column, type='double') %}
    cast(
        case
            when trim({{ column }}) in ('', 'N/A', 'Not Available', 'Not Applicable', 'Too Few to Report', '.') then null
            else replace(replace(trim({{ column }}), ',', ''), '%', '')
        end
        as {{ type }}
    )
{% endmacro %}
