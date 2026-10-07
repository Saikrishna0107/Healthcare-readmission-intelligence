-- Every public HRRP result and every supplemental condition row lands in fct_readmissions
-- exactly once. Returns the source whose count does not match.
--
-- The full outer join on hospital, condition and fiscal year should neither drop rows (a key
-- that fails to match is kept as a one-sided row) nor duplicate them.

with counts as (
    select
        'stg_cms__hrrp_history'                                                     as source,
        (select count(*) from {{ ref('stg_cms__hrrp_history') }})                   as expected,
        (select count(*) from {{ ref('fct_readmissions') }} where in_public_file)   as actual
    union all
    select
        'stg_cms__hrrp_peer_comparisons',
        (select count(*) from {{ ref('stg_cms__hrrp_peer_comparisons') }}),
        (select count(*) from {{ ref('fct_readmissions') }} where in_payment_file)
)

select * from counts where expected <> actual
