from eval import run_eval, scoring


def test_tolerance():
    assert scoring.within_tolerance(101, 100, {"rel": 0.01})
    assert not scoring.within_tolerance(102, 100, {"rel": 0.01})
    assert scoring.within_tolerance(0.861, 0.86, {"abs": 0.01})
    assert not scoring.within_tolerance(None, 1, {"abs": 1})


def test_headline_value_is_authoritative():
    a = {"headline_value": 6836, "headline": "MAU was 9,999"}
    assert scoring.score_numeric(a, 6836, {"rel": 0.01})["pass"]
    a = {"headline_value": 1234, "headline": "MAU was 6,836"}
    assert not scoring.score_numeric(a, 6836, {"rel": 0.01})["pass"]


def test_numbers_parsed_from_headline_when_no_value():
    a = {"headline_value": None, "headline": "Android had 86.1% of Brazil sessions in November"}
    assert scoring.score_numeric(a, 0.8609, {"abs": 0.01})["pass"]
    a = {"headline_value": None, "headline": "Net revenue was $19,817.25 after correcting refunds"}
    assert scoring.score_numeric(a, 19817.25, {"rel": 0.01})["pass"]


def test_score_one_combines_numeric_and_judge():
    q = {"id": "X", "category": "dq_trap", "question": "q", "numeric": {"sql": "", "tol": {"rel": 0.01}},
         "judge": "flag the trap"}
    gt = {"questions": {"X": {"value": 100.0, "tol": {"rel": 0.01}, "facts": {}}}}
    res = {"answer": {"headline_value": 100.0, "headline": "", "answer_markdown": "md"}, "stop": "submitted",
           "tool_calls": 3, "sql_calls": 1}
    ok = run_eval.score_one(q, gt, res, judge_fn=lambda *a: {"pass": True, "score": 9, "failure_type": "none", "rationale": ""})
    bad = run_eval.score_one(q, gt, res, judge_fn=lambda *a: {"pass": False, "score": 2, "failure_type": "missed_dq_check", "rationale": "no flag"})
    assert ok["pass"] and not bad["pass"] and bad["failure_type"] == "missed_dq_check"
    none = run_eval.score_one(q, gt, {"answer": None, "stop": "api_error"}, judge_fn=lambda *a: {"pass": False, "score": 0, "failure_type": "other", "rationale": ""})
    assert none["failure_type"] == "loop_or_timeout"


def test_markdown_report_renders():
    rows = [{"id": "E01", "category": "simple", "question": "q", "pass": False, "failure_type": "wrong_number",
             "numeric": {"truth": 1.0, "candidates": [2.0], "pass": False}, "headline": "h",
             "agent": {"latency_s": 3, "tool_calls": 2, "usage": {"input_tokens": 10, "output_tokens": 5}}}]
    md = run_eval.to_markdown(run_eval.summarise(rows))
    assert "0 / 1 passed" in md and "Failure analysis" in md and "E01" in md


def test_eval_checkpoints_each_result_and_resumes(monkeypatch, tmp_path):
    import pytest
    monkeypatch.setattr(run_eval, "RESULTS", tmp_path)
    monkeypatch.setattr(run_eval, "PARTIAL", tmp_path / "partial.json")
    qs = [{"id": f"X{i}", "category": "simple", "question": f"q{i}"} for i in range(3)]
    monkeypatch.setattr(run_eval.GT, "load_questions", lambda: qs)
    monkeypatch.setattr(run_eval.GT, "build", lambda: {"questions": {}})
    asked = []

    class Agent:
        def run(self, question):
            asked.append(question)
            if question == "q2":
                raise KeyboardInterrupt            # the run dies part-way
            return type("R", (), {"to_dict": lambda self: {"answer": {"headline": "x"}, "stop": "submitted"}})()

    with pytest.raises(KeyboardInterrupt):
        run_eval.run(None, 1, agent_factory=Agent)
    import json
    assert sorted(r["id"] for r in json.loads((tmp_path / "partial.json").read_text())) == ["X0", "X1"]

    asked.clear()
    Agent.run = lambda self, q: (asked.append(q), type("R", (), {"to_dict": lambda s: {"answer": None, "stop": "x"}})())[1]
    summary = run_eval.run(None, 1, agent_factory=Agent, resume=True)
    assert asked == ["q2"] and [r["id"] for r in summary["results"]] == ["X0", "X1", "X2"]
