"""Audit log: who asked what, which SQL ran, and how it ended.

Stored in a small SQLite file (PT_AUDIT_DB, default data/audit.sqlite), separate from
the read-only analytics database. Client IPs are stored only as a salted hash.
Reading the log is off unless PT_EXPOSE_AUDIT=1 or the caller sends EVAL_ADMIN_TOKEN,
because it holds other people's questions.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_lock = threading.Lock()
MAX_ROWS = int(os.environ.get("PT_AUDIT_MAX_ROWS", "20000"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS audit (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts REAL NOT NULL,
  kind TEXT NOT NULL,          -- ask | query | eval_run
  client TEXT,                 -- salted hash of the client IP
  status TEXT NOT NULL,        -- ok | error | rate_limited | rejected | <agent stop reason>
  summary TEXT,                -- the question, or the SQL
  latency_ms INTEGER,
  detail TEXT                  -- JSON: agent queries, headline, error, row count...
);
CREATE INDEX IF NOT EXISTS audit_ts ON audit(ts);
"""


def db_path() -> Path:
    return Path(os.environ.get("PT_AUDIT_DB", ROOT / "data" / "audit.sqlite"))


def _connect() -> sqlite3.Connection:
    p = db_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(p, timeout=5)
    con.executescript(SCHEMA)
    return con


def hash_client(ip: str) -> str:
    salt = os.environ.get("PT_AUDIT_SALT", "pockettoons-audit")
    return hashlib.sha256(f"{salt}:{ip}".encode()).hexdigest()[:10]


def record(kind: str, status: str, summary: str | None = None, client_ip: str | None = None,
           latency_ms: int | None = None, **detail) -> None:
    """Write one event. Never raises: auditing must not break the request."""
    try:
        with _lock, _connect() as con:
            con.execute("INSERT INTO audit (ts, kind, client, status, summary, latency_ms, detail) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (time.time(), kind, hash_client(client_ip) if client_ip else None, status,
                         (summary or "")[:8000], latency_ms, json.dumps(detail, default=str)))
            con.execute("DELETE FROM audit WHERE id <= (SELECT MAX(id) FROM audit) - ?", (MAX_ROWS,))
    except Exception as e:  # noqa: BLE001
        print(f"audit write failed: {e}", flush=True)


def read(kind: str | None = None, status: str | None = None, search: str | None = None,
         limit: int = 100, before_id: int | None = None) -> dict:
    where, args = [], []
    if kind:
        where.append("kind = ?"); args.append(kind)
    if status:
        where.append("status = ?"); args.append(status)
    if search:
        where.append("(summary LIKE ? OR detail LIKE ?)"); args += [f"%{search}%"] * 2
    if before_id:
        where.append("id < ?"); args.append(before_id)
    sql = "SELECT id, ts, kind, client, status, summary, latency_ms, detail FROM audit"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY id DESC LIMIT ?"
    with _lock, _connect() as con:
        rows = con.execute(sql, [*args, max(1, min(limit, 500))]).fetchall()
        totals = dict(con.execute("SELECT kind, COUNT(*) FROM audit GROUP BY kind").fetchall())
        statuses = dict(con.execute("SELECT status, COUNT(*) FROM audit GROUP BY status").fetchall())
    events = [{"id": r[0], "ts": r[1], "kind": r[2], "client": r[3], "status": r[4], "summary": r[5],
               "latency_ms": r[6], "detail": json.loads(r[7] or "{}")} for r in rows]
    return {"events": events, "totals": totals, "statuses": statuses}


class AskRecorder:
    """Collects one /ask run's events so the whole run is logged as one row when it ends."""

    def __init__(self, question: str, client_ip: str):
        self.question, self.client_ip, self.t0 = question, client_ip, time.monotonic()
        self.queries: dict[str, dict] = {}
        self.detail: dict = {}

    def on_event(self, ev: dict) -> None:
        t = ev.get("type")
        if t == "tool_call":
            inp = ev.get("input") or {}
            self.queries[ev["id"]] = {"tool": ev.get("name"), "sql": inp.get("query"),
                                      "purpose": inp.get("purpose")}
        elif t == "tool_result" and ev.get("id") in self.queries:
            self.queries[ev["id"]].update(query_id=ev.get("query_id"), error=ev.get("error"),
                                          summary=(ev.get("summary") or "")[:300])
        elif t == "answer" and ev.get("answer"):
            a = ev["answer"]
            self.detail.update(headline=a.get("headline"), headline_value=a.get("headline_value"),
                               unit=a.get("unit"), confidence=a.get("confidence"))
        elif t == "error":
            self.detail["error"] = ev.get("message")
        elif t == "done":
            stop = ev.get("stop") or "unknown"
            status = "ok" if stop == "submitted" else stop
            record("ask", status, self.question, self.client_ip,
                   int((time.monotonic() - self.t0) * 1000),
                   stop=stop, tool_calls=ev.get("tool_calls"), sql_calls=ev.get("sql_calls"),
                   queries=[q for q in self.queries.values() if q["tool"] != "submit_answer"],
                   **self.detail)
