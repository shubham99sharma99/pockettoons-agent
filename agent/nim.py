"""NVIDIA NIM (or any OpenAI-compatible endpoint) as an optional LLM provider.

The agent loop in agent.py speaks the Anthropic message format: assistant turns are
lists of `text` / `tool_use` blocks and tool results come back as `tool_result` blocks.
NimLLM translates that history to OpenAI chat-completions format on every step and
translates the reply back, so the loop, budgets, SQL guard and citation checks are
shared by both providers unchanged.

What the NIM path does not have: adaptive thinking, effort levels, prompt caching and
server-side refusal fallback (all Claude API features).

    PT_PROVIDER=nim  NVIDIA_API_KEY=...  [PT_NIM_MODEL=...]  [PT_NIM_BASE_URL=...]
"""
from __future__ import annotations

import json
import os
import re
import uuid
from types import SimpleNamespace as NS
from typing import Any

NIM_BASE_URL = os.environ.get("PT_NIM_BASE_URL", "https://integrate.api.nvidia.com/v1")
NIM_DEFAULT_MODEL = os.environ.get("PT_NIM_MODEL", "meta/llama-3.3-70b-instruct")
NIM_KEY_ENV = "NVIDIA_API_KEY"

_THINK = re.compile(r"<think>.*?</think>\s*", re.DOTALL)
_STOP = {"tool_calls": "tool_use", "function_call": "tool_use", "length": "max_tokens",
         "content_filter": "refusal"}


def _get(b: Any, k: str) -> Any:
    return b.get(k) if isinstance(b, dict) else getattr(b, k, None)


def to_openai_tools(tools: list[dict]) -> list[dict]:
    return [{"type": "function", "function": {
        "name": t["name"], "description": t.get("description", ""),
        "parameters": t.get("input_schema") or {"type": "object", "properties": {}}}} for t in tools]


def to_openai_messages(system: str, messages: list) -> list[dict]:
    """Anthropic-format history -> OpenAI chat messages."""
    out: list[dict] = [{"role": "system", "content": system}]
    for m in messages:
        role, content = m["role"], m["content"]
        if isinstance(content, str):
            out.append({"role": role, "content": content})
            continue
        if role == "assistant":
            text = "".join(_get(b, "text") or "" for b in content if _get(b, "type") == "text")
            calls = []
            for b in content:
                if _get(b, "type") != "tool_use":
                    continue
                args = _get(b, "input")
                calls.append({"id": _get(b, "id"), "type": "function", "function": {
                    "name": _get(b, "name"),
                    "arguments": args if isinstance(args, str) else json.dumps(args or {})}})
            msg: dict = {"role": "assistant", "content": text or None}
            if calls:
                msg["tool_calls"] = calls
            out.append(msg)
        else:  # user turn: tool results and/or text
            texts = []
            for b in content:
                t = _get(b, "type")
                if t == "tool_result":
                    c = _get(b, "content")
                    if not isinstance(c, str):
                        c = json.dumps(c, default=str)
                    out.append({"role": "tool", "tool_call_id": _get(b, "tool_use_id"), "content": c})
                elif t == "text":
                    texts.append(_get(b, "text") or "")
            if texts:
                out.append({"role": "user", "content": "\n".join(texts)})
    return out


def from_openai_response(resp: Any) -> NS:
    """OpenAI chat completion -> object shaped like an Anthropic message."""
    choice = resp.choices[0]
    m = choice.message
    blocks: list[dict] = []
    text = _THINK.sub("", m.content or "").strip()  # reasoning models may inline <think>
    if text:
        blocks.append({"type": "text", "text": text})
    for tc in (m.tool_calls or []):
        raw = tc.function.arguments or "{}"
        try:
            args: Any = json.loads(raw)
        except json.JSONDecodeError:
            args = raw  # the loop reports invalid arguments back to the model as a tool error
        blocks.append({"type": "tool_use", "id": tc.id or f"call_{uuid.uuid4().hex[:12]}",
                       "name": tc.function.name, "input": args})
    has_tools = any(b["type"] == "tool_use" for b in blocks)
    stop = "tool_use" if has_tools else _STOP.get(choice.finish_reason or "", "end_turn")
    u = getattr(resp, "usage", None)
    usage = NS(input_tokens=getattr(u, "prompt_tokens", 0) or 0,
               output_tokens=getattr(u, "completion_tokens", 0) or 0,
               cache_read_input_tokens=0, cache_creation_input_tokens=0)
    return NS(content=blocks, stop_reason=stop, usage=usage)


class NimLLM:
    """Hosted NVIDIA NIM through the OpenAI-compatible chat completions API."""

    def __init__(self, model: str | None = None, max_tokens: int = 4096, temperature: float | None = None,
                 client: Any = None):
        self.model = model or NIM_DEFAULT_MODEL
        self.max_tokens = int(os.environ.get("PT_NIM_MAX_TOKENS", max_tokens))
        self.temperature = float(os.environ.get("PT_NIM_TEMPERATURE", "0.2")) if temperature is None else temperature
        if client is None:
            import openai
            key = os.environ.get(NIM_KEY_ENV)
            if not key:
                raise RuntimeError(f"{NIM_KEY_ENV} is not set.")
            client = openai.OpenAI(base_url=NIM_BASE_URL, api_key=key, max_retries=4, timeout=180)
        self.client = client

    def complete(self, messages: list[dict], **kw) -> Any:
        return self.client.chat.completions.create(
            model=self.model, messages=messages, max_tokens=self.max_tokens,
            temperature=self.temperature, **kw)

    def step(self, system, messages, tools, on_text):
        resp = self.complete(to_openai_messages(system, messages),
                             tools=to_openai_tools(tools), tool_choice="auto")
        out = from_openai_response(resp)
        for b in out.content:
            if b["type"] == "text":
                on_text(b["text"])
        return out
