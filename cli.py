"""Ask the PocketToons analytics agent a question from the command line.

    python cli.py "What was MAU in October 2026?"
    python cli.py --gm             # the GM's board question, saves outputs/investigation_raw.md
    python cli.py --quiet "..."    # final answer only
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from dotenv_lite import load_env

ROOT = Path(__file__).resolve().parent
GM_QUESTION = ("MAU is up 20% QoQ but revenue is flat. Board meeting Thursday. "
               "Figure out what's happening and what we should do about it.")


def main(argv=None) -> int:
    load_env(ROOT / ".env")
    ap = argparse.ArgumentParser()
    ap.add_argument("question", nargs="?")
    ap.add_argument("--gm", action="store_true", help="run the GM investigation question")
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--out", help="write the Markdown report here")
    ap.add_argument("--json", help="write the full result JSON here")
    args = ap.parse_args(argv)
    q = GM_QUESTION if args.gm else args.question
    if not q:
        ap.error("give a question or --gm")

    from agent.agent import AnalyticsAgent
    from agent.report import render_markdown

    def show(e):
        if args.quiet:
            return
        t = e["type"]
        if t == "text":
            sys.stdout.write(e["text"]); sys.stdout.flush()
        elif t == "tool_call":
            inp = json.dumps(e["input"])[:160]
            print(f"\n  -> {e['name']} {inp}")
        elif t == "tool_result":
            print(f"  <- {e.get('query_id') or ''} {e['summary']}")
        elif t == "error":
            print(f"\n[error] {e['message']}")

    res = AnalyticsAgent().run(q, on_event=show)
    md = render_markdown(res)
    print("\n\n" + "=" * 80 + "\n" + (res.answer or {}).get("answer_markdown", "(no answer)"))
    out = args.out or (str(ROOT / "outputs" / "investigation_raw.md") if args.gm else None)
    if out:
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        Path(out).write_text(md)
        print(f"\nsaved {out}")
    if args.json or args.gm:
        jp = args.json or str(ROOT / "outputs" / "investigation_raw.json")
        Path(jp).write_text(json.dumps(res.to_dict(), indent=2, default=str))
    return 0 if res.answer else 1


if __name__ == "__main__":
    raise SystemExit(main())
