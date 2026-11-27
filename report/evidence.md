# Evidence: queries behind the board deck

Each query ran through `agent.tools` (read-only, guarded). IDs match the deck.

## Q1: dq: null_share (transactions)

Source: `run_dq_checks`, rows: 1

```sql
SELECT avg(("txn_id" IS NULL)::int) AS "txn_id", avg(("user_id" IS NULL)::int) AS "user_id", avg(("date" IS NULL)::int) AS "date", avg(("created_at" IS NULL)::int) AS "created_at", avg(("type" IS NULL)::int) AS "type", avg(("amount_usd" IS NULL)::int) AS "amount_usd", avg(("payment_method" IS NULL)::int) AS "payment_method", avg(("status" IS NULL)::int) AS "status" FROM transactions
```

## Q2: dq: duplicate_primary_key (transactions)

Source: `run_dq_checks`, rows: 1

```sql
SELECT count(*) - count(DISTINCT txn_id) AS dup FROM transactions
```

## Q3: dq: date_coverage (transactions)

Source: `run_dq_checks`, rows: 1

```sql
WITH d AS (SELECT date AS day, count(*) AS n FROM transactions GROUP BY 1),
                last AS (SELECT max(day) AS mx FROM d)
                SELECT min(day) AS first_day, max(day) AS last_day, count(*) AS days_with_rows,
                       date_diff('day', min(day), max(day)) + 1 AS days_spanned,
                       avg(n) FILTER (WHERE day > (SELECT mx FROM last) - 14) AS avg_rows_last_14d,
                       avg(n) FILTER (WHERE day <= (SELECT mx FROM last) - 14
                                        AND day > (SELECT mx FROM last) - 42) AS avg_rows_prior_28d
                FROM d
```

## Q4: dq: amount_sign_by_type_method_month (transactions)

Source: `run_dq_checks`, rows: 54

```sql
SELECT type, payment_method, strftime(date, '%Y-%m') AS month, count(*) AS n,
                       count(*) FILTER (WHERE amount_usd > 0) AS positive,
                       count(*) FILTER (WHERE amount_usd < 0) AS negative,
                       count(*) FILTER (WHERE amount_usd = 0) AS zero
                FROM transactions WHERE status = 'success' GROUP BY 1, 2, 3 ORDER BY 1, 2, 3
```

## Q5: dq: distinct_amounts_by_type (transactions)

Source: `run_dq_checks`, rows: 6

```sql
SELECT type, round(abs(amount_usd), 2) AS abs_amount, count(*) AS n
                FROM transactions GROUP BY 1, 2 ORDER BY 1, 3 DESC
```

## Q6: dq: duplicate_charges_5min (transactions)

Source: `run_dq_checks`, rows: 6

```sql
SELECT strftime(a.date, '%Y-%m') AS month, count(*) AS duplicate_pairs,
                       (SELECT count(*) FROM transactions WHERE status='success' AND type<>'refund') AS successful_charges
                FROM transactions a JOIN transactions b
                  ON a.user_id = b.user_id AND a.type = b.type AND a.amount_usd = b.amount_usd
                 AND a.txn_id < b.txn_id AND a.status = 'success' AND b.status = 'success'
                 AND abs(epoch(b.created_at) - epoch(a.created_at)) <= 300
                WHERE a.type <> 'refund' GROUP BY 1 ORDER BY 1
```

## Q7: dq: failure_rate_by_method_month (transactions)

Source: `run_dq_checks`, rows: 18

```sql
SELECT payment_method, strftime(date, '%Y-%m') AS month,
                       round(avg((status = 'failed')::int), 4) AS failed_share, count(*) AS attempts
                FROM transactions WHERE type <> 'refund' GROUP BY 1, 2 ORDER BY 1, 2
```

## Q8: dq: orphan_user_ids (transactions)

Source: `run_dq_checks`, rows: 1

```sql
SELECT count(*) AS orphans FROM transactions x LEFT JOIN users u USING (user_id) WHERE u.user_id IS NULL
```

## Q9: dq: null_share (sessions)

Source: `run_dq_checks`, rows: 1

```sql
SELECT avg(("session_id" IS NULL)::int) AS "session_id", avg(("user_id" IS NULL)::int) AS "user_id", avg(("date" IS NULL)::int) AS "date", avg(("duration_sec" IS NULL)::int) AS "duration_sec", avg(("platform" IS NULL)::int) AS "platform" FROM sessions
```

## Q10: dq: duplicate_primary_key (sessions)

Source: `run_dq_checks`, rows: 1

```sql
SELECT count(*) - count(DISTINCT session_id) AS dup FROM sessions
```

## Q11: dq: date_coverage (sessions)

Source: `run_dq_checks`, rows: 1

```sql
WITH d AS (SELECT date AS day, count(*) AS n FROM sessions GROUP BY 1),
                last AS (SELECT max(day) AS mx FROM d)
                SELECT min(day) AS first_day, max(day) AS last_day, count(*) AS days_with_rows,
                       date_diff('day', min(day), max(day)) + 1 AS days_spanned,
                       avg(n) FILTER (WHERE day > (SELECT mx FROM last) - 14) AS avg_rows_last_14d,
                       avg(n) FILTER (WHERE day <= (SELECT mx FROM last) - 14
                                        AND day > (SELECT mx FROM last) - 42) AS avg_rows_prior_28d
                FROM d
```

## Q12: dq: orphan_user_ids (sessions)

Source: `run_dq_checks`, rows: 1

```sql
SELECT count(*) AS orphans FROM sessions x LEFT JOIN users u USING (user_id) WHERE u.user_id IS NULL
```

## Q13: dq: nonpositive_duration_and_before_signup (sessions)

Source: `run_dq_checks`, rows: 6

```sql
SELECT strftime(s.date, '%Y-%m') AS month, count(*) AS sessions,
                       count(*) FILTER (WHERE duration_sec <= 0) AS nonpositive_duration,
                       count(*) FILTER (WHERE s.date < u.signup_date) AS before_signup
                FROM sessions s JOIN users u USING (user_id) GROUP BY 1 ORDER BY 1
```

## Q14: monthly MAU and net revenue, as stored and with refunds forced negative

Source: `run_sql`, rows: 6

```sql
WITH m AS (SELECT date_trunc('month', date) AS month, COUNT(DISTINCT user_id) AS mau FROM sessions GROUP BY 1),
r AS (SELECT date_trunc('month', date) AS month, SUM(amount_usd) AS rev_stored,
             SUM(CASE WHEN type = 'refund' THEN -abs(amount_usd) ELSE amount_usd END) AS rev_corrected
      FROM transactions WHERE status = 'success' GROUP BY 1)
SELECT strftime(month, '%Y-%m') AS month, mau, rev_stored, rev_corrected FROM m JOIN r USING (month) ORDER BY 1
```

## Q15: refund sign by month x method

Source: `run_sql`, rows: 18

```sql
SELECT strftime(date, '%Y-%m') AS month, payment_method,
       COUNT(*) AS refunds, COUNT(*) FILTER (WHERE amount_usd > 0) AS positive
FROM transactions WHERE type = 'refund' GROUP BY 1, 2 ORDER BY 1, 2
```

## Q16: observed free-episode allowance per day

Source: `run_sql`, rows: 183

```sql
SELECT date, MAX(free_views) AS observed_limit FROM fct_user_day GROUP BY 1 ORDER BY 1
```

## Q17: limit-hit rate and purchases per limit hit, before/after, by market

Source: `run_sql`, rows: 4

```sql
WITH d AS (SELECT *, free_views = MAX(free_views) OVER (PARTITION BY date) AS hit FROM fct_user_day WHERE sub_views = 0)
SELECT date >= '2026-09-01' AS q2, CASE WHEN country = 'US' THEN 'US' ELSE 'New markets' END AS market,
       AVG(hit::INT) AS hit_rate, SUM(hit::INT) AS hit_days,
       SUM((subscription_charges + ppv_charges) * hit::INT) * 1.0 / SUM(hit::INT) AS purchases_per_hit
FROM d GROUP BY ALL ORDER BY 1, 2
```

## Q18: payer rate and MAU by market by month

Source: `run_sql`, rows: 12

```sql
SELECT strftime(month, '%Y-%m') AS month, CASE WHEN country = 'US' THEN 'US' ELSE 'New markets' END AS market,
       AVG(is_payer::INT) AS payer_rate, COUNT(*) AS mau
FROM fct_user_month WHERE is_active GROUP BY ALL ORDER BY 1, 2
```

## Q19: spend share TikTok + influencer by month

Source: `run_sql`, rows: 6

```sql
SELECT strftime(date, '%Y-%m') AS month,
       SUM(spend_usd) FILTER (WHERE channel IN ('tiktok_ads','influencer')) / SUM(spend_usd) AS tiktok_influencer_share,
       SUM(spend_usd) AS spend FROM marketing_spend GROUP BY 1 ORDER BY 1
```

## Q20: Q2 CPI vs cost per paying user (paid within 30 days) by channel

Source: `run_sql`, rows: 4

```sql
WITH c AS (SELECT user_id, signup_date, acquisition_source FROM users WHERE signup_date BETWEEN '2026-09-01' AND '2026-11-30'),
p AS (SELECT acquisition_source AS channel, COUNT(*) AS signups,
        COUNT(*) FILTER (WHERE EXISTS (SELECT 1 FROM transactions t WHERE t.user_id = c.user_id AND t.status = 'success'
             AND t.type IN ('subscription','ppv') AND t.date BETWEEN c.signup_date AND c.signup_date + 30)) AS payers_30d,
        AVG(CASE WHEN country_us THEN 1 ELSE 0 END) AS us_share
      FROM (SELECT c.*, u.country = 'US' AS country_us FROM c JOIN users u USING (user_id)) c GROUP BY 1),
s AS (SELECT channel, SUM(spend_usd) AS spend FROM marketing_spend WHERE date BETWEEN '2026-09-01' AND '2026-11-30' GROUP BY 1)
SELECT channel, spend, signups, spend / signups AS cpi, payers_30d, spend / payers_30d AS cost_per_payer, us_share
FROM s JOIN p USING (channel) ORDER BY cost_per_payer
```

## Q21: D30 retention by signup cohort, overall and by market

Source: `run_sql`, rows: 15

```sql
WITH c AS (SELECT user_id, signup_date, strftime(signup_date, '%Y-%m') AS cohort,
                        CASE WHEN country = 'US' THEN 'US' ELSE 'new_markets' END AS market FROM users
                 WHERE signup_date BETWEEN '2026-06-01' AND '2026-10-24'),
r AS (SELECT cohort, market, CASE WHEN EXISTS (SELECT 1 FROM sessions s WHERE s.user_id = c.user_id
        AND s.date BETWEEN c.signup_date + 30 AND c.signup_date + 36) THEN 1 ELSE 0 END AS kept FROM c)
SELECT cohort, market, AVG(kept) AS d30, COUNT(*) AS users FROM r GROUP BY GROUPING SETS ((cohort), (cohort, market))
ORDER BY 1, 2 NULLS FIRST
```

## Q22: payer rate by platform within market

Source: `run_sql`, rows: 12

```sql
WITH up AS (SELECT user_id, any_value(platform) AS platform FROM sessions GROUP BY 1)
SELECT platform, CASE WHEN country = 'US' THEN 'US' ELSE 'New markets' END AS market, month >= DATE '2026-09-01' AS q2,
       AVG(is_payer::INT) AS payer_rate, COUNT(*) AS user_months
FROM fct_user_month JOIN up USING (user_id) WHERE is_active GROUP BY ALL ORDER BY 1, 2, 3
```

## Q23: payer rate by platform overall

Source: `run_sql`, rows: 6

```sql
WITH up AS (SELECT user_id, any_value(platform) AS platform FROM sessions GROUP BY 1)
SELECT platform, month >= DATE '2026-09-01' AS q2, AVG(is_payer::INT) AS payer_rate
FROM fct_user_month JOIN up USING (user_id) WHERE is_active GROUP BY ALL ORDER BY 1, 2
```

## Q24: charge failure share by method

Source: `run_sql`, rows: 3

```sql
SELECT payment_method, AVG((status = 'failed')::INT) AS failed_share FROM transactions
WHERE type <> 'refund' GROUP BY 1 ORDER BY 1
```

## Q25: revenue by product line, Q1 vs Q2

Source: `run_sql`, rows: 2

```sql
SELECT date >= '2026-09-01' AS q2,
       SUM(amount_usd) FILTER (WHERE type = 'ppv' AND amount_usd = 0.99) AS unlock_rev,
       SUM(amount_usd) FILTER (WHERE type = 'ppv' AND amount_usd = 1.99) AS premium_rev,
       SUM(amount_usd) FILTER (WHERE type = 'subscription') AS sub_rev
FROM transactions WHERE status = 'success' GROUP BY 1 ORDER BY 1
```

## Q26: completion rate by month

Source: `run_sql`, rows: 6

```sql
SELECT strftime(date, '%Y-%m') AS month, SUM(watch_duration_sec) * 1.0 / SUM(content_duration_sec) AS completion
FROM content_views GROUP BY 1 ORDER BY 1
```

## Q27: distinct amounts (price changes, currency)

Source: `run_sql`, rows: 6

```sql
SELECT type, round(abs(amount_usd), 2) AS amount, COUNT(*) AS n FROM transactions GROUP BY 1, 2 ORDER BY 1, 2
```

## Q28: decompose net_revenue by market (force_negative)

Source: `decompose_change`, rows: 0

```sql
-- period A

    WITH act AS (
        SELECT user_id, date_trunc('month', date) AS m FROM sessions
        WHERE date BETWEEN DATE '2026-06-01' AND DATE '2026-08-31' GROUP BY 1, 2),
    pay AS (
        SELECT user_id, date_trunc('month', date) AS m,
               sum(CASE WHEN type = 'refund' THEN -abs(amount_usd) ELSE amount_usd END) AS rev,
               count(*) FILTER (WHERE type IN ('subscription','ppv')) AS charges
        FROM transactions WHERE status = 'success' AND date BETWEEN DATE '2026-06-01' AND DATE '2026-08-31'
        GROUP BY 1, 2),
    um AS (
        SELECT coalesce(act.user_id, pay.user_id) AS user_id, coalesce(act.m, pay.m) AS m,
               act.user_id IS NOT NULL AS active, coalesce(pay.charges, 0) > 0 AS payer,
               coalesce(pay.rev, 0) AS rev
        FROM act FULL OUTER JOIN pay ON act.user_id = pay.user_id AND act.m = pay.m)
    SELECT CASE WHEN country = 'US' THEN 'US' ELSE 'new_markets' END AS seg, count(DISTINCT m) AS months,
           count(*) FILTER (WHERE active) AS mau_sum,
           count(*) FILTER (WHERE payer) AS payers_sum,
           sum(rev) AS rev_sum
    FROM um JOIN users USING (user_id) GROUP BY 1 ORDER BY 1
-- period B

    WITH act AS (
        SELECT user_id, date_trunc('month', date) AS m FROM sessions
        WHERE date BETWEEN DATE '2026-09-01' AND DATE '2026-11-30' GROUP BY 1, 2),
    pay AS (
        SELECT user_id, date_trunc('month', date) AS m,
               sum(CASE WHEN type = 'refund' THEN -abs(amount_usd) ELSE amount_usd END) AS rev,
               count(*) FILTER (WHERE type IN ('subscription','ppv')) AS charges
        FROM transactions WHERE status = 'success' AND date BETWEEN DATE '2026-09-01' AND DATE '2026-11-30'
        GROUP BY 1, 2),
    um AS (
        SELECT coalesce(act.user_id, pay.user_id) AS user_id, coalesce(act.m, pay.m) AS m,
               act.user_id IS NOT NULL AS active, coalesce(pay.charges, 0) > 0 AS payer,
               coalesce(pay.rev, 0) AS rev
        FROM act FULL OUTER JOIN pay ON act.user_id = pay.user_id AND act.m = pay.m)
    SELECT CASE WHEN country = 'US' THEN 'US' ELSE 'new_markets' END AS seg, count(DISTINCT m) AS months,
           count(*) FILTER (WHERE active) AS mau_sum,
           count(*) FILTER (WHERE payer) AS payers_sum,
           sum(rev) AS rev_sum
    FROM um JOIN users USING (user_id) GROUP BY 1 ORDER BY 1
```

## Q29: weekly limit-hit rate by market (chart)

Source: `run_sql`, rows: 54

```sql
WITH d AS (SELECT *, free_views = MAX(free_views) OVER (PARTITION BY date) AS hit FROM fct_user_day WHERE sub_views = 0)
SELECT date_trunc('week', date) AS week, CASE WHEN country = 'US' THEN 'US' ELSE 'New markets' END AS market, AVG(hit::INT) AS hit_rate
FROM d GROUP BY ALL ORDER BY 1
```
