-- CMS Footnote Crosswalk, latest release.
-- Grain: one row per footnote code. Translates codes such as '1' or '29' into their meaning.

select
    "Footnote"          as footnote_code,
    "Footnote Text"     as footnote_text
from {{ latest_release('footnotes') }}
