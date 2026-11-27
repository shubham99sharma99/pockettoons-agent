-- One row per user per active day (a day with >= 1 session), with viewing and
-- purchase counts. Generic building block for engagement and paywall analysis.
with s as (
    select user_id, date, count(*) as sessions, sum(duration_sec) as session_sec,
           any_value(platform) as platform
    from {{ ref('sessions') }}
    group by 1, 2
),
v as (
    select cv.user_id, cv.date,
           count(*) as views_total,
           count(*) filter (where view_type = 'free') as free_views,
           count(*) filter (where view_type = 'sub') as sub_views,
           count(*) filter (where view_type = 'ppv') as ppv_views,
           count(*) filter (where view_type = 'ppv' and cc.content_tier = 'standard') as ppv_standard_views,
           count(*) filter (where view_type = 'ppv' and cc.content_tier = 'premium') as ppv_premium_views,
           sum(watch_duration_sec) as watch_sec
    from {{ ref('content_views') }} cv
    join {{ ref('content_catalog') }} cc using (content_id)
    group by 1, 2
),
t as (
    select user_id, date,
           count(*) filter (where status = 'success' and type = 'subscription') as subscription_charges,
           count(*) filter (where status = 'success' and type = 'ppv') as ppv_charges,
           count(*) filter (where status = 'failed') as failed_charges
    from {{ ref('transactions') }}
    group by 1, 2
)
select
    s.user_id,
    s.date,
    u.country,
    u.acquisition_source,
    u.signup_date,
    s.platform,
    s.date - u.signup_date as days_since_signup,
    s.sessions,
    s.session_sec,
    coalesce(v.views_total, 0) as views_total,
    coalesce(v.free_views, 0) as free_views,
    coalesce(v.sub_views, 0) as sub_views,
    coalesce(v.ppv_views, 0) as ppv_views,
    coalesce(v.ppv_standard_views, 0) as ppv_standard_views,
    coalesce(v.ppv_premium_views, 0) as ppv_premium_views,
    coalesce(v.watch_sec, 0) as watch_sec,
    coalesce(t.subscription_charges, 0) as subscription_charges,
    coalesce(t.ppv_charges, 0) as ppv_charges,
    coalesce(t.failed_charges, 0) as failed_charges
from s
join {{ ref('users') }} u using (user_id)
left join v using (user_id, date)
left join t using (user_id, date)
