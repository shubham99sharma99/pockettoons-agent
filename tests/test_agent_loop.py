"""End-to-end agent loop with a scripted LLM (no network)."""
import pytest

from agent.agent import AnalyticsAgent
from agent.report import render_markdown
from tests.fakes import ScriptedLLM, msg, text, tool

pytestmark = pytest.mark.needs_db


def test_simple_question_flow_counts_and_evidence():
    llm = ScriptedLLM([
        msg(text("Checking the schema."), tool("get_schema", {}, "t1")),
        msg(tool("run_sql", {"query": "SELECT count(DISTINCT user_id) AS mau FROM sessions "
                                      "WHERE date BETWEEN '2026-10-01' AND '2026-10-31'",
                             "purpose": "October MAU"}, "t2"),
            tool("run_dq_checks", {"tables": ["sessions"]}, "t3")),
        msg(tool("submit_answer", {"answer_markdown": "**Answer:** MAU was X (Q1)", "headline": "MAU in Oct",
                                   "headline_value": 1.0, "confidence": "high", "query_ids": ["Q1"]}, "t4")),
    ])
    events = []
    res = AnalyticsAgent(llm=llm).run("What was MAU in October 2026?", on_event=events.append)
    assert res.submitted and res.stop == "submitted"
    assert res.sql_calls == 1            # only run_sql counts as SQL (the sample's counter bug)
    assert res.tool_calls == 4
    assert res.evidence[0]["id"] == "Q1" and res.evidence[0]["row_count"] == 1
    types = [e["type"] for e in events]
    assert types[0] == "start" and types[-1] == "done" and "tool_result" in types and "text" in types
    # parallel tool calls answered in ONE user message
    last_user = llm.calls[-1]["messages"][-1]
    assert last_user["role"] == "user" and len(last_user["content"]) == 2
    md = render_markdown(res)
    assert "Appendix: queries run" in md and "Q1" in md


def test_budget_is_enforced():
    spam = [msg(tool("run_sql", {"query": "SELECT 1", "purpose": "spam"}, f"s{i}")) for i in range(6)]
    llm = ScriptedLLM(spam + [msg(text("stopping"), stop="end_turn")])
    res = AnalyticsAgent(llm=llm, max_sql_calls=3).run("loop forever")
    assert res.sql_calls == 3
    assert any("budget exhausted" in (t["error"] or "") for t in res.tool_trace)
    assert not res.submitted and res.answer["answer_markdown"] == "stopping"


def test_max_turns_stops_loop():
    llm = ScriptedLLM([msg(tool("get_schema", {}, f"g{i}")) for i in range(10)])
    res = AnalyticsAgent(llm=llm, max_turns=3).run("q")
    assert res.stop == "max_turns" and res.turns == 3


def test_refusal_and_api_error_are_reported():
    res = AnalyticsAgent(llm=ScriptedLLM([msg(text(""), stop="refusal")])).run("q")
    assert res.stop == "refusal" and res.answer is None

    class Boom:
        model = "x"

        def step(self, *a, **k):
            raise RuntimeError("network down")
    res = AnalyticsAgent(llm=Boom()).run("q")
    assert res.stop == "api_error"


def test_system_prompt_has_budget_and_format():
    from agent.agent import system_prompt
    p = system_prompt(40)
    assert "40 tool calls" in p and "**Answer:**" in p and "{max_tool_calls}" not in p
