"""Run the golden-question eval against the live agent and score it.

    python -m eval.run_eval                  # all questions
    python -m eval.run_eval --ids E01 E17    # a subset
    python -m eval.run_eval --concurrency 4
    python -m eval.run_eval --resume         # continue an interrupted run
    python -m eval.run_eval --rejudge eval/results/latest.json   # re-score stored answers only

Writes eval/results/run_<timestamp>.json, eval/results/latest.json and
eval/results.md (pass/fail table + failure analysis). Requires ANTHROPIC_API_KEY
(or NVIDIA_API_KEY with PT_PROVIDER=nim).
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv_lite import load_env  # noqa: E402

load_env(ROOT / ".env")  # before importing scoring/agent: provider and model are read at import

from eval import ground_truth as GT  # noqa: E402
from eval import scoring  # noqa: E402

RESULTS = ROOT / "eval" / "results"


def score_one(q: dict, gt: dict, result: dict, judge_fn=scoring.judge) -> dict:
    ans = result.get("answer")
    entry = gt["questions"].get(q["id"], {})
    out: dict = {"id": q["id"], "category": q["category"], "question": q["question"]}
    passes = []
    if "numeric" in q:
        num = scoring.score_numeric(ans, entry.get("value"), entry.get("tol", q["numeric"]["tol"]))
        out["numeric"] = num
        passes.append(num["pass"])
    api_failed = result.get("stop") == "api_error" and not ans
    if q.get("judge") and not api_failed:     # don't spend judge calls on infrastructure failures
        try:
            j = judge_fn(q["question"], q["judge"], entry.get("facts"), (ans or {}).get("answer_markdown", ""))
        except Exception as e:  # noqa: BLE001
            j = {"pass": False, "score": 0, "failure_type": "judge_error", "rationale": f"judge error: {e}"}
        out["judge"] = j
        passes.append(bool(j.get("pass")))
    if not ans:
        passes.append(False)
    out["pass"] = all(passes) if passes else False
    ft = (out.get("judge") or {}).get("failure_type")
    if not out["pass"]:
        if api_failed:
            ft = "api_error"
        elif ft == "judge_error":
            pass
        elif result.get("stop") in ("max_turns", "time_budget", "api_error") or not ans:
            ft = "loop_or_timeout"
        elif "numeric" in out and not out["numeric"]["pass"] and (not ft or ft == "none"):
            ft = "wrong_number"
    out["failure_type"] = ft if not out["pass"] else "none"
    out["agent"] = {k: result.get(k) for k in ("stop", "submitted", "tool_calls", "sql_calls", "turns",
                                              "latency_s", "usage", "error")}
    out["headline"] = (ans or {}).get("headline")
    out["headline_value"] = (ans or {}).get("headline_value")
    out["answer_markdown"] = (ans or {}).get("answer_markdown")
    return out


PARTIAL = RESULTS / "partial.json"
INFRA_FAILURES = ("api_error", "judge_error")   # not the agent's fault; shown separately


def _load_partial() -> dict[str, dict]:
    try:
        return {r["id"]: r for r in json.loads(PARTIAL.read_text())}
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def run(ids: list[str] | None, concurrency: int, agent_factory=None, judge_fn=scoring.judge,
        resume: bool = False) -> dict:
    """Run the golden questions. Each scored result is checkpointed to eval/results/partial.json
    as soon as it finishes, so an interrupted run keeps its work; resume=True skips those."""
    from agent.agent import AnalyticsAgent
    questions = [q for q in GT.load_questions() if not ids or q["id"] in ids]
    gt = GT.build()  # always recompute: the answer key can never be stale
    factory = agent_factory or (lambda: AnalyticsAgent())
    done = _load_partial() if resume else {}
    if not resume:
        PARTIAL.unlink(missing_ok=True)
    todo = [q for q in questions if q["id"] not in done]
    if done:
        print(f"resuming: {len(questions) - len(todo)} already done, {len(todo)} to run", flush=True)
    lock = threading.Lock()

    def checkpoint(scored):
        with lock:
            done[scored["id"]] = scored
            RESULTS.mkdir(parents=True, exist_ok=True)
            PARTIAL.write_text(json.dumps(list(done.values()), indent=1, default=str))

    def one(q):
        t0 = time.monotonic()
        try:
            res = factory().run(q["question"]).to_dict()
        except Exception as e:  # noqa: BLE001
            res = {"answer": None, "stop": "api_error", "error": str(e)}
        scored = score_one(q, gt, res, judge_fn)
        scored["wall_s"] = round(time.monotonic() - t0, 1)
        print(f"{q['id']} {'PASS' if scored['pass'] else 'FAIL'} ({scored['failure_type']}) "
              f"tools={res.get('tool_calls')} sql={res.get('sql_calls')} {scored['wall_s']}s", flush=True)
        checkpoint(scored)
        return scored

    with ThreadPoolExecutor(max_workers=concurrency) as ex:
        list(ex.map(one, todo))
    order = [q["id"] for q in questions]
    return summarise([done[i] for i in order if i in done])


def rejudge(source: Path, ids: list[str] | None = None, judge_fn=scoring.judge) -> dict:
    """Re-score stored answers (numeric check and judge) without re-running the agent.
    Use after a judge outage or a rubric fix; the agent's answers are untouched."""
    rows = json.loads(source.read_text())
    rows = rows["results"] if isinstance(rows, dict) else rows
    questions = {q["id"]: q for q in GT.load_questions()}
    gt = GT.build()
    out = []
    for r in rows:
        if r["id"] not in questions or (ids and r["id"] not in ids):
            out.append(r)
            continue
        ans = None if r.get("answer_markdown") is None and r.get("headline") is None else {
            k: r.get(k) for k in ("headline", "headline_value", "answer_markdown")}
        new = score_one(questions[r["id"]], gt, {"answer": ans, **(r.get("agent") or {})}, judge_fn)
        new["wall_s"] = r.get("wall_s")
        print(f"{r['id']} {'PASS' if new['pass'] else 'FAIL'} ({new['failure_type']})", flush=True)
        out.append(new)
    return summarise(out)


def summarise(rows: list[dict]) -> dict:
    from agent.agent import DEFAULT_MODEL, PROVIDER
    n = len(rows)
    passed = sum(r["pass"] for r in rows)
    by_cat: dict = {}
    for r in rows:
        c = by_cat.setdefault(r["category"], {"n": 0, "pass": 0})
        c["n"] += 1
        c["pass"] += int(r["pass"])
    fails: dict = {}
    for r in rows:
        if not r["pass"]:
            fails[r["failure_type"]] = fails.get(r["failure_type"], 0) + 1
    lat = [r["agent"].get("latency_s") for r in rows if r["agent"].get("latency_s")]
    tools = [r["agent"].get("tool_calls") for r in rows if r["agent"].get("tool_calls") is not None]
    toks_in = [r["agent"].get("usage", {}).get("input_tokens", 0) +
               r["agent"].get("usage", {}).get("cache_read_input_tokens", 0) for r in rows if r["agent"].get("usage")]
    toks_out = [r["agent"].get("usage", {}).get("output_tokens", 0) for r in rows if r["agent"].get("usage")]
    return {
        "run_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "model": DEFAULT_MODEL, "provider": PROVIDER, "judge_model": scoring.JUDGE_MODEL,
        "n": n, "passed": passed, "pass_rate": round(passed / n, 3) if n else 0,
        "by_category": by_cat, "failure_types": fails,
        "infra_failures": sum(fails.get(k, 0) for k in INFRA_FAILURES),
        "median_latency_s": statistics.median(lat) if lat else None,
        "median_tool_calls": statistics.median(tools) if tools else None,
        "median_input_tokens": statistics.median(toks_in) if toks_in else None,
        "median_output_tokens": statistics.median(toks_out) if toks_out else None,
        "results": rows,
    }


def to_markdown(summary: dict) -> str:
    L = [f"# Eval results", "",
         f"Run {summary['run_at']} · provider `{summary.get('provider', 'anthropic')}` · agent `{summary['model']}` · judge `{summary['judge_model']}`", "",
         f"**{summary['passed']} / {summary['n']} passed ({summary['pass_rate']:.0%}).** "
         f"Median latency {summary['median_latency_s']} s, median tool calls {summary['median_tool_calls']}, "
         f"median tokens in/out {summary['median_input_tokens']}/{summary['median_output_tokens']}.", ""]
    if summary.get("infra_failures"):
        L += [f"> **Warning:** {summary['infra_failures']} result(s) failed on API or judge errors, not agent "
              "behaviour. Re-run them (`--ids ...`) before reading the pass rate.", ""]
    L += [
         "| ID | Category | Question | Expected | Agent headline | Result | Failure type | Tools |",
         "|---|---|---|---|---|---|---|---|"]
    for r in summary["results"]:
        exp = r.get("numeric", {}).get("truth")
        exp = f"{exp:,.4g}" if isinstance(exp, (int, float)) else "rubric"
        head = (r.get("headline") or "").replace("|", "/").replace("\n", " ")[:140]
        L.append(f"| {r['id']} | {r['category']} | {r['question'][:70]} | {exp} | {head} | "
                 f"{'PASS' if r['pass'] else 'FAIL'} | {r['failure_type']} | {r['agent'].get('tool_calls')} |")
    L += ["", "## By category", "", "| Category | Passed |", "|---|---|"]
    for c, v in summary["by_category"].items():
        L.append(f"| {c} | {v['pass']}/{v['n']} |")
    L += ["", "## Failure analysis", ""]
    if not summary["failure_types"]:
        L.append("No failures.")
    for r in summary["results"]:
        if not r["pass"]:
            why = (r.get("judge") or {}).get("rationale") or ""
            num = r.get("numeric")
            if num and not num["pass"]:
                why = f"Numeric: expected {num['truth']}, got {num['candidates'][:3]}. " + why
            L.append(f"- **{r['id']}** ({r['failure_type']}): {why}")
    return "\n".join(L) + "\n"


def save(summary: dict) -> Path:
    RESULTS.mkdir(parents=True, exist_ok=True)
    stamp = summary["run_at"].replace(":", "").replace("-", "")
    p = RESULTS / f"run_{stamp}.json"
    p.write_text(json.dumps(summary, indent=2, default=str))
    (RESULTS / "latest.json").write_text(json.dumps(summary, indent=2, default=str))
    (ROOT / "eval" / "results.md").write_text(to_markdown(summary))
    return p


def main(argv=None):
    load_env(ROOT / ".env")
    ap = argparse.ArgumentParser()
    ap.add_argument("--ids", nargs="*")
    ap.add_argument("--concurrency", type=int, default=3)
    ap.add_argument("--resume", action="store_true",
                    help="skip questions already scored in eval/results/partial.json")
    ap.add_argument("--rejudge", metavar="RESULTS_JSON", type=Path,
                    help="re-score stored answers from a run_*.json / partial.json without re-running the agent")
    a = ap.parse_args(argv)
    if a.rejudge:
        p = save(rejudge(a.rejudge, a.ids))
        print(f"Re-scored. Wrote {p} and eval/results.md")
        return
    summary = run(a.ids, a.concurrency, resume=a.resume)
    p = save(summary)
    PARTIAL.unlink(missing_ok=True)
    print(f"\n{summary['passed']}/{summary['n']} passed. Wrote {p} and eval/results.md")


if __name__ == "__main__":
    main()
