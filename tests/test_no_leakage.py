"""The agent must reason to the answer, not read it.

Fails if anything the agent can see (system prompt, playbook, semantic layer,
data dictionary, metric definitions, tool descriptions) names a planted effect,
or if agent code imports the generator config or the eval answer key.
"""
import json
import re
from pathlib import Path

from agent import semantic
from agent import tools as T
from agent.agent import system_prompt

ROOT = Path(__file__).resolve().parents[1]

FORBIDDEN = [
    r"2026-08-15", r"2026-10-01", r"\b5\s*(->|→|to)\s*8\b", r"free limit (was|is) \d", r"limit of \d",
    r"\b8 free episodes\b", r"\b5 free episodes\b", r"positive refunds?", r"refunds? (are|were) (stored|logged) as positive",
    r"sign (bug|flip)", r"billing integration", r"budget (moved|shift)", r"spend shift", r"mix effect.*android",
    r"android checkout is (fine|not broken)", r"root cause 1", r"RC1", r"RC2",
]


def visible_text() -> str:
    parts = [system_prompt(40), semantic.playbook(), json.dumps(semantic.metric_catalog()),
             json.dumps(semantic.data_dictionary()), json.dumps(T.TOOL_SPECS)]
    return "\n".join(parts)


def test_visible_text_has_no_planted_facts():
    text = visible_text()
    hits = [p for p in FORBIDDEN if re.search(p, text, flags=re.I)]
    assert not hits, f"agent-visible text leaks: {hits}"


def test_agent_code_does_not_import_ground_truth():
    for f in (ROOT / "agent").glob("*.py"):
        src = f.read_text()
        assert "import config" not in src and "data.config" not in src, f
        assert "eval" not in re.findall(r"^\s*(?:from|import)\s+(\w+)", src, flags=re.M), f
        assert "ground_truth" not in src and "questions.yaml" not in src, f
