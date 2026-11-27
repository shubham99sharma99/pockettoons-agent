"""Render an AgentResult as a self-contained Markdown report (answer + evidence)."""
from __future__ import annotations

from .agent import AgentResult


def _cell(x) -> str:
    return str(x).replace("|", "\\|").replace("\n", " ")


def render_markdown(r: AgentResult | dict, include_sql: bool = True) -> str:
    d = r.to_dict() if isinstance(r, AgentResult) else r
    a = d.get("answer") or {}
    out = [a.get("answer_markdown") or "_No answer produced._", ""]
    if not d.get("submitted"):
        out.append("> Note: the agent did not submit through `submit_answer`; this is its last message.\n")
    hyps = d.get("hypotheses") or []
    if hyps:
        out += ["## Hypothesis register", "",
                "| ID | Branch | Hypothesis | Result | Verdict | Confidence | Evidence |",
                "|---|---|---|---|---|---|---|"]
        for h in hyps:
            out.append("| " + " | ".join(_cell(h.get(k, "")) for k in
                                         ("id", "branch", "statement", "result", "verdict", "confidence"))
                       + " | " + ", ".join(h.get("query_ids", [])) + " |")
        out.append("")
    out += ["## Run facts", "",
            f"- Model: `{d.get('model')}`; stop: `{d.get('stop')}`; turns: {d.get('turns')}",
            f"- Tool calls: {d.get('tool_calls')} (SQL: {d.get('sql_calls')}); latency: {d.get('latency_s')} s",
            f"- Tokens: {d.get('usage')}", ""]
    if include_sql and d.get("evidence"):
        out += ["## Appendix: queries run", ""]
        for e in d["evidence"]:
            status = f"error: {e['error']}" if e.get("error") else f"{e.get('row_count')} rows"
            out += [f"**{e['id']}** ({e.get('source')}) {e.get('purpose', '')} [{status}]", "",
                    "```sql", e["sql"].strip(), "```", ""]
    return "\n".join(out)
