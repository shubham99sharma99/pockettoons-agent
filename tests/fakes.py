"""A scripted stand-in for the Claude API so the agent loop can be tested offline."""
from types import SimpleNamespace as NS


def text(t):
    return NS(type="text", text=t)


def tool(name, inp, tid=None):
    return NS(type="tool_use", name=name, input=inp, id=tid or f"tu_{name}_{id(inp)}")


def msg(*blocks, stop="tool_use"):
    return NS(content=list(blocks), stop_reason=stop,
              usage=NS(input_tokens=100, output_tokens=20, cache_read_input_tokens=0,
                       cache_creation_input_tokens=0))


class ScriptedLLM:
    model = "scripted-test-model"

    def __init__(self, script):
        self.script = list(script)
        self.calls = []

    def step(self, system, messages, tools, on_text):
        self.calls.append({"system": system, "messages": list(messages)})
        if not self.script:
            return msg(text("done"), stop="end_turn")
        m = self.script.pop(0)
        for b in m.content:
            if b.type == "text":
                on_text(b.text)
        return m
