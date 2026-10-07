{#
    Why an HRRP excess readmission ratio is (or is not) there, in words instead of footnote
    codes (D-003). Footnotes 23 and 29 (claims discrepancies, partial period) come with a ratio,
    so those rows are 'scored'. 'unknown' means a code not seen before; a test fails on it.
#}
{% macro hrrp_score_status(ratio, footnote_code) %}
    case
        when {{ ratio }} is not null then 'scored'
        when {{ footnote_code }} = '1' then 'too_few_cases'
        when {{ footnote_code }} = '5' then 'not_available'
        when {{ footnote_code }} = '7' then 'no_cases'
        else 'unknown'
    end
{% endmacro %}
