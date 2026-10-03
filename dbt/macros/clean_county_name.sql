{#
    A comparison key for county names, so 'ST. LOUIS CITY' (CMS) and 'St. Louis city' (Census)
    or 'DE KALB' and 'DeKalb County' give the same key.

    Steps: remove accents (Doña Ana), upper-case, drop punctuation, SAINT -> ST, drop the type
    word at the end (COUNTY, PARISH, BOROUGH, ...; the longest first, so 'Juneau City and
    Borough' loses the whole phrase), then remove all spaces (DE KALB = DEKALB).

    'CITY' is kept on purpose: 'BALTIMORE CITY' and 'BALTIMORE' are different places.
    Based on clean_county() in the step 2 notebook, which removed 'BOROUGH' before
    'CITY AND BOROUGH' and so left 'JUNEAU CITY AND'.
#}
{% macro clean_county_name(column) %}
    replace(
        regexp_replace(
            replace(
                regexp_replace(upper(strip_accents(trim({{ column }}))), '[.''’]', '', 'g'),
                'SAINT ', 'ST '
            ),
            '\s+(CITY AND BOROUGH|CENSUS AREA|MUNICIPALITY|COUNTY|PARISH|BOROUGH)$', ''
        ),
        ' ', ''
    )
{% endmacro %}
