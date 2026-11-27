"""FastAPI backend for the PocketToons analytics agent.

Endpoints
  GET  /health         liveness + database and model info
  GET  /schema         tables, columns and the data dictionary
  GET  /metrics        governed metric catalog (dbt semantic layer + agent definitions)
  POST /query          run one guarded read-only SELECT          (rate limited)
  POST /ask            ask the agent; Server-Sent Events stream (rate limited)
  GET  /eval/results   latest eval summary
  POST /eval/run       start an eval run in the background      (rate limited, optional admin token)
  GET  /eval/status    status of the background eval run

Config (environment)
  ANTHROPIC_API_KEY       required for /ask and /eval/run (PT_PROVIDER=anthropic, the default)
  NVIDIA_API_KEY          required instead when PT_PROVIDER=nim (NVIDIA NIM, see agent/nim.py)
  ALLOWED_ORIGINS         comma-separated CORS origins (your Vercel domain)
  ALLOWED_ORIGIN_REGEX    optional regex, e.g. https://pockettoons-.*\\.vercel\\.app for previews
  ASK_RATE_PER_MIN        per-IP /ask limit (default 4); ASK_RATE_PER_DAY global daily cap (default 200)
  EVAL_ADMIN_TOKEN        if set, /eval/run requires header X-Admin-Token
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import threading
import time
from collections import defaultdict, deque
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv_lite import load_env  # noqa: E402

load_env(ROOT / ".env")

from agent import db, semantic  # noqa: E402
from agent import tools as T  # noqa: E402
from agent.agent import DEFAULT_MODEL, KEY_ENV, PROVIDER, AnalyticsAgent, llm_configured  # noqa: E402

app = FastAPI(title="PocketToons Analytics Agent", version="1.0.0")

origins = [o.strip() for o in os.environ.get("ALLOWED_ORIGINS", "http://localhost:3000").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_origin_regex=os.environ.get("ALLOWED_ORIGIN_REGEX") or None,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "X-Admin-Token"],
)


# --------------------------------------------------------------------------- #
# Rate limiting (in-memory sliding window; fine for one Render instance)
# --------------------------------------------------------------------------- #
class RateLimiter:
    def __init__(self, per_window: int, window_s: float, global_per_day: int | None = None):
        self.per_window, self.window_s, self.global_per_day = per_window, window_s, global_per_day
        self.hits: dict[str, deque] = defaultdict(deque)
        self.day_hits: deque = deque()
        self.lock = threading.Lock()

    def check(self, key: str) -> None:
        now = time.time()
        with self.lock:
            q = self.hits[key]
            while q and now - q[0] > self.window_s:
                q.popleft()
            if len(q) >= self.per_window:
                retry = int(self.window_s - (now - q[0])) + 1
                raise HTTPException(429, f"Rate limit: {self.per_window} per {int(self.window_s)}s. "
                                         f"Retry in {retry}s.", headers={"Retry-After": str(retry)})
            if self.global_per_day is not None:
                while self.day_hits and now - self.day_hits[0] > 86400:
                    self.day_hits.popleft()
                if len(self.day_hits) >= self.global_per_day:
                    raise HTTPException(429, "Daily demo budget reached. Try again tomorrow.")
                self.day_hits.append(now)
            q.append(now)


ask_limiter = RateLimiter(int(os.environ.get("ASK_RATE_PER_MIN", "4")), 60,
                          int(os.environ.get("ASK_RATE_PER_DAY", "200")))
query_limiter = RateLimiter(int(os.environ.get("QUERY_RATE_PER_MIN", "30")), 60)
eval_limiter = RateLimiter(1, float(os.environ.get("EVAL_RUN_MIN_INTERVAL_S", "3600")))


def client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    return fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else "unknown")


def require_key():
    if not llm_configured():
        raise HTTPException(503, f"The server has no {KEY_ENV} configured.")


# --------------------------------------------------------------------------- #
# Read-only endpoints
# --------------------------------------------------------------------------- #
@app.get("/health")
def health():
    try:
        n = int(db.query_df("SELECT count(*) AS n FROM sessions").n[0])
        ok = True
    except Exception as e:  # noqa: BLE001
        n, ok = str(e), False
    return {"status": "ok" if ok else "degraded", "sessions_rows": n, "model": DEFAULT_MODEL,
            "provider": PROVIDER, "database": "motherduck" if db.motherduck_database() else "local",
            "llm_configured": llm_configured()}


@app.get("/schema")
def schema():
    return T.get_schema(T.Session())


@app.get("/metrics")
def metrics():
    return semantic.metric_catalog()


class QueryIn(BaseModel):
    sql: str = Field(..., max_length=8000)


@app.post("/query")
def query(body: QueryIn, request: Request):
    query_limiter.check(client_ip(request))
    try:
        res = db.execute(body.sql)
    except db.SQLGuardError as e:
        raise HTTPException(400, str(e))
    if res.error:
        raise HTTPException(400, res.error)
    return res.to_dict()


# --------------------------------------------------------------------------- #
# /ask: Server-Sent Events
# --------------------------------------------------------------------------- #
class AskIn(BaseModel):
    question: str = Field(..., min_length=3, max_length=2000)


def make_agent() -> AnalyticsAgent:  # overridden in tests
    return AnalyticsAgent()


@app.post("/ask")
async def ask(body: AskIn, request: Request):
    require_key()
    ask_limiter.check(client_ip(request))
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()

    def sink(ev):
        loop.call_soon_threadsafe(queue.put_nowait, ev)

    def work():
        try:
            make_agent().run(body.question, on_event=sink)
        except Exception as e:  # noqa: BLE001
            sink({"type": "error", "message": f"{type(e).__name__}: {str(e)[:300]}"})
            sink({"type": "done", "stop": "api_error"})

    threading.Thread(target=work, daemon=True).start()

    async def gen():
        while True:
            if await request.is_disconnected():
                break
            try:
                ev = await asyncio.wait_for(queue.get(), timeout=15)
            except asyncio.TimeoutError:
                yield {"event": "ping", "data": "{}"}
                continue
            yield {"event": ev["type"], "data": json.dumps(ev, default=str)}
            if ev["type"] == "done":
                break

    return EventSourceResponse(gen())


# --------------------------------------------------------------------------- #
# Eval
# --------------------------------------------------------------------------- #
LATEST = ROOT / "eval" / "results" / "latest.json"
_eval_state = {"status": "idle", "started_at": None, "finished_at": None, "error": None, "ids": None}


@app.get("/eval/results")
def eval_results():
    if not LATEST.exists():
        return {"available": False, "message": "No eval run yet. Run `python -m eval.run_eval` or POST /eval/run."}
    data = json.loads(LATEST.read_text())
    data["available"] = True
    return data


@app.get("/eval/questions")
def eval_questions():
    """Golden questions with reference SQL, for checking the agent by hand on the SQL page.

    Off unless PT_EXPOSE_GOLDEN=1 (local use): this is the eval answer key, so a public
    deployment should not serve it. The agent never calls the API, so this is not a leak to it.
    """
    if os.environ.get("PT_EXPOSE_GOLDEN") != "1":
        raise HTTPException(404, "Golden questions are not exposed. Set PT_EXPOSE_GOLDEN=1 in .env (local only).")
    import yaml
    qs = yaml.safe_load((ROOT / "eval" / "questions.yaml").read_text())["questions"]
    return {"questions": [
        {"id": q["id"], "category": q.get("category"), "question": q["question"],
         "sql": ((q.get("numeric") or {}).get("sql") or "").strip() or None,
         "tol": (q.get("numeric") or {}).get("tol"),
         "facts": q.get("facts") or {}, "rubric": (q.get("judge") or "").strip() or None}
        for q in qs]}


@app.get("/eval/status")
def eval_status():
    return _eval_state


class EvalRunIn(BaseModel):
    ids: list[str] | None = None


@app.post("/eval/run")
def eval_run(body: EvalRunIn, request: Request, x_admin_token: str | None = Header(default=None)):
    token = os.environ.get("EVAL_ADMIN_TOKEN")
    if token and x_admin_token != token:
        raise HTTPException(403, "Admin token required.")
    require_key()
    if _eval_state["status"] == "running":
        raise HTTPException(409, "An eval run is already in progress.")
    eval_limiter.check("global")

    def work():
        from eval import run_eval
        _eval_state.update(status="running", started_at=time.time(), finished_at=None, error=None, ids=body.ids)
        try:
            summary = run_eval.run(body.ids, concurrency=int(os.environ.get("EVAL_CONCURRENCY", "2")))
            run_eval.save(summary)
            _eval_state.update(status="done")
        except Exception as e:  # noqa: BLE001
            _eval_state.update(status="failed", error=str(e)[:500])
        _eval_state["finished_at"] = time.time()

    threading.Thread(target=work, daemon=True).start()
    return {"started": True, "ids": body.ids}
