"""Planner + ReAct loop over the analytics tools, on the Claude Messages API
(or NVIDIA NIM with PT_PROVIDER=nim; see agent/nim.py).

The loop is written by hand (not the SDK tool runner) because it needs to:
  * stream progress events (text, tool calls, results) to the API's SSE endpoint;
  * enforce tool-call and SQL budgets and stop cleanly;
  * keep a per-question evidence log and hypothesis register;
  * finish through a submit_answer tool that rejects uncited numbers.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Protocol

from . import tools as T
from .nim import NIM_DEFAULT_MODEL, NIM_KEY_ENV

PROMPTS = Path(__file__).resolve().parent / "prompts"
# LLM provider: "anthropic" (default, Claude) or "nim" (NVIDIA NIM / OpenAI-compatible, see agent/nim.py)
PROVIDER = os.environ.get("PT_PROVIDER", "anthropic").strip().lower()
if PROVIDER not in ("anthropic", "nim"):
    raise ValueError(f"PT_PROVIDER must be 'anthropic' or 'nim', got {PROVIDER!r}")
_DEFAULT_MODELS = {"anthropic": "claude-opus-5-5", "nim": NIM_DEFAULT_MODEL}
DEFAULT_MODEL = os.environ.get("PT_MODEL") or _DEFAULT_MODELS[PROVIDER]
KEY_ENV = {"anthropic": "ANTHROPIC_API_KEY", "nim": NIM_KEY_ENV}[PROVIDER]

DEFAULT_EFFORT = os.environ.get("PT_EFFORT", "high")
MAX_TOOL_CALLS = int(os.environ.get("PT_MAX_TOOL_CALLS", "40"))
MAX_SQL_CALLS = int(os.environ.get("PT_MAX_SQL_CALLS", "32"))
MAX_TURNS = int(os.environ.get("PT_MAX_TURNS", "45"))
# Wall-clock budget per question. After it, tools refuse and ask for submit_answer; at
# 1.5x the loop stops and returns the best text so far. Protects /ask and the eval from
# slow providers (NIM steps slow down as the conversation grows).
MAX_SECONDS = float(os.environ.get("PT_MAX_SECONDS", "900"))


def llm_configured() -> bool:
    """True when the configured provider's API key is present."""
    return bool(os.environ.get(KEY_ENV))

Event = dict[str, Any]
EventSink = Callable[[Event], None]


def system_prompt(max_tool_calls: int = MAX_TOOL_CALLS) -> str:
    return (PROMPTS / "system.md").read_text().replace("{max_tool_calls}", str(max_tool_calls))


class LLM(Protocol):
    model: str

    def step(self, system: str, messages: list, tools: list, on_text: Callable[[str], None]) -> Any:
        """Return a message object with .content (blocks), .stop_reason and .usage."""


class AnthropicLLM:
    """Claude via the official SDK: streaming, adaptive thinking, server-side refusal fallback."""

    def __init__(self, model: str = DEFAULT_MODEL, effort: str = DEFAULT_EFFORT, max_tokens: int = 32000):
        import anthropic
        self.client = anthropic.Anthropic()
        self.model = model
        self.effort = effort
        self.max_tokens = max_tokens

    def step(self, system, messages, tools, on_text):
        tool_defs = [{**t, "eager_input_streaming": True} for t in tools]
        with self.client.beta.messages.stream(
            model=self.model,
            max_tokens=self.max_tokens,
            system=system,
            messages=messages,
            tools=tool_defs,
            thinking={"type": "adaptive"},
            output_config={"effort": self.effort},
            cache_control={"type": "ephemeral"},
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        ) as stream:
            for ev in stream:
                if getattr(ev, "type", "") == "content_block_delta" and \
                        getattr(ev.delta, "type", "") == "text_delta":
                    on_text(ev.delta.text)
            return stream.get_final_message()


def make_llm(provider: str | None = None, model: str | None = None) -> LLM:
    provider = (provider or PROVIDER).lower()
    model = model or (DEFAULT_MODEL if provider == PROVIDER else _DEFAULT_MODELS[provider])
    if provider == "nim":
        from .nim import NimLLM
        return NimLLM(model=model)
    return AnthropicLLM(model=model)


@dataclass
class AgentResult:
    question: str
    model: str
    answer: dict | None
    submitted: bool
    stop: str
    tool_calls: int
    sql_calls: int
    turns: int
    latency_s: float
    usage: dict
    evidence: list[dict]
    hypotheses: list[dict]
    tool_trace: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return self.__dict__.copy()


def _usage_add(acc: dict, usage: Any) -> None:
    if usage is None:
        return
    for k in ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"):
        v = getattr(usage, k, None)
        if isinstance(v, int):
            acc[k] = acc.get(k, 0) + v


def _block_type(b: Any) -> str:
    return b.get("type") if isinstance(b, dict) else getattr(b, "type", "")


def _attr(b: Any, k: str) -> Any:
    return b.get(k) if isinstance(b, dict) else getattr(b, k, None)


class AnalyticsAgent:
    def __init__(self, llm: LLM | None = None, max_tool_calls: int = MAX_TOOL_CALLS,
                 max_sql_calls: int = MAX_SQL_CALLS, max_turns: int = MAX_TURNS,
                 max_seconds: float = MAX_SECONDS, clock: Callable[[], float] = time.monotonic):
        self.llm = llm or make_llm()
        self.max_tool_calls = max_tool_calls
        self.max_sql_calls = max_sql_calls
        self.max_turns = max_turns
        self.max_seconds = max_seconds
        self.clock = clock

    def run(self, question: str, on_event: EventSink | None = None) -> AgentResult:
        emit = on_event or (lambda e: None)
        s = T.Session()
        system = system_prompt(self.max_tool_calls)
        messages: list = [{"role": "user", "content": question}]
        usage: dict = {}
        trace: list[dict] = []
        t0 = self.clock()
        stop = "end_turn"
        last_text = ""
        turns = 0
        emit({"type": "start", "question": question, "model": self.llm.model})

        while turns < self.max_turns:
            if self.clock() - t0 > 1.5 * self.max_seconds:
                stop = "time_budget"
                emit({"type": "error", "message": "Time budget exceeded; returning the best answer so far."})
                break
            turns += 1
            buf: list[str] = []

            def on_text(t):
                buf.append(t)
                emit({"type": "text", "text": t})

            try:
                resp = self.llm.step(system, messages, T.TOOL_SPECS, on_text)
            except Exception as e:  # noqa: BLE001
                stop = "api_error"
                emit({"type": "error", "message": f"{type(e).__name__}: {str(e)[:300]}"})
                break
            _usage_add(usage, getattr(resp, "usage", None))
            content = list(resp.content)
            text_now = "".join(_attr(b, "text") or "" for b in content if _block_type(b) == "text")
            if text_now:
                last_text = text_now
            stop_reason = resp.stop_reason
            if stop_reason == "refusal":
                stop = "refusal"
                emit({"type": "error", "message": "The model declined this request."})
                break
            messages.append({"role": "assistant", "content": content})
            tool_uses = [b for b in content if _block_type(b) == "tool_use"]
            if stop_reason == "pause_turn":
                continue
            if not tool_uses:
                stop = stop_reason or "end_turn"
                break

            results = []
            for tu in tool_uses:
                name, args, tid = _attr(tu, "name"), _attr(tu, "input"), _attr(tu, "id")
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except json.JSONDecodeError:
                        args = None
                emit({"type": "tool_call", "id": tid, "name": name, "input": args})
                if name != "submit_answer" and self.clock() - t0 > self.max_seconds:
                    out = {"error": "Time budget exhausted. Call submit_answer now with what you have."}
                elif name in T.SQL_TOOLS and s.sql_calls >= self.max_sql_calls:
                    out = {"error": "SQL budget exhausted. Call submit_answer now with what you have."}
                elif s.tool_calls >= self.max_tool_calls and name != "submit_answer":
                    out = {"error": "Tool budget exhausted. Call submit_answer now with what you have."}
                else:
                    out = T.call_tool(s, name, args if isinstance(args, dict) else {"_invalid": args})
                trace.append({"tool": name, "input": args, "query_id": out.get("query_id"),
                              "error": out.get("error")})
                emit({"type": "tool_result", "id": tid, "name": name,
                      "query_id": out.get("query_id"), "error": out.get("error"),
                      "summary": _summarise(name, out)})
                results.append({"type": "tool_result", "tool_use_id": tid,
                                "content": T.to_tool_content(out), "is_error": bool(out.get("error"))})
            messages.append({"role": "user", "content": results})
            if s.final is not None:
                stop = "submitted"
                break
        else:
            stop = "max_turns"

        answer = s.final
        submitted = answer is not None
        if answer is None and last_text:
            answer = {"answer_markdown": last_text, "headline": last_text.strip().split("\n")[0][:300],
                      "headline_value": None, "unit": "", "confidence": "low", "query_ids": [],
                      "assumptions": ["Answer was not submitted through submit_answer."]}
        res = AgentResult(
            question=question, model=self.llm.model, answer=answer, submitted=submitted, stop=stop,
            tool_calls=s.tool_calls, sql_calls=s.sql_calls, turns=turns,
            latency_s=round(self.clock() - t0, 2), usage=usage,
            evidence=s.log.entries, hypotheses=list(s.hypotheses.values()), tool_trace=trace)
        emit({"type": "answer", "answer": answer, "submitted": submitted})
        emit({"type": "done", "stop": stop, "tool_calls": s.tool_calls, "sql_calls": s.sql_calls,
              "latency_s": res.latency_s, "usage": usage})
        return res


def _summarise(name: str, out: dict) -> str:
    if out.get("error"):
        return f"error: {out['error'][:200]}"
    if name == "run_sql":
        return f"{out.get('row_count')} rows" + (" (truncated)" if out.get("truncated") else "")
    if name == "run_dq_checks":
        return out.get("summary", "")[:300]
    if name == "decompose_change":
        return f"change {out.get('change_pct')}%; bridge {out.get('bridge_points_index_a_100')}"
    if name == "log_hypothesis":
        return f"register size {out.get('register_size')}"
    if name == "get_schema":
        return f"{len(out.get('tables', []))} tables"
    return "ok"
