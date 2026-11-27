-- One row per user per calendar month in which the user had a session or a
-- transaction. Revenue follows the documented sign convention (amount_usd as stored).
with active as (
    select user_id, date_trunc('month', date)::date as month, count(*) as active_days
    from {{ ref('sessions') }} group by 1, 2
),
money as (
    select user_id, date_trunc('month', date)::date as month,
           sum(amount_usd) filter (where status = 'success') as net_revenue,
           sum(amount_usd) filter (where status = 'success' and type in ('subscription', 'ppv')) as gross_revenue,
           count(*) filter (where status = 'success' and type in ('subscription', 'ppv')) as successful_charges,
           count(*) filter (where status = 'success' and type = 'subscription') as subscription_charges,
           count(*) filter (where status = 'success' and type = 'ppv') as ppv_charges,
           count(*) filter (where type = 'refund') as refunds
    from {{ ref('transactions') }} group by 1, 2
),
keys as (select user_id, month from active union select user_id, month from money)
select
    k.user_id,
    k.month,
    u.country,
    u.acquisition_source,
    u.signup_date,
    date_trunc('month', u.signup_date)::date as signup_month,
    coalesce(a.active_days, 0) > 0 as is_active,
    coalesce(a.active_days, 0) as active_days,
    coalesce(m.successful_charges, 0) > 0 as is_payer,
    coalesce(m.net_revenue, 0) as net_revenue,
    coalesce(m.gross_revenue, 0) as gross_revenue,
    coalesce(m.subscription_charges, 0) as subscription_charges,
    coalesce(m.ppv_charges, 0) as ppv_charges,
    coalesce(m.refunds, 0) as refunds
from keys k
join {{ ref('users') }} u using (user_id)
left join active a using (user_id, month)
left join money m using (user_id, month)
