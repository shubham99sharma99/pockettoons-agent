"""Read-only, guarded SQL access to the analytics schema.

Guardrails (each one is unit-tested in tests/test_sql_guard.py):
  * local mode: the DuckDB file is opened read_only, external file/network
    access is disabled and the configuration is locked;
  * MotherDuck mode (MOTHERDUCK_TOKEN + PT_MD_DATABASE set): the connection
    runs in saas_mode (no local file access) and should use a read-only
    (read scaling) token, so the warehouse cannot be modified even if the
    SQL guard below were bypassed;
  * exactly one statement, and it must be a SELECT (optionally WITH ... SELECT);
  * every table referenced must be on the allowlist (analytics schema only),
    so raw.*, information_schema, table functions like read_csv() are rejected;
  * a wall-clock timeout interrupts long queries;
  * results are capped (auto-LIMIT) and the true row count is reported.
"""
from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import duckdb
import sqlglot
from sqlglot import exp

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "data" / "pockettoons.duckdb"
SCHEMA = "analytics"

ALLOWED_TABLES = {
    "users", "sessions", "content_views", "transactions", "content_catalog", "marketing_spend",
    "fct_user_day", "fct_user_month", "fct_transactions",
}
MAX_ROWS = 200
TIMEOUT_S = float(os.environ.get("PT_SQL_TIMEOUT_S", "10"))


class SQLGuardError(ValueError):
    """Raised when a query is rejected before execution."""


def db_path() -> Path:
    return Path(os.environ.get("PT_DUCKDB_PATH", DEFAULT_DB))


def motherduck_database() -> str | None:
    """MotherDuck database name when MotherDuck mode is configured, else None."""
    name = os.environ.get("PT_MD_DATABASE", "").strip()
    return name if name and os.environ.get("MOTHERDUCK_TOKEN") else None


def target() -> str:
    """Human-readable description of where queries run (for /health and logs)."""
    md = motherduck_database()
    return f"md:{md}" if md else str(db_path())


def _connect() -> duckdb.DuckDBPyConnection:
    md = motherduck_database()
    if md:
        # The MotherDuck extension reads MOTHERDUCK_TOKEN from the environment;
        # the token is never put in the connection string or logged.
        con = duckdb.connect(f"md:{md}?saas_mode=true")
        con.execute("SET lock_configuration = true")
        return con
    con = duckdb.connect(str(db_path()), read_only=True)
    con.execute("SET enable_external_access = false")
    con.execute("SET lock_configuration = true")
    return con


_conn_lock = threading.Lock()
_base_conn: duckdb.DuckDBPyConnection | None = None


def connection() -> duckdb.DuckDBPyConnection:
    """Shared read-only base connection; callers take a cursor per query."""
    global _base_conn
    with _conn_lock:
        if _base_conn is None:
            _base_conn = _connect()
        return _base_conn


def reset_connection() -> None:
    global _base_conn
    with _conn_lock:
        if _base_conn is not None:
            _base_conn.close()
        _base_conn = None


def cursor() -> duckdb.DuckDBPyConnection:
    """A per-query cursor scoped to the analytics schema."""
    cur = connection().cursor()
    cur.execute(f"USE {SCHEMA}")
    return cur


def check_sql(sql: str) -> str:
    """Validate a query and return it normalised (no trailing semicolon)."""
    text = sql.strip().rstrip(";").strip()
    if not text:
        raise SQLGuardError("Empty query.")
    try:
        statements = sqlglot.parse(text, read="duckdb")
    except sqlglot.errors.ParseError as e:
        raise SQLGuardError(f"Could not parse SQL: {str(e).splitlines()[0]}") from None
    statements = [s for s in statements if s is not None]
    if len(statements) != 1:
        raise SQLGuardError("Exactly one statement is allowed.")
    tree = statements[0]
    if not isinstance(tree, (exp.Select, exp.Union, exp.Intersect, exp.Except)):
        raise SQLGuardError("Only SELECT queries (optionally starting with WITH) are allowed.")
    for node in tree.walk():
        if isinstance(node, (exp.Insert, exp.Update, exp.Delete, exp.Create, exp.Drop,
                             exp.Alter, exp.Command, exp.Copy)):
            raise SQLGuardError("Write or DDL operations are not allowed.")
    ctes = {c.alias_or_name.lower() for c in tree.find_all(exp.CTE)}
    for t in tree.find_all(exp.Table):
        name = (t.name or "").lower()
        if not name:
            # table functions such as read_csv('...') or range(...)
            raise SQLGuardError("Table functions are not allowed; query the analytics tables.")
        if name in ctes and not t.db:
            continue
        if t.db and t.db.lower() != SCHEMA:
            raise SQLGuardError(f"Only the '{SCHEMA}' schema is available (got {t.db}.{t.name}).")
        if name not in ALLOWED_TABLES:
            raise SQLGuardError(
                f"Unknown table '{t.name}'. Available: {', '.join(sorted(ALLOWED_TABLES))}.")
    for fn in tree.find_all(exp.Anonymous):
        if fn.name.lower() in {"read_csv", "read_parquet", "read_json", "glob", "read_text",
                               "read_blob", "sqlite_scan", "postgres_scan"}:
            raise SQLGuardError("File and external readers are not allowed.")
    return text


@dataclass
class QueryResult:
    columns: list[str]
    rows: list[list[Any]]
    row_count: int
    truncated: bool
    elapsed_ms: int
    error: str | None = None

    def to_dict(self) -> dict:
        return {"columns": self.columns, "rows": self.rows, "row_count": self.row_count,
                "truncated": self.truncated, "elapsed_ms": self.elapsed_ms, "error": self.error}


def _jsonable(v: Any) -> Any:
    if v is None or isinstance(v, (bool, int, str)):
        return v
    if isinstance(v, float):
        return round(v, 6)
    try:
        import decimal
        if isinstance(v, decimal.Decimal):
            return float(v)
    except Exception:  # pragma: no cover
        pass
    return str(v)


def execute(sql: str, max_rows: int = MAX_ROWS, timeout_s: float = TIMEOUT_S) -> QueryResult:
    """Run a guarded query. Guard errors raise; database errors are returned."""
    text = check_sql(sql)
    cur = cursor()
    out: dict[str, Any] = {}

    def work():
        try:
            rel = cur.execute(f"SELECT * FROM ({text}) AS _q LIMIT {max_rows + 1}")
            out["cols"] = [d[0] for d in rel.description]
            out["rows"] = rel.fetchall()
        except Exception as e:  # noqa: BLE001 - errors go back to the model
            out["err"] = str(e).splitlines()[0][:500]

    t0 = time.monotonic()
    th = threading.Thread(target=work, daemon=True)
    th.start()
    th.join(timeout_s)
    if th.is_alive():
        cur.interrupt()
        th.join(2)
        cur.close()
        return QueryResult([], [], 0, False, int((time.monotonic() - t0) * 1000),
                           error=f"Query timed out after {timeout_s:.0f}s. Aggregate more or filter.")
    elapsed = int((time.monotonic() - t0) * 1000)
    if "err" in out:
        cur.close()
        return QueryResult([], [], 0, False, elapsed, error=out["err"])
    rows = out["rows"]
    truncated = len(rows) > max_rows
    count = len(rows)
    if truncated:
        try:
            count = cur.execute(f"SELECT count(*) FROM ({text}) AS _q").fetchone()[0]
        except Exception:  # noqa: BLE001
            count = -1
        rows = rows[:max_rows]
    cur.close()
    return QueryResult(out["cols"], [[_jsonable(v) for v in r] for r in rows], count,
                       truncated, elapsed)


def query_df(sql: str):
    """Trusted internal helper (tools, eval references). Still read-only."""
    cur = cursor()
    try:
        return cur.execute(sql).df()
    finally:
        cur.close()


@dataclass
class QueryLog:
    """Per-session evidence log: every query gets an ID the answer must cite."""
    entries: list[dict] = field(default_factory=list)

    def add(self, sql: str, purpose: str, result: QueryResult | None, error: str | None = None,
            source: str = "run_sql") -> str:
        qid = f"Q{len(self.entries) + 1}"
        self.entries.append({
            "id": qid, "purpose": purpose, "sql": sql, "source": source,
            "row_count": result.row_count if result else 0,
            "columns": result.columns if result else [],
            "preview": (result.rows[:10] if result else []),
            "error": error or (result.error if result else None),
            "elapsed_ms": result.elapsed_ms if result else 0,
        })
        return qid

    def ids(self) -> set[str]:
        return {e["id"] for e in self.entries}

    def successful_ids(self) -> set[str]:
        return {e["id"] for e in self.entries if not e["error"]}
