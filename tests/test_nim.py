"""NVIDIA NIM provider: format translation, the shared agent loop, the judge and the switch."""
import importlib
import json
from types import SimpleNamespace as NS

import pytest

from agent import nim
from agent.nim import NimLLM, from_openai_response, to_openai_messages, to_openai_tools
from agent.tools import TOOL_SPECS


def completion(content=None, tool_calls=(), finish="stop", pt=50, ct=10):
    calls = [NS(id=cid, type="function", function=NS(name=n, arguments=a)) for cid, n, a in tool_calls]
    return NS(choices=[NS(message=NS(content=content, tool_calls=calls or None), finish_reason=finish)],
              usage=NS(prompt_tokens=pt, completion_tokens=ct))


class FakeOpenAI:
    """Records requests and replays scripted chat completions."""

    def __init__(self, script):
        self.script, self.requests = list(script), []
        self.chat = NS(completions=NS(create=self._create))

    def _create(self, **kw):
        self.requests.append(kw)
        return self.script.pop(0) if self.script else completion("done")


def test_tools_translate_to_openai_functions():
    out = to_openai_tools(TOOL_SPECS)
    assert len(out) == len(TOOL_SPECS)
    sql = next(t for t in out if t["function"]["name"] == "run_sql")
    assert sql["type"] == "function"
    assert sql["function"]["parameters"]["required"] == ["query", "purpose"]


def test_history_round_trip_keeps_tool_ids_and_results():
    history = [
        {"role": "user", "content": "How many users?"},
        {"role": "assistant", "content": [
            {"type": "text", "text": "Checking."},
            {"type": "tool_use", "id": "c1", "name": "run_sql", "input": {"query": "SELECT 1", "purpose": "p"}},
            {"type": "tool_use", "id": "c2", "name": "get_schema", "input": {}}]},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "c1", "content": '{"rows": [[1]]}', "is_error": False},
            {"type": "tool_result", "tool_use_id": "c2", "content": '{"tables": []}', "is_error": False}]},
    ]
    msgs = to_openai_messages("SYS", history)
    assert [m["role"] for m in msgs] == ["system", "user", "assistant", "tool", "tool"]
    a = msgs[2]
    assert a["content"] == "Checking."
    assert [c["id"] for c in a["tool_calls"]] == ["c1", "c2"]
    assert json.loads(a["tool_calls"][0]["function"]["arguments"]) == {"query": "SELECT 1", "purpose": "p"}
    assert msgs[3] == {"role": "tool", "tool_call_id": "c1", "content": '{"rows": [[1]]}'}


def test_response_parsing_tool_calls_think_tags_and_bad_json():
    r = from_openai_response(completion(
        "<think>private reasoning</think>Let me look.",
        [("c1", "run_sql", '{"query": "SELECT 1", "purpose": "x"}'), (None, "get_schema", "{not json")],
        finish="tool_calls", pt=120, ct=30))
    assert r.stop_reason == "tool_use"
    assert r.content[0] == {"type": "text", "text": "Let me look."}
    assert r.content[1]["input"] == {"query": "SELECT 1", "purpose": "x"}
    assert r.content[2]["id"].startswith("call_")          # missing id is generated
    assert r.content[2]["input"] == "{not json"             # passed through; the loop reports it
    assert (r.usage.input_tokens, r.usage.output_tokens) == (120, 30)
    assert from_openai_response(completion("hi", finish="length")).stop_reason == "max_tokens"
    assert from_openai_response(completion("hi")).stop_reason == "end_turn"


def test_missing_key_is_a_clear_error(monkeypatch):
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="NVIDIA_API_KEY"):
        NimLLM()


@pytest.mark.needs_db
def test_agent_loop_runs_end_to_end_on_nim():
    from agent.agent import AnalyticsAgent
    fake = FakeOpenAI([
        completion(None, [("a", "run_sql", json.dumps({"query": "SELECT count(*) AS n FROM users",
                                                         "purpose": "count users"}))], "tool_calls"),
        completion(None, [("b", "submit_answer", json.dumps({
            "answer_markdown": "**Answer:** there are users (Q1)", "headline": "users counted",
            "confidence": "high", "query_ids": ["Q1"]}))], "tool_calls"),
    ])
    res = AnalyticsAgent(llm=NimLLM(model="test/model", client=fake)).run("How many users?")
    assert res.submitted and res.stop == "submitted"
    assert res.model == "test/model" and res.sql_calls == 1
    assert res.usage["input_tokens"] == 100
    second = fake.requests[1]["messages"]                    # the tool result went back as a tool message
    tool_msg = next(m for m in second if m["role"] == "tool")
    assert tool_msg["tool_call_id"] == "a" and '"query_id": "Q1"' in tool_msg["content"]
    assert fake.requests[0]["tool_choice"] == "auto" and fake.requests[0]["model"] == "test/model"


@pytest.mark.needs_db
def test_uncited_answer_is_still_rejected_on_nim():
    from agent.agent import AnalyticsAgent
    fake = FakeOpenAI([
        completion(None, [("b", "submit_answer", json.dumps({
            "answer_markdown": "Revenue was $1,234,567.", "headline": "Revenue was $1,234,567",
            "confidence": "high", "query_ids": []}))], "tool_calls"),
        completion("I cannot cite that."),
    ])
    res = AnalyticsAgent(llm=NimLLM(model="m", client=fake)).run("Revenue?")
    assert not res.submitted
    rejected = next(m for m in fake.requests[1]["messages"] if m["role"] == "tool")
    assert "error" in json.loads(rejected["content"])


def test_judge_verdict_parsing():
    from eval.scoring import parse_verdict
    v = parse_verdict('<think>hmm</think>Here: {"pass": true, "score": 14, "failure_type": "bogus", '
                      '"rationale": "ok"} thanks')
    assert v == {"pass": True, "score": 10, "failure_type": "none", "rationale": "ok"}
    assert parse_verdict('{"pass": false, "score": "3", "failure_type": "wrong_number", "rationale": "x"}'
                         )["failure_type"] == "wrong_number"
    with pytest.raises(ValueError):
        parse_verdict("no json here")
    with pytest.raises(ValueError):
        parse_verdict('{"score": 5}')


def test_judge_uses_nim_when_configured(monkeypatch):
    import eval.scoring as scoring
    monkeypatch.setattr(scoring, "JUDGE_PROVIDER", "nim")
    fake = FakeOpenAI([completion('{"pass": true, "score": 8, "failure_type": "none", "rationale": "good"}')])
    v = scoring.judge("Q?", "rubric", {"f": 1}, "answer (Q1)", client=fake)
    assert v["pass"] and v["score"] == 8
    req = fake.requests[0]
    assert req["temperature"] == 0.0 and "JSON" in req["messages"][0]["content"]


def test_provider_switch(monkeypatch):
    import agent.agent as A
    try:
        monkeypatch.setenv("PT_PROVIDER", "nim")
        monkeypatch.delenv("PT_MODEL", raising=False)
        monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-test-not-real")
        importlib.reload(A)
        assert A.PROVIDER == "nim" and A.KEY_ENV == "NVIDIA_API_KEY"
        assert A.DEFAULT_MODEL == nim.NIM_DEFAULT_MODEL and A.llm_configured()
        assert isinstance(A.make_llm(), NimLLM)
        monkeypatch.setenv("PT_PROVIDER", "bogus")
        with pytest.raises(ValueError):
            importlib.reload(A)
    finally:
        monkeypatch.delenv("PT_PROVIDER", raising=False)
        importlib.reload(A)
    assert A.PROVIDER == "anthropic" and A.KEY_ENV == "ANTHROPIC_API_KEY"
    assert A.make_llm("nim").model == nim.NIM_DEFAULT_MODEL   # not the Claude default


def test_rate_limit_backs_off_then_gives_up(monkeypatch):
    class RateLimited(Exception):
        status_code = 429

    calls, slept = [], []

    def create(**kw):
        calls.append(kw)
        if len(calls) < 3:
            raise RateLimited("429")
        return completion("ok")

    llm = NimLLM(model="m", client=NS(chat=NS(completions=NS(create=create))), sleep=slept.append)
    assert llm.complete([{"role": "user", "content": "hi"}]).choices[0].message.content == "ok"
    assert slept == [30.0, 60.0]

    monkeypatch.setenv("PT_NIM_RATE_WAIT_S", "100")
    always = NimLLM(model="m", client=NS(chat=NS(completions=NS(create=lambda **k: (_ for _ in ()).throw(RateLimited())))),
                    sleep=lambda s: None)
    with pytest.raises(RateLimited):
        always.complete([{"role": "user", "content": "hi"}])

    class BadRequest(Exception):
        status_code = 400
    other = NimLLM(model="m", client=NS(chat=NS(completions=NS(create=lambda **k: (_ for _ in ()).throw(BadRequest())))),
                   sleep=lambda s: pytest.fail("must not retry non-429 errors"))
    with pytest.raises(BadRequest):
        other.complete([])


def test_single_offered_tool_is_forced():
    fake = FakeOpenAI([completion("ok")])
    sub = [t for t in TOOL_SPECS if t["name"] == "submit_answer"]
    NimLLM(model="m", client=fake).step("S", [{"role": "user", "content": "q"}], sub, lambda t: None)
    assert fake.requests[0]["tool_choice"] == {"type": "function", "function": {"name": "submit_answer"}}
