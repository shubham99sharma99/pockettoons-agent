import json

import pytest
from fastapi.testclient import TestClient

from tests.fakes import ScriptedLLM, msg, tool

pytestmark = pytest.mark.needs_db


@pytest.fixture()
def client(monkeypatch, tmp_path):
    import api.main as m
    monkeypatch.setenv("PT_AUDIT_DB", str(tmp_path / "audit.sqlite"))
    monkeypatch.delenv("PT_EXPOSE_AUDIT", raising=False)
    monkeypatch.delenv("EVAL_ADMIN_TOKEN", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")
    monkeypatch.setenv("NVIDIA_API_KEY", "test-key-not-real")
    from agent.agent import AnalyticsAgent

    def fake_agent():
        return AnalyticsAgent(llm=ScriptedLLM([
            msg(tool("run_sql", {"query": "SELECT count(*) AS n FROM users", "purpose": "count"}, "a")),
            msg(tool("submit_answer", {"answer_markdown": "**Answer:** n (Q1)", "headline": "users",
                                       "confidence": "high", "query_ids": ["Q1"]}, "b")),
        ]))
    monkeypatch.setattr(m, "make_agent", fake_agent)
    m.ask_limiter.hits.clear(); m.ask_limiter.day_hits.clear()
    return TestClient(m.app)


def test_health_schema_metrics(client):
    assert client.get("/health").json()["status"] == "ok"
    tables = {t["table"] for t in client.get("/schema").json()["tables"]}
    assert {"users", "transactions", "fct_user_month"} <= tables
    names = {m["name"] for m in client.get("/metrics").json()["metrics"]}
    assert {"mau", "net_revenue", "payer_rate"} <= names


def test_query_guard(client):
    assert client.post("/query", json={"sql": "SELECT 1 AS x"}).json()["rows"] == [[1]]
    r = client.post("/query", json={"sql": "DROP TABLE users"})
    assert r.status_code == 400


def test_ask_streams_sse(client):
    with client.stream("POST", "/ask", json={"question": "How many users?"}) as r:
        assert r.status_code == 200
        body = "".join(r.iter_text())
    events = [json.loads(line[5:]) for line in body.splitlines() if line.startswith("data:") and line[5:].strip() != "{}"]
    types = [e["type"] for e in events]
    assert types[0] == "start" and "tool_result" in types and types[-1] == "done"
    ans = next(e for e in events if e["type"] == "answer")
    assert ans["submitted"] and ans["answer"]["query_ids"] == ["Q1"]


def test_ask_rate_limited(client):
    import api.main as m
    m.ask_limiter.per_window = 1
    try:
        with client.stream("POST", "/ask", json={"question": "first"}) as r:
            "".join(r.iter_text())
        assert client.post("/ask", json={"question": "second"}).status_code == 429
    finally:
        m.ask_limiter.per_window = 4


def test_ask_without_key(client, monkeypatch):
    from agent.agent import KEY_ENV
    monkeypatch.delenv(KEY_ENV)                       # the active provider's key
    r = client.post("/ask", json={"question": "anything"})
    assert r.status_code == 503 and KEY_ENV in r.json()["detail"]


def test_eval_results_endpoint(client):
    assert "available" in client.get("/eval/results").json()


def test_cors_allows_only_configured_origin(client):
    ok = client.options("/health", headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": "GET"})
    bad = client.options("/health", headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"})
    assert ok.headers.get("access-control-allow-origin") == "http://localhost:3000"
    assert "access-control-allow-origin" not in bad.headers


def test_golden_questions_hidden_unless_enabled(client, monkeypatch):
    monkeypatch.delenv("PT_EXPOSE_GOLDEN", raising=False)
    assert client.get("/eval/questions").status_code == 404
    monkeypatch.setenv("PT_EXPOSE_GOLDEN", "1")
    qs = client.get("/eval/questions").json()["questions"]
    assert len(qs) >= 20 and qs[0]["id"] == "E01" and qs[0]["sql"]
    # every reference query passes the same guard the agent and SQL page use
    import api.main as m
    m.query_limiter.hits.clear()
    for q in qs[:5]:
        if q["sql"]:
            assert client.post("/query", json={"sql": q["sql"]}).status_code == 200, q["id"]


def test_dashboard_numbers_match_metric_definitions(client):
    d = client.get("/dashboard").json()
    oct_ = next(r for r in d["monthly"] if r["month"] == "2026-10")
    from agent import db
    mau = int(db.query_df("SELECT COUNT(DISTINCT user_id) AS n FROM sessions "
                          "WHERE date_trunc('month', date) = DATE '2026-10-01'").n[0])
    assert oct_["mau"] == mau
    assert oct_["refunds"] <= 0 and oct_["net_revenue"] == pytest.approx(oct_["gross_revenue"] + oct_["refunds"])
    assert abs(oct_["payer_rate"] - oct_["paying_users"] / oct_["mau"]) < 1e-6
    assert len(d["daily"]) > 100 and d["channels"] and d["platforms"]


def test_relations_keys_exist_and_hold(client):
    r = client.get("/schema/relations").json()
    cols = {t["table"]: {c["name"] for c in t["columns"]} for t in client.get("/schema").json()["tables"]}
    for rel in r["relations"]:
        assert rel["from_column"] in cols[rel["from"]] and rel["to_column"] in cols[rel["to"]]
        assert rel.get("orphan_rows", 0) == 0 and rel.get("unmatched_values", 0) == 0
    for t, pk in r["primary_keys"].items():
        assert set(pk) <= cols[t]


def test_audit_log_records_queries_and_asks(client, monkeypatch):
    assert client.get("/audit").status_code == 404
    client.post("/query", json={"sql": "SELECT 1 AS x"})
    client.post("/query", json={"sql": "DROP TABLE users"})
    with client.stream("POST", "/ask", json={"question": "How many users?"}) as resp:
        for _ in resp.iter_lines():
            pass
    import time
    from api import audit
    for _ in range(50):   # the ask row is written by the agent thread when the run ends
        if audit.read(kind="ask")["events"]:
            break
        time.sleep(0.05)
    monkeypatch.setenv("PT_EXPOSE_AUDIT", "1")
    ev = client.get("/audit").json()["events"]
    kinds = [(e["kind"], e["status"]) for e in ev]
    assert ("query", "ok") in kinds and ("query", "rejected") in kinds and ("ask", "ok") in kinds
    ask = next(e for e in ev if e["kind"] == "ask")
    assert ask["summary"] == "How many users?" and ask["detail"]["queries"][0]["sql"].startswith("SELECT count")
    assert all(e["client"] is None or len(e["client"]) == 10 for e in ev)   # IPs are hashed
    assert client.get("/audit", params={"kind": "query", "q": "DROP"}).json()["events"][0]["status"] == "rejected"
