"""Tools the agent can call. Each returns a JSON-serialisable dict.

Every query that touches data (run_sql, profile_column, run_dq_checks,
decompose_change) is recorded in the session's QueryLog and gets a query ID
(Q1, Q2, ...). The final answer must cite these IDs.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable

from . import db, semantic

VERDICTS = ["open", "ruled_out", "root_cause", "explained_by_root_cause", "data_issue", "not_testable"]
CONFIDENCE = ["high", "medium", "low"]
MAX_RESULT_CHARS = 14000


@dataclass
class Session:
    """Per-question state: evidence log, hypothesis register, counters."""
    log: db.QueryLog = field(default_factory=db.QueryLog)
    hypotheses: dict[str, dict] = field(default_factory=dict)
    tool_calls: int = 0
    sql_calls: int = 0
    final: dict | None = None
    citation_retries: int = 0


# --------------------------------------------------------------------------- #
# Tool implementations
# --------------------------------------------------------------------------- #
def get_schema(s: Session) -> dict:
    dd = semantic.data_dictionary()
    tables = []
    for name in sorted(db.ALLOWED_TABLES):
        cols = db.query_df(
            "SELECT column_name, data_type FROM information_schema.columns "
            f"WHERE table_schema = '{db.SCHEMA}' AND table_name = '{name}' ORDER BY ordinal_position")
        n = int(db.query_df(f"SELECT count(*) AS n FROM {db.SCHEMA}.{name}").n[0])
        desc = dd.get(name, {})
        tables.append({
            "table": name, "rows": n, "description": desc.get("description", ""),
            "columns": [{"name": r.column_name, "type": r.data_type,
                         "description": desc.get("columns", {}).get(r.column_name, "")}
                        for r in cols.itertuples()],
        })
    return {"schema": db.SCHEMA, "dialect": "duckdb", "tables": tables}


def get_metric_catalog(s: Session) -> dict:
    return semantic.metric_catalog()


def get_playbook(s: Session) -> dict:
    return {"playbook": semantic.playbook()}


def profile_column(s: Session, table: str, column: str) -> dict:
    if table not in db.ALLOWED_TABLES:
        return {"error": f"Unknown table {table}."}
    cols = set(db.query_df(
        "SELECT column_name FROM information_schema.columns "
        f"WHERE table_schema = '{db.SCHEMA}' AND table_name = '{table}'").column_name)
    if column not in cols:
        return {"error": f"Unknown column {table}.{column}. Columns: {sorted(cols)}"}
    stats_sql = (f'SELECT count(*) AS n, count(*) FILTER (WHERE "{column}" IS NULL) AS nulls, '
                 f'count(DISTINCT "{column}") AS distinct_values, min("{column}") AS min, '
                 f'max("{column}") AS max FROM {table}')
    top_sql = (f'SELECT "{column}" AS value, count(*) AS n FROM {table} '
               f'GROUP BY 1 ORDER BY 2 DESC LIMIT 50')
    st = db.execute(stats_sql)
    top = db.execute(top_sql)
    qid = s.log.add(stats_sql + ";\n" + top_sql, f"profile {table}.{column}", st, source="profile_column")
    r = dict(zip(st.columns, st.rows[0])) if st.rows else {}
    n = r.get("n") or 0
    return {"query_id": qid, "table": table, "column": column, "rows": n,
            "null_share": round((r.get("nulls") or 0) / n, 4) if n else None,
            "distinct_values": r.get("distinct_values"), "min": r.get("min"), "max": r.get("max"),
            "top_values": [{"value": v, "count": c} for v, c in top.rows]}


def run_sql(s: Session, query: str, purpose: str = "") -> dict:
    s.sql_calls += 1
    try:
        res = db.execute(query)
    except db.SQLGuardError as e:
        qid = s.log.add(query, purpose, None, error=f"rejected: {e}")
        return {"query_id": qid, "error": f"Query rejected by guardrail: {e}"}
    qid = s.log.add(query, purpose, res)
    if res.error:
        return {"query_id": qid, "error": res.error,
                "hint": "Fix the query and retry. Use get_schema for exact column names."}
    return {"query_id": qid, "columns": res.columns, "rows": res.rows, "row_count": res.row_count,
            "truncated": res.truncated, "elapsed_ms": res.elapsed_ms}


# --------------------------------------------------------------------------- #
# Data-quality checks (canned, generic)
# --------------------------------------------------------------------------- #
PKS = {"users": "user_id", "sessions": "session_id", "content_views": "view_id",
       "transactions": "txn_id", "content_catalog": "content_id"}
DATE_COLS = {"sessions": "date", "content_views": "date", "transactions": "date",
             "marketing_spend": "date", "users": "signup_date"}


def _check(s: Session, name: str, table: str, sql: str, judge: Callable[[list[dict]], tuple[str, str]]):
    res = db.execute(sql)
    qid = s.log.add(sql, f"dq: {name} ({table})", res, source="run_dq_checks")
    if res.error:
        return {"check": name, "table": table, "status": "error", "detail": res.error, "query_id": qid}
    rows = [dict(zip(res.columns, r)) for r in res.rows]
    status, detail = judge(rows)
    return {"check": name, "table": table, "status": status, "detail": detail, "query_id": qid,
            "evidence": rows[:24]}


def run_dq_checks(s: Session, tables: list[str] | None = None) -> dict:
    tables = [t for t in (tables or list(PKS) + ["marketing_spend"]) if t in db.ALLOWED_TABLES]
    out = []
    for t in tables:
        cols = db.query_df("SELECT column_name, data_type FROM information_schema.columns "
                           f"WHERE table_schema='{db.SCHEMA}' AND table_name='{t}'")
        # nulls
        parts = ", ".join(f'avg(("{c}" IS NULL)::int) AS "{c}"' for c in cols.column_name)
        out.append(_check(s, "null_share", t, f"SELECT {parts} FROM {t}", lambda rows: (
            "info", "Null share per column: " + json.dumps({k: round(v or 0, 4) for k, v in rows[0].items()
                                                              if (v or 0) > 0}) if rows else "")))
        if t in PKS:
            pk = PKS[t]
            out.append(_check(s, "duplicate_primary_key", t,
                              f"SELECT count(*) - count(DISTINCT {pk}) AS dup FROM {t}",
                              lambda rows: ("pass" if rows[0]["dup"] == 0 else "fail",
                                            f"{rows[0]['dup']} duplicate keys")))
        if t in DATE_COLS:
            dc = DATE_COLS[t]
            out.append(_check(s, "date_coverage", t, f"""
                WITH d AS (SELECT {dc} AS day, count(*) AS n FROM {t} GROUP BY 1),
                last AS (SELECT max(day) AS mx FROM d)
                SELECT min(day) AS first_day, max(day) AS last_day, count(*) AS days_with_rows,
                       date_diff('day', min(day), max(day)) + 1 AS days_spanned,
                       avg(n) FILTER (WHERE day > (SELECT mx FROM last) - 14) AS avg_rows_last_14d,
                       avg(n) FILTER (WHERE day <= (SELECT mx FROM last) - 14
                                        AND day > (SELECT mx FROM last) - 42) AS avg_rows_prior_28d
                FROM d""", lambda rows: (
                "warn" if rows[0]["days_with_rows"] < rows[0]["days_spanned"] or
                (rows[0]["avg_rows_prior_28d"] and rows[0]["avg_rows_last_14d"] <
                 0.7 * rows[0]["avg_rows_prior_28d"]) else "pass",
                "Gaps or a drop in the last 14 days indicate incomplete data" )))
        if t == "transactions":
            out.append(_check(s, "amount_sign_by_type_method_month", t, """
                SELECT type, payment_method, strftime(date, '%Y-%m') AS month, count(*) AS n,
                       count(*) FILTER (WHERE amount_usd > 0) AS positive,
                       count(*) FILTER (WHERE amount_usd < 0) AS negative,
                       count(*) FILTER (WHERE amount_usd = 0) AS zero
                FROM transactions WHERE status = 'success' GROUP BY 1, 2, 3 ORDER BY 1, 2, 3""",
                lambda rows: _sign_judge(rows)))
            out.append(_check(s, "distinct_amounts_by_type", t, """
                SELECT type, round(abs(amount_usd), 2) AS abs_amount, count(*) AS n
                FROM transactions GROUP BY 1, 2 ORDER BY 1, 3 DESC""",
                lambda rows: ("info", "Distinct absolute amounts per type (list prices, discounts, currency issues)")))
            out.append(_check(s, "duplicate_charges_5min", t, """
                SELECT strftime(a.date, '%Y-%m') AS month, count(*) AS duplicate_pairs,
                       (SELECT count(*) FROM transactions WHERE status='success' AND type<>'refund') AS successful_charges
                FROM transactions a JOIN transactions b
                  ON a.user_id = b.user_id AND a.type = b.type AND a.amount_usd = b.amount_usd
                 AND a.txn_id < b.txn_id AND a.status = 'success' AND b.status = 'success'
                 AND abs(epoch(b.created_at) - epoch(a.created_at)) <= 300
                WHERE a.type <> 'refund' GROUP BY 1 ORDER BY 1""",
                lambda rows: ("info" if sum(r["duplicate_pairs"] for r in rows) == 0 else "warn",
                              f"{sum(r['duplicate_pairs'] for r in rows)} duplicate charge pairs "
                              f"(same user/type/amount within 5 min)")))
            out.append(_check(s, "failure_rate_by_method_month", t, """
                SELECT payment_method, strftime(date, '%Y-%m') AS month,
                       round(avg((status = 'failed')::int), 4) AS failed_share, count(*) AS attempts
                FROM transactions WHERE type <> 'refund' GROUP BY 1, 2 ORDER BY 1, 2""",
                lambda rows: ("info", "Failed share of charge attempts")))
        if t in ("sessions", "content_views", "transactions"):
            out.append(_check(s, "orphan_user_ids", t,
                              f"SELECT count(*) AS orphans FROM {t} x LEFT JOIN users u USING (user_id) "
                              "WHERE u.user_id IS NULL",
                              lambda rows: ("pass" if rows[0]["orphans"] == 0 else "fail",
                                            f"{rows[0]['orphans']} rows without a matching user")))
        if t == "sessions":
            out.append(_check(s, "nonpositive_duration_and_before_signup", t, """
                SELECT strftime(s.date, '%Y-%m') AS month, count(*) AS sessions,
                       count(*) FILTER (WHERE duration_sec <= 0) AS nonpositive_duration,
                       count(*) FILTER (WHERE s.date < u.signup_date) AS before_signup
                FROM sessions s JOIN users u USING (user_id) GROUP BY 1 ORDER BY 1""",
                lambda rows: ("warn" if any(r["before_signup"] for r in rows) or
                              sum(r["nonpositive_duration"] for r in rows) > 0.01 * sum(r["sessions"] for r in rows)
                              else "pass", "Zero/negative durations and sessions dated before signup")))
        if t == "content_views":
            out.append(_check(s, "watch_vs_content_duration", t, """
                SELECT count(*) FILTER (WHERE watch_duration_sec > content_duration_sec) AS watch_gt_content,
                       count(*) FILTER (WHERE watch_duration_sec <= 0) AS nonpositive_watch, count(*) AS n
                FROM content_views""",
                lambda rows: ("pass" if rows[0]["watch_gt_content"] == 0 else "warn",
                              f"{rows[0]['watch_gt_content']} views longer than the episode")))
    fails = [c for c in out if c["status"] in ("fail", "warn")]
    return {"checks": out, "summary": f"{len(out)} checks, {len(fails)} warn/fail: " +
            ", ".join(f"{c['check']}({c['table']})" for c in fails)}


def _sign_judge(rows: list[dict]) -> tuple[str, str]:
    bad = []
    for r in rows:
        if r["type"] == "refund" and r["positive"] > 0:
            bad.append(f"refund/{r['payment_method']}/{r['month']}: {r['positive']} of {r['n']} positive")
        if r["type"] != "refund" and r["negative"] > 0:
            bad.append(f"{r['type']}/{r['payment_method']}/{r['month']}: {r['negative']} negative")
    if bad:
        return "fail", "Rows violating the documented sign convention: " + "; ".join(bad[:12])
    return "pass", "All charges positive and all refunds negative"


# --------------------------------------------------------------------------- #
# Decomposition: volume -> mix -> rate -> price (sequential substitution)
# --------------------------------------------------------------------------- #
SEGMENT_EXPR = {
    "country": "country",
    "acquisition_source": "acquisition_source",
    "market": "CASE WHEN country = 'US' THEN 'US' ELSE 'new_markets' END",
    "paid_vs_organic": "CASE WHEN acquisition_source IN ('organic','referral') THEN 'organic' ELSE 'paid' END",
}


def _segment_inputs(period: tuple[str, str], seg_expr: str, refund_handling: str) -> dict[str, dict]:
    amount = ("CASE WHEN type = 'refund' THEN -abs(amount_usd) ELSE amount_usd END"
              if refund_handling == "force_negative" else "amount_usd")
    a, b = period
    sql = f"""
    WITH act AS (
        SELECT user_id, date_trunc('month', date) AS m FROM sessions
        WHERE date BETWEEN DATE '{a}' AND DATE '{b}' GROUP BY 1, 2),
    pay AS (
        SELECT user_id, date_trunc('month', date) AS m,
               sum({amount}) AS rev,
               count(*) FILTER (WHERE type IN ('subscription','ppv')) AS charges
        FROM transactions WHERE status = 'success' AND date BETWEEN DATE '{a}' AND DATE '{b}'
        GROUP BY 1, 2),
    um AS (
        SELECT coalesce(act.user_id, pay.user_id) AS user_id, coalesce(act.m, pay.m) AS m,
               act.user_id IS NOT NULL AS active, coalesce(pay.charges, 0) > 0 AS payer,
               coalesce(pay.rev, 0) AS rev
        FROM act FULL OUTER JOIN pay ON act.user_id = pay.user_id AND act.m = pay.m)
    SELECT {seg_expr} AS seg, count(DISTINCT m) AS months,
           count(*) FILTER (WHERE active) AS mau_sum,
           count(*) FILTER (WHERE payer) AS payers_sum,
           sum(rev) AS rev_sum
    FROM um JOIN users USING (user_id) GROUP BY 1 ORDER BY 1"""
    df = db.query_df(sql)
    n_months = max(int(df.months.max()), 1)
    return {r.seg: {"mau": r.mau_sum / n_months, "payers": r.payers_sum / n_months,
                    "rev": r.rev_sum / n_months} for r in df.itertuples()}, sql


def _revenue(mau: float, share: dict, pr: dict, arppu: dict) -> float:
    return mau * sum(share[k] * pr[k] * arppu[k] for k in share)


def decompose_change(s: Session, metric: str = "net_revenue", period_a: list[str] | None = None,
                     period_b: list[str] | None = None, segment_col: str = "country",
                     refund_handling: str = "as_stored") -> dict:
    if metric != "net_revenue":
        return {"error": "Only metric='net_revenue' is supported (identity: MAU x share x payer rate x ARPPU)."}
    if segment_col not in SEGMENT_EXPR:
        return {"error": f"segment_col must be one of {sorted(SEGMENT_EXPR)}"}
    if refund_handling not in ("as_stored", "force_negative"):
        return {"error": "refund_handling must be 'as_stored' or 'force_negative'"}
    pa = tuple(period_a or ["2026-06-01", "2026-08-31"])
    pb = tuple(period_b or ["2026-09-01", "2026-11-30"])
    A, sql_a = _segment_inputs(pa, SEGMENT_EXPR[segment_col], refund_handling)
    B, sql_b = _segment_inputs(pb, SEGMENT_EXPR[segment_col], refund_handling)
    segs = sorted(set(A) | set(B))
    for d in (A, B):
        for k in segs:
            d.setdefault(k, {"mau": 0.0, "payers": 0.0, "rev": 0.0})

    def parts(d):
        mau = sum(v["mau"] for v in d.values())
        share = {k: (d[k]["mau"] / mau if mau else 0) for k in segs}
        pr = {k: (d[k]["payers"] / d[k]["mau"] if d[k]["mau"] else 0) for k in segs}
        arppu = {k: (d[k]["rev"] / d[k]["payers"] if d[k]["payers"] else 0) for k in segs}
        return mau, share, pr, arppu

    ma, sa, pra, aa = parts(A)
    mb, sb, prb, ab = parts(B)
    r0 = _revenue(ma, sa, pra, aa)
    r1 = _revenue(mb, sa, pra, aa)
    r2 = _revenue(mb, sb, pra, aa)
    r3 = _revenue(mb, sb, prb, aa)
    r4 = _revenue(mb, sb, prb, ab)
    actual_a = sum(v["rev"] for v in A.values())
    actual_b = sum(v["rev"] for v in B.values())

    def pts(x):
        return round(100 * x / r0, 2) if r0 else None

    # per-segment contribution to the rate step (holding the others at A)
    rate_by_seg = {k: round(100 * mb * sb[k] * (prb[k] - pra[k]) * aa[k] / r0, 2) if r0 else None for k in segs}
    qid = s.log.add(f"-- period A\n{sql_a}\n-- period B\n{sql_b}",
                    f"decompose net_revenue by {segment_col} ({refund_handling})", None,
                    source="decompose_change")
    return {
        "query_id": qid,
        "metric": metric, "segment_col": segment_col, "refund_handling": refund_handling,
        "period_a": pa, "period_b": pb,
        "order": "volume (MAU) -> mix (segment shares) -> rate (payer rate) -> price (ARPPU incl. refunds); residual",
        "monthly_avg_a": {"mau": round(ma, 1), "net_revenue": round(actual_a, 2)},
        "monthly_avg_b": {"mau": round(mb, 1), "net_revenue": round(actual_b, 2)},
        "change_pct": round(100 * (actual_b / actual_a - 1), 2) if actual_a else None,
        "bridge_points_index_a_100": {
            "volume": pts(r1 - r0), "mix": pts(r2 - r1), "rate": pts(r3 - r2), "price": pts(r4 - r3),
            "residual": pts((actual_b - actual_a) - (r4 - r0)),
        },
        "rate_step_by_segment_points": rate_by_seg,
        "segments": {k: {
            "mau_a": round(A[k]["mau"], 1), "mau_b": round(B[k]["mau"], 1),
            "share_a": round(sa[k], 4), "share_b": round(sb[k], 4),
            "payer_rate_a": round(pra[k], 4), "payer_rate_b": round(prb[k], 4),
            "arppu_a": round(aa[k], 2), "arppu_b": round(ab[k], 2),
            "net_revenue_a": round(A[k]["rev"], 2), "net_revenue_b": round(B[k]["rev"], 2),
        } for k in segs},
        "note": "Sequential substitution: the order changes how mix vs rate split by 1-2 points; it is fixed and reported.",
    }


# --------------------------------------------------------------------------- #
# Hypothesis register and final answer
# --------------------------------------------------------------------------- #
def log_hypothesis(s: Session, id: str, statement: str, verdict: str = "open", branch: str = "",
                   test: str = "", result: str = "", confidence: str = "low",
                   query_ids: list[str] | None = None) -> dict:
    if verdict not in VERDICTS:
        return {"error": f"verdict must be one of {VERDICTS}"}
    if confidence not in CONFIDENCE:
        return {"error": f"confidence must be one of {CONFIDENCE}"}
    unknown = [q for q in (query_ids or []) if q not in s.log.ids()]
    if unknown:
        return {"error": f"Unknown query IDs {unknown}. Cite IDs returned by your tools."}
    if verdict not in ("open", "not_testable") and not query_ids:
        return {"error": "A verdict other than open/not_testable needs at least one query ID as evidence."}
    s.hypotheses[id] = {"id": id, "branch": branch, "statement": statement, "test": test,
                        "result": result, "verdict": verdict, "confidence": confidence,
                        "query_ids": query_ids or []}
    counts: dict[str, int] = {}
    for h in s.hypotheses.values():
        counts[h["verdict"]] = counts.get(h["verdict"], 0) + 1
    return {"ok": True, "register_size": len(s.hypotheses), "verdict_counts": counts}


def submit_answer(s: Session, answer_markdown: str, headline: str, confidence: str,
                  query_ids: list[str], headline_value: float | None = None, unit: str = "",
                  assumptions: list[str] | None = None) -> dict:
    if confidence not in CONFIDENCE:
        return {"error": f"confidence must be one of {CONFIDENCE}"}
    unknown = [q for q in query_ids if q not in s.log.ids()]
    if unknown:
        return {"error": f"Unknown query IDs {unknown}. Only cite IDs your tools returned."}
    has_numbers = any(ch.isdigit() for ch in headline)
    if has_numbers and not (set(query_ids) & s.log.successful_ids()) and s.citation_retries < 1:
        s.citation_retries += 1
        return {"error": "Your headline states numbers but cites no successful query. Run the query "
                         "or cite the query IDs the numbers came from, then submit again."}
    s.final = {"answer_markdown": answer_markdown, "headline": headline, "headline_value": headline_value,
               "unit": unit, "confidence": confidence, "query_ids": query_ids,
               "assumptions": assumptions or []}
    return {"ok": True}


# --------------------------------------------------------------------------- #
# Tool specs for the Messages API
# --------------------------------------------------------------------------- #
def _spec(name, description, props=None, required=None):
    return {"name": name, "description": description,
            "input_schema": {"type": "object", "properties": props or {}, "required": required or [],
                             "additionalProperties": False}}


TOOL_SPECS = [
    _spec("get_schema", "List the analytics tables with columns, types, row counts and the data dictionary. Call this first for any new question."),
    _spec("get_metric_catalog", "Governed metric definitions (with reference SQL), segments, period definitions, product facts and analytical definitions such as retention and paywall metrics."),
    _spec("get_playbook", "Generic investigation playbook: MECE issue tree, hypothesis checklist and isolation techniques. Use for open-ended 'why' questions."),
    _spec("profile_column", "Profile one column: null share, distinct count, min/max and the top 50 values with counts.",
          {"table": {"type": "string"}, "column": {"type": "string"}}, ["table", "column"]),
    _spec("run_sql", "Run one read-only DuckDB SELECT (or WITH ... SELECT) over the analytics tables. Returns at most 200 rows plus the true row count and a query_id to cite. Errors come back so you can fix the query. Aggregate in SQL; do not pull raw rows.",
          {"query": {"type": "string", "description": "A single SELECT statement in DuckDB SQL."},
           "purpose": {"type": "string", "description": "One line: what this query tests or measures."}},
          ["query", "purpose"]),
    _spec("run_dq_checks", "Canned data-quality checks for the given tables: nulls, duplicate keys, date coverage, sign of amount_usd by type x payment_method x month, distinct amounts, duplicate charges within 5 minutes, failure rates, orphan keys, broken durations. Returns pass/warn/fail with the evidence query ID.",
          {"tables": {"type": "array", "items": {"type": "string"},
                      "description": "Tables to check; omit for all source tables."}}),
    _spec("decompose_change", "Bridge a change in monthly-average net revenue between two periods into volume (MAU), mix (segment shares), rate (payer rate) and price (ARPPU, net of refunds) by sequential substitution, in index points (period A = 100). Use refund_handling='force_negative' to recompute with every refund subtracting regardless of its stored sign.",
          {"metric": {"type": "string", "enum": ["net_revenue"]},
           "period_a": {"type": "array", "items": {"type": "string"}, "description": "[start, end] ISO dates"},
           "period_b": {"type": "array", "items": {"type": "string"}, "description": "[start, end] ISO dates"},
           "segment_col": {"type": "string", "enum": sorted(SEGMENT_EXPR)},
           "refund_handling": {"type": "string", "enum": ["as_stored", "force_negative"]}},
          ["period_a", "period_b", "segment_col"]),
    _spec("log_hypothesis", "Add or update a row in the hypothesis register. Verdicts other than open/not_testable need query IDs as evidence.",
          {"id": {"type": "string", "description": "e.g. A10, D1"},
           "branch": {"type": "string"}, "statement": {"type": "string"}, "test": {"type": "string"},
           "result": {"type": "string"}, "verdict": {"type": "string", "enum": VERDICTS},
           "confidence": {"type": "string", "enum": CONFIDENCE},
           "query_ids": {"type": "array", "items": {"type": "string"}}},
          ["id", "statement", "verdict"]),
    _spec("submit_answer", "Submit the final answer. Call exactly once, at the end. answer_markdown follows the required output format; headline is the one-sentence answer; headline_value is the single main number if the question asks for one (as a plain number: 0.085 for 8.5%, 12345.6 for $12,345.60), else null.",
          {"answer_markdown": {"type": "string"}, "headline": {"type": "string"},
           "headline_value": {"type": ["number", "null"]}, "unit": {"type": "string"},
           "confidence": {"type": "string", "enum": CONFIDENCE},
           "query_ids": {"type": "array", "items": {"type": "string"}},
           "assumptions": {"type": "array", "items": {"type": "string"}}},
          ["answer_markdown", "headline", "confidence", "query_ids"]),
]

DISPATCH: dict[str, Callable[..., dict]] = {
    "get_schema": get_schema, "get_metric_catalog": get_metric_catalog, "get_playbook": get_playbook,
    "profile_column": profile_column, "run_sql": run_sql, "run_dq_checks": run_dq_checks,
    "decompose_change": decompose_change, "log_hypothesis": log_hypothesis, "submit_answer": submit_answer,
}
SQL_TOOLS = {"run_sql"}


def validate_input(name: str, args: Any) -> str | None:
    """Manual validation (tool inputs are streamed eagerly, so the API does not validate)."""
    spec = next((t for t in TOOL_SPECS if t["name"] == name), None)
    if spec is None:
        return f"Unknown tool {name}"
    if not isinstance(args, dict):
        return "Tool input must be a JSON object."
    schema = spec["input_schema"]
    missing = [k for k in schema["required"] if k not in args]
    if missing:
        return f"Missing required fields: {missing}"
    extra = [k for k in args if k not in schema["properties"]]
    if extra:
        return f"Unknown fields: {extra}"
    for k, v in args.items():
        t = schema["properties"][k].get("type")
        types = t if isinstance(t, list) else [t]
        ok = any((tt == "string" and isinstance(v, str)) or (tt == "array" and isinstance(v, list)) or
                 (tt == "number" and isinstance(v, (int, float)) and not isinstance(v, bool)) or
                 (tt == "null" and v is None) or tt is None for tt in types)
        if not ok:
            return f"Field {k} must be {t}"
        enum = schema["properties"][k].get("enum")
        if enum and v not in enum:
            return f"Field {k} must be one of {enum}"
    return None


def call_tool(s: Session, name: str, args: dict) -> dict:
    s.tool_calls += 1
    err = validate_input(name, args)
    if err:
        return {"error": err}
    try:
        return DISPATCH[name](s, **args)
    except db.SQLGuardError as e:
        return {"error": str(e)}
    except Exception as e:  # noqa: BLE001 - surface to the model, never crash the loop
        return {"error": f"{type(e).__name__}: {str(e)[:400]}"}


def to_tool_content(result: dict) -> str:
    text = json.dumps(result, default=str)
    if len(text) > MAX_RESULT_CHARS:
        text = text[:MAX_RESULT_CHARS] + '... [truncated: aggregate further or select fewer columns]'
    return text
