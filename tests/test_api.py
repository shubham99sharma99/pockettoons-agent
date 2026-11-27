import json

import pytest
from fastapi.testclient import TestClient

from tests.fakes import ScriptedLLM, msg, tool

pytestmark = pytest.mark.needs_db


@pytest.fixture()
def client(monkeypatch):
    import api.main as m
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
