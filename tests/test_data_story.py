"""The planted story must actually be in the data (ground-truth checks G1-G9)."""
import pytest

from agent import db

pytestmark = pytest.mark.needs_db
q = lambda sql: db.query_df(sql).iloc[0].to_dict()  # noqa: E731


def test_g1_mau_up_about_20pct():
    r = q("""WITH m AS (SELECT date_trunc('month', date) m, count(DISTINCT user_id) mau FROM sessions GROUP BY 1)
             SELECT avg(mau) FILTER (WHERE m >= '2026-09-01') / avg(mau) FILTER (WHERE m < '2026-09-01') - 1 AS g FROM m""")
    assert 0.15 <= r["g"] <= 0.25


def test_g2_g3_refund_sign_bug_hides_decline():
    r = q("""SELECT count(*) FILTER (WHERE amount_usd > 0 AND payment_method = 'google_play' AND date >= '2026-10-01') pos_bug,
                    count(*) FILTER (WHERE amount_usd > 0 AND (payment_method <> 'google_play' OR date < '2026-10-01')) pos_other,
                    count(*) FILTER (WHERE payment_method = 'google_play' AND date >= '2026-10-01') gp_after
             FROM transactions WHERE type = 'refund'""")
    assert r["pos_bug"] == r["gp_after"] > 0 and r["pos_other"] == 0
    r = q("""SELECT sum(amount_usd) FILTER (WHERE date >= '2026-09-01') / sum(amount_usd) FILTER (WHERE date < '2026-09-01') - 1 AS naive,
                    sum(CASE WHEN type='refund' THEN -abs(amount_usd) ELSE amount_usd END) FILTER (WHERE date >= '2026-09-01')
                  / sum(CASE WHEN type='refund' THEN -abs(amount_usd) ELSE amount_usd END) FILTER (WHERE date < '2026-09-01') - 1 AS true_
             FROM transactions WHERE status = 'success'""")
    assert -0.04 <= r["naive"] <= 0.0 and r["true_"] < r["naive"] - 0.01 and r["true_"] < -0.03


def test_g4_observed_free_limit_steps_on_sep_1():
    df = db.query_df("SELECT date, max(free_views) lim FROM fct_user_day GROUP BY 1 ORDER BY 1")
    before = df[df.date.astype(str) < "2026-09-01"].lim
    after = df[df.date.astype(str) >= "2026-09-01"].lim
    assert before.max() == 5 and after.max() == 8 and (after >= 6).mean() > 0.9


def test_g5_us_payer_rate_falls_without_us_mix_change():
    r = q("""SELECT avg(is_payer::int) FILTER (WHERE month < '2026-09-01') a, avg(is_payer::int) FILTER (WHERE month >= '2026-09-01') b
             FROM fct_user_month WHERE is_active AND country = 'US'""")
    assert r["b"] < r["a"] * 0.95


def test_g6_android_gap_is_mix():
    df = db.query_df("""WITH up AS (SELECT user_id, any_value(platform) p FROM sessions GROUP BY 1)
        SELECT country = 'US' AS us, p = 'android' AS android, avg(is_payer::int) pr
        FROM fct_user_month JOIN up USING (user_id) WHERE is_active AND month >= '2026-09-01' GROUP BY ALL""")
    overall = db.query_df("""WITH up AS (SELECT user_id, any_value(platform) p FROM sessions GROUP BY 1)
        SELECT p = 'android' AS android, avg(is_payer::int) pr FROM fct_user_month JOIN up USING (user_id)
        WHERE is_active AND month >= '2026-09-01' GROUP BY 1""").set_index("android").pr
    within = df.pivot(index="us", columns="android", values="pr")
    overall_gap = overall[True] / overall[False]
    within_gap = (within[True] / within[False]).min()
    assert overall_gap < 0.6 and within_gap > 0.75   # big overall gap, small within market


def test_g7_spend_moves_to_tiktok_influencer():
    r = q("""SELECT sum(spend_usd) FILTER (WHERE channel IN ('tiktok_ads','influencer') AND date < '2026-08-01') /
                    sum(spend_usd) FILTER (WHERE date < '2026-08-01') a,
                    sum(spend_usd) FILTER (WHERE channel IN ('tiktok_ads','influencer') AND date >= '2026-09-15') /
                    sum(spend_usd) FILTER (WHERE date >= '2026-09-15') b FROM marketing_spend""")
    assert abs(r["a"] - 0.20) < 0.03 and abs(r["b"] - 0.60) < 0.03


def test_g9_content_steady():
    df = db.query_df("""SELECT date_trunc('month', date) m, sum(watch_duration_sec) / sum(content_duration_sec) c
                        FROM content_views GROUP BY 1""")
    assert df.c.between(0.57, 0.63).all()
