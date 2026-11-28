"""Server-side data for the Dashboard and ER-diagram pages.

These are fixed, trusted queries (not user SQL), cached for the life of the process
because the analytics database is read-only.
"""
from __future__ import annotations

from functools import lru_cache

from agent import db


def _rows(sql: str) -> list[dict]:
    df = db.query_df(sql)
    df = df.astype(object).where(df.notna(), None)   # NaN is not valid JSON
    return [{k: None if v is None else db._jsonable(v) for k, v in r.items()} for r in df.to_dict(orient="records")]


MONTHLY = """
WITH s AS (SELECT date_trunc('month', date) AS m, COUNT(DISTINCT user_id) AS mau FROM sessions GROUP BY 1),
t AS (
  SELECT date_trunc('month', date) AS m,
    SUM(amount_usd) FILTER (WHERE status = 'success' AND type = 'subscription') AS subscription_revenue,
    SUM(amount_usd) FILTER (WHERE status = 'success' AND type = 'ppv') AS ppv_revenue,
    -- refunds always reduce revenue, whatever sign they were stored with
    -SUM(ABS(amount_usd)) FILTER (WHERE status = 'success' AND type = 'refund') AS refunds,
    COUNT(DISTINCT user_id) FILTER (WHERE status = 'success' AND type IN ('subscription', 'ppv')) AS paying_users,
    COUNT(*) FILTER (WHERE type = 'refund') AS refund_rows,
    COUNT(*) FILTER (WHERE type = 'refund' AND amount_usd > 0) AS refunds_stored_positive,
    COUNT(*) FILTER (WHERE status = 'failed' AND type IN ('subscription', 'ppv')) AS failed_charges,
    COUNT(*) FILTER (WHERE type IN ('subscription', 'ppv')) AS charge_attempts
  FROM transactions GROUP BY 1),
u AS (SELECT date_trunc('month', signup_date) AS m, COUNT(*) AS new_users FROM users GROUP BY 1)
SELECT strftime(m, '%Y-%m') AS month, mau, paying_users, new_users,
  paying_users * 1.0 / mau AS payer_rate,
  subscription_revenue, ppv_revenue, refunds,
  subscription_revenue + ppv_revenue AS gross_revenue,
  subscription_revenue + ppv_revenue + refunds AS net_revenue,
  (subscription_revenue + ppv_revenue + refunds) / paying_users AS arppu,
  refund_rows, refunds_stored_positive,
  failed_charges * 1.0 / charge_attempts AS charge_failure_rate
FROM s LEFT JOIN t USING (m) LEFT JOIN u USING (m) ORDER BY m
"""

DAILY = """
SELECT strftime(date, '%Y-%m-%d') AS date, COUNT(DISTINCT user_id) AS dau FROM sessions GROUP BY 1 ORDER BY 1
"""

CHANNELS = """
WITH last AS (SELECT date_trunc('month', MAX(date)) AS m FROM sessions),
sp AS (SELECT channel, SUM(spend_usd) AS spend FROM marketing_spend, last
       WHERE date_trunc('month', date) = last.m GROUP BY 1),
su AS (SELECT acquisition_source AS channel, COUNT(*) AS signups FROM users, last
       WHERE date_trunc('month', signup_date) = last.m GROUP BY 1)
SELECT su.channel, su.signups, sp.spend, sp.spend / su.signups AS cost_per_signup
FROM su LEFT JOIN sp USING (channel) ORDER BY su.signups DESC
"""

PLATFORMS = """
WITH last AS (SELECT date_trunc('month', MAX(date)) AS m FROM sessions)
SELECT platform, COUNT(*) AS sessions, COUNT(DISTINCT user_id) AS users
FROM sessions, last WHERE date_trunc('month', date) = last.m GROUP BY 1 ORDER BY 2 DESC
"""


@lru_cache(maxsize=1)
def dashboard() -> dict:
    monthly = _rows(MONTHLY)
    return {
        "monthly": monthly,
        "daily": _rows(DAILY),
        "channels": _rows(CHANNELS),
        "platforms": _rows(PLATFORMS),
        "latest_month": monthly[-1]["month"] if monthly else None,
        "definitions": {
            "mau": "Distinct users with a session in the month.",
            "paying_users": "Distinct users with a successful subscription or PPV charge in the month.",
            "payer_rate": "Paying users / MAU.",
            "net_revenue": "Successful subscription + PPV charges minus refunds. Refunds are always "
                           "subtracted, whichever sign they were stored with.",
            "arppu": "Net revenue / paying users.",
            "new_users": "Users whose signup date falls in the month.",
            "cost_per_signup": "Marketing spend on the channel in the month / signups from that channel.",
            "charge_failure_rate": "Failed subscription + PPV charges / all charge attempts.",
        },
    }


# --------------------------------------------------------------------------- #
# ER diagram
# --------------------------------------------------------------------------- #
LAYERS = {
    "users": "staging", "sessions": "staging", "transactions": "staging", "content_views": "staging",
    "content_catalog": "staging", "marketing_spend": "staging",
    "fct_transactions": "mart", "fct_user_day": "mart", "fct_user_month": "mart",
}
PRIMARY_KEYS = {
    "users": ["user_id"], "sessions": ["session_id"], "transactions": ["txn_id"],
    "content_views": ["view_id"], "content_catalog": ["content_id"], "marketing_spend": ["date", "channel"],
    "fct_transactions": ["txn_id"], "fct_user_day": ["user_id", "date"], "fct_user_month": ["user_id", "month"],
}
# (child table, child column, parent table, parent column, cardinality, kind)
RELATIONS = [
    ("sessions", "user_id", "users", "user_id", "many-to-one", "foreign key"),
    ("transactions", "user_id", "users", "user_id", "many-to-one", "foreign key"),
    ("content_views", "user_id", "users", "user_id", "many-to-one", "foreign key"),
    ("content_views", "content_id", "content_catalog", "content_id", "many-to-one", "foreign key"),
    ("fct_user_day", "user_id", "users", "user_id", "many-to-one", "foreign key"),
    ("fct_user_month", "user_id", "users", "user_id", "many-to-one", "foreign key"),
    ("fct_transactions", "user_id", "users", "user_id", "many-to-one", "foreign key"),
    ("fct_transactions", "txn_id", "transactions", "txn_id", "one-to-one", "foreign key"),
    ("marketing_spend", "channel", "users", "acquisition_source", "many-to-many", "logical (same values)"),
]
LINEAGE = {   # dbt ref() inputs of each mart model
    "fct_transactions": ["transactions", "users"],
    "fct_user_day": ["sessions", "content_views", "content_catalog", "transactions", "users"],
    "fct_user_month": ["sessions", "transactions", "users"],
}


@lru_cache(maxsize=1)
def relations() -> dict:
    out = []
    for child, ccol, parent, pcol, card, kind in RELATIONS:
        if kind == "foreign key":
            orphans = int(db.query_df(
                f"SELECT COUNT(*) AS n FROM {child} c LEFT JOIN (SELECT DISTINCT {pcol} AS k FROM {parent}) p "
                f"ON c.{ccol} = p.k WHERE c.{ccol} IS NOT NULL AND p.k IS NULL").n[0])
            check = {"orphan_rows": orphans}
        else:
            vals = db.query_df(
                f"SELECT (SELECT COUNT(DISTINCT {ccol}) FROM {child}) AS a, "
                f"(SELECT COUNT(DISTINCT {ccol}) FROM {child} WHERE {ccol} NOT IN "
                f"(SELECT DISTINCT {pcol} FROM {parent})) AS unmatched")
            check = {"distinct_values": int(vals.a[0]), "unmatched_values": int(vals.unmatched[0])}
        out.append({"from": child, "from_column": ccol, "to": parent, "to_column": pcol,
                    "cardinality": card, "kind": kind, **check})
    return {"layers": LAYERS, "primary_keys": PRIMARY_KEYS, "relations": out, "lineage": LINEAGE}
