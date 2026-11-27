"""Compute reference answers for the golden questions from the database.

    python -m eval.ground_truth      -> eval/ground_truth.json

Re-run whenever the data is regenerated, so the answer key is never stale.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import yaml

from agent import db

HERE = Path(__file__).resolve().parent
QUESTIONS = HERE / "questions.yaml"
OUT = HERE / "ground_truth.json"


def _scalar(sql: str):
    df = db.query_df(sql)
    v = df.iloc[0, 0]
    return None if v is None or (isinstance(v, float) and math.isnan(v)) else float(v)


def _table(sql: str) -> list[dict]:
    df = db.query_df(sql)
    return json.loads(df.to_json(orient="records", date_format="iso"))


def load_questions() -> list[dict]:
    return yaml.safe_load(QUESTIONS.read_text())["questions"]


def build() -> dict:
    target = db.target()
    if not db.motherduck_database() and db.db_path().resolve().is_relative_to(db.ROOT):
        target = db.db_path().resolve().relative_to(db.ROOT).as_posix()  # no machine paths in the repo
    out = {"db": target, "questions": {}}
    for q in load_questions():
        entry: dict = {}
        if "numeric" in q:
            entry["value"] = _scalar(q["numeric"]["sql"])
            entry["tol"] = q["numeric"]["tol"]
        if q.get("facts"):
            entry["facts"] = {k: _table(v) for k, v in q["facts"].items()}
        out["questions"][q["id"]] = entry
    return out


def main():
    gt = build()
    OUT.write_text(json.dumps(gt, indent=2, default=str))
    for qid, e in gt["questions"].items():
        print(qid, e.get("value"), list(e.get("facts", {}))[:3])
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
