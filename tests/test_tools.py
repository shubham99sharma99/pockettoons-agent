import pytest

from agent import db
from agent import tools as T

pytestmark = pytest.mark.needs_db


def test_every_tool_spec_has_a_dispatcher():
    assert {t["name"] for t in T.TOOL_SPECS} == set(T.DISPATCH)


def test_run_sql_assigns_query_ids_and_counts():
    s = T.Session()
    a = T.call_tool(s, "run_sql", {"query": "SELECT 1 AS x", "purpose": "t"})
    b = T.call_tool(s, "run_sql", {"query": "SELECT * FROM raw.users", "purpose": "t"})
    assert a["query_id"] == "Q1" and b["query_id"] == "Q2" and "guardrail" in b["error"]
    assert s.sql_calls == 2 and s.tool_calls == 2


def test_input_validation():
    s = T.Session()
    assert "Missing" in T.call_tool(s, "run_sql", {"purpose": "x"})["error"]
    assert "Unknown fields" in T.call_tool(s, "run_sql", {"query": "SELECT 1", "purpose": "x", "x": 1})["error"]
    assert "one of" in T.call_tool(s, "log_hypothesis", {"id": "A1", "statement": "s", "verdict": "maybe"})["error"]


def test_dq_checks_flag_sign_convention_generically():
    s = T.Session()
    out = T.run_dq_checks(s, ["transactions"])
    sign = next(c for c in out["checks"] if c["check"] == "amount_sign_by_type_method_month")
    assert sign["status"] == "fail" and "refund" in sign["detail"]
    assert all(c["query_id"] in s.log.ids() for c in out["checks"])


def test_decomposition_closes_and_matches_direct_revenue():
    s = T.Session()
    for mode, case in (("as_stored", "amount_usd"),
                       ("force_negative", "CASE WHEN type='refund' THEN -abs(amount_usd) ELSE amount_usd END")):
        d = T.decompose_change(s, period_a=["2026-06-01", "2026-08-31"], period_b=["2026-09-01", "2026-11-30"],
                               segment_col="country", refund_handling=mode)
        b = d["bridge_points_index_a_100"]
        assert abs(b["residual"]) < 0.01
        total = b["volume"] + b["mix"] + b["rate"] + b["price"]
        assert abs(total - d["change_pct"]) < 0.05
        q = db.query_df(f"SELECT sum({case}) FILTER (WHERE date >= '2026-09-01') / sum({case}) FILTER (WHERE date < '2026-09-01') - 1 AS c "
                        "FROM transactions WHERE status = 'success'").c[0]
        assert abs(100 * q - d["change_pct"]) < 0.05


def test_hypothesis_needs_real_evidence():
    s = T.Session()
    assert "Unknown query IDs" in T.log_hypothesis(s, "A1", "x", "ruled_out", query_ids=["Q9"])["error"]
    assert "needs at least one" in T.log_hypothesis(s, "A1", "x", "ruled_out")["error"]
    qid = T.run_sql(s, "SELECT 1", "t")["query_id"]
    assert T.log_hypothesis(s, "A1", "x", "ruled_out", query_ids=[qid], confidence="high")["ok"]


def test_submit_answer_rejects_uncited_numbers_once():
    s = T.Session()
    r = T.submit_answer(s, "md", "MAU was 6,836", "high", [])
    assert "cites no successful query" in r["error"]
    assert T.submit_answer(s, "md", "MAU was 6,836", "low", [])["ok"]
    assert T.submit_answer(T.Session(), "md", "x", "high", ["Q7"])["error"].startswith("Unknown query IDs")


def test_schema_and_catalog_are_model_sized():
    s = T.Session()
    assert len(T.to_tool_content(T.get_schema(s))) < T.MAX_RESULT_CHARS
    assert len(T.to_tool_content(T.get_metric_catalog(s))) < T.MAX_RESULT_CHARS
