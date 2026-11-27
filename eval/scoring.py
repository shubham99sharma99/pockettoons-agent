"""Scoring: numeric tolerance check plus an LLM judge for behaviour.

The judge never sees the agent's prompt; it sees the question, the rubric,
reference facts computed from the database, and the agent's answer.
"""
from __future__ import annotations

import json
import os
import re

JUDGE_MODEL = os.environ.get("PT_JUDGE_MODEL", "claude-opus-5-5")
FAILURE_TYPES = [
    "none", "wrong_metric_definition", "wrong_join_or_filter", "missed_dq_check",
    "mix_effect_read_as_behaviour", "overclaimed_causality", "hallucinated_column_or_value",
    "did_not_state_assumption", "unhelpful_raw_table", "loop_or_timeout", "wrong_number", "other",
]


def within_tolerance(value: float | None, truth: float | None, tol: dict) -> bool:
    if value is None or truth is None:
        return False
    if "abs" in tol and abs(value - truth) <= tol["abs"]:
        return True
    if "rel" in tol and truth != 0 and abs(value - truth) / abs(truth) <= tol["rel"]:
        return True
    return False


_NUM = re.compile(r"-?\$?\d[\d,]*\.?\d*%?")


def _parse_num(tok: str) -> float | None:
    t = tok.replace("$", "").replace(",", "")
    pct = t.endswith("%")
    t = t.rstrip("%")
    try:
        v = float(t)
    except ValueError:
        return None
    return v / 100 if pct else v


def candidate_values(answer: dict | None) -> list[float]:
    """headline_value first; then numbers in the headline (percentages as fractions)."""
    if not answer:
        return []
    out = []
    hv = answer.get("headline_value")
    if isinstance(hv, (int, float)) and not isinstance(hv, bool):
        out.append(float(hv))
    for tok in _NUM.findall(answer.get("headline") or ""):
        v = _parse_num(tok)
        if v is not None:
            out.append(v)
    return out


def score_numeric(answer: dict | None, truth: float | None, tol: dict) -> dict:
    cands = candidate_values(answer)
    # headline_value is authoritative when present; otherwise any headline number may match,
    # also allowing a percentage given as 5.2 instead of 0.052
    pool = cands[:1] if (answer and isinstance(answer.get("headline_value"), (int, float))) else cands
    ok = any(within_tolerance(v, truth, tol) or within_tolerance(v / 100, truth, tol) for v in pool)
    return {"pass": ok, "truth": truth, "candidates": cands[:6], "tol": tol}


JUDGE_SCHEMA = {
    "type": "object",
    "properties": {
        "pass": {"type": "boolean"},
        "score": {"type": "integer", "description": "0-10"},
        "failure_type": {"type": "string", "enum": FAILURE_TYPES},
        "rationale": {"type": "string"},
    },
    "required": ["pass", "score", "failure_type", "rationale"],
    "additionalProperties": False,
}

JUDGE_SYSTEM = """You grade answers from an analytics agent against a rubric and reference facts
computed from the same database. Be strict about numbers (they must match the facts within the
rubric's tolerance or a clearly stated alternative definition) and about traps named in the rubric.
Do not reward length. If the answer passes, failure_type is "none"."""


def judge(question: str, rubric: str, facts: dict | None, answer_md: str, client=None) -> dict:
    import anthropic
    client = client or anthropic.Anthropic()
    prompt = (f"<question>\n{question}\n</question>\n\n<rubric>\n{rubric}\n</rubric>\n\n"
              f"<reference_facts>\n{json.dumps(facts or {}, indent=1, default=str)[:12000]}\n</reference_facts>\n\n"
              f"<agent_answer>\n{answer_md[:20000]}\n</agent_answer>\n\nGrade the answer.")
    resp = client.messages.create(
        model=JUDGE_MODEL, max_tokens=4000, system=JUDGE_SYSTEM,
        messages=[{"role": "user", "content": prompt}],
        output_config={"effort": "medium", "format": {"type": "json_schema", "schema": JUDGE_SCHEMA}},
    )
    if resp.stop_reason == "refusal":
        return {"pass": False, "score": 0, "failure_type": "other", "rationale": "judge refused"}
    text = next(b.text for b in resp.content if b.type == "text")
    return json.loads(text)
