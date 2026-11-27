# PocketToons autonomous analytics agent

An AI analyst for a freemium anime streaming app. Ask a product question in plain
English; the agent checks data quality, writes and runs read-only SQL, tests
hypotheses, and returns a GM-ready answer where every number cites a query ID.

Built for the PocketFM Lead Product Analyst take-home ("MAU is up 20% QoQ but
revenue is flat. Figure out what's happening.").

| Deliverable | Where |
|---|---|
| Data generator + database | `data/generate_data.py`, `data/config.py` (every planted effect), `data/pockettoons.duckdb` / `.sqlite` |
| Warehouse + semantic layer | `dbt/` (staging, marts, data tests, MetricFlow semantic models and metrics) |
| Agent | `agent/` (tools, guardrails, prompt, loop), `cli.py` |
| Investigation (board deck, 10 pages) | `report/board_deck.pdf` (source `report/board_deck.md`, evidence `report/evidence.md`) |
| Raw agent output on the GM question | `outputs/investigation_raw.md` (created by `python cli.py --gm`) |
| Eval | `eval/questions.yaml` (21 golden questions), `eval/run_eval.py`, results in `eval/results.md` |
| Write-up (1 page) | `WRITEUP.md` |
| API (Render) | `api/main.py`, `Dockerfile`, `render.yaml` |
| Web app (Vercel) | `web/` (Next.js: Ask, Metrics, Eval pages) |

## Architecture

```
data/generate_data.py ──► DuckDB raw.* ──► dbt (staging views, marts, data tests,
                                              MetricFlow semantic models + metrics)
                                                    │  analytics.* (read-only)
agent/tools.py: get_schema · get_metric_catalog · get_playbook · profile_column
                run_sql (guarded) · run_dq_checks · decompose_change
                log_hypothesis · submit_answer (rejects uncited numbers)
          ▲
agent/agent.py: Claude tool-calling loop (streaming, adaptive thinking,
                budgets, evidence log, hypothesis register)
          ▲
cli.py · api/main.py (FastAPI, SSE) ◄── web/ (Next.js)
eval/: golden questions → numeric tolerance + LLM judge → results.md
```

Guardrails: the DuckDB file is opened read-only with external file access disabled
and the configuration locked; one SELECT per call, parsed with sqlglot; only the
`analytics` tables are allowed (no `raw.*`, table functions or file readers);
10 s timeout; 200-row cap with the true row count; tool and SQL budgets; every
number must cite a query ID.

No answer leakage: the agent sees only `agent/prompts/`, `agent/semantic_layer.yaml`
and the dbt YAML. The generator config and the eval answer key are developer-only,
and `tests/test_no_leakage.py` fails if agent-visible text names a planted effect.

## Run locally

Requirements: Python 3.11+ (tested on 3.13), Node 20+ for the web app.

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env            # then put your key in .env (never commit it)

make build    # generate data (DuckDB + SQLite), dbt build, recompute eval answer key (stop the API first: dbt needs a write lock)
make test     # 59 tests: guardrails, tools, agent loop (scripted LLM), data story, leakage, API
```

Ask questions (needs `ANTHROPIC_API_KEY` in `.env`):

```bash
python cli.py "What was MAU in October 2026?"
python cli.py --gm              # full investigation → outputs/investigation_raw.md (+ .json)
python -m eval.run_eval         # all 21 questions → eval/results.md, eval/results/latest.json
python -m eval.run_eval --ids E01 E17 E19
```

Run the API and the web app:

```bash
make api                        # http://localhost:8000  (docs at /docs)
cd web && cp .env.example .env.local && npm install && npm run dev   # http://localhost:3000
```

Rebuild the board deck (numbers are recomputed through the agent's tools):

```bash
python report/build_report.py
npx @marp-team/marp-cli@4.2.3 report/board_deck.md --pdf --allow-local-files -o report/board_deck.pdf
```

Configuration (`.env`): `PT_MODEL` (default `claude-opus-5-5`), `PT_EFFORT`
(`high`), `PT_JUDGE_MODEL`, `PT_MAX_TOOL_CALLS` (40), `PT_DUCKDB_PATH`
(keep the file name `pockettoons.duckdb`: dbt views reference that catalog name).

## Deploy

### API on Render (free tier, Docker)

1. Push this folder to a GitHub repo.
2. Render → New → Blueprint → pick the repo. `render.yaml` creates a Docker web
   service. The image generates the data and runs `dbt build` at build time, so the
   DuckDB file is baked in and opened read-only.
3. In the service's Environment tab set `ANTHROPIC_API_KEY`, set `ALLOWED_ORIGINS`
   to your Vercel URL (e.g. `https://pockettoons.vercel.app`), optionally
   `ALLOWED_ORIGIN_REGEX` for preview URLs, and `EVAL_ADMIN_TOKEN` to protect
   `POST /eval/run`.
4. Check `https://<service>.onrender.com/health`. Free instances sleep when idle;
   the first request after a sleep takes ~30-60 s.

Endpoints: `GET /health`, `GET /schema`, `GET /metrics`, `POST /query` (guarded SQL,
30/min/IP), `POST /ask` (SSE stream, 4/min/IP and 200/day overall),
`GET /eval/results`, `POST /eval/run` (1/hour, admin token if set), `GET /eval/status`.

Note: eval results written by `/eval/run` live on the container's disk and reset on
redeploy. Commit `eval/results/latest.json` from a local run to ship results with the image.

### Web app on Vercel

1. Vercel → Add New Project → import the repo, set **Root Directory** to `web`.
2. Environment variable: `NEXT_PUBLIC_API_URL=https://<service>.onrender.com`.
3. Deploy, then put the Vercel URL into the API's `ALLOWED_ORIGINS`. The app is
   public with no login; the API's rate limits are the spend control.

## The dataset

Six tables as specified in the brief (`users`, `sessions`, `content_views`,
`transactions`, `content_catalog`, `marketing_spend`), 1 Jun to 30 Nov 2026:
95K users (about 11-15K MAU), 564K sessions, 1.64M episode views, 36K
transactions, about $33K net revenue a month against about $31K of marketing
spend. The story is built from user-level mechanics in `data/generate_data.py`
(vectorised, about 10 seconds); parameters and dates are in `data/config.py`.
`python data/generate_data.py --check` prints the planted-story checks, and
`--seed N --no-write` tries another seed: seeds 1-3 tell the same story
(MAU +18% to +20%; stored revenue -4% to -7%, corrected -7% to -10%).

Measured on the generated data (seed 2026): MAU +19.4% QoQ; net revenue as
stored -3.5%, corrected -6.5%; observed free allowance 5 → 8 on 1 Sep;
TikTok + influencer share of spend 20% → 60%; US share of new signups
58% → 43%; 234 Google Play refunds stored positive from October, overstating
Q2 revenue by about 3%.
`tests/test_data_story.py` asserts each of these.

## Status of this build

Everything above was built and run in a cloud sandbox: data, dbt build, 59 tests,
the Docker image (built and smoke-tested), the Next.js production build, and the
board deck. **The live agent run and the live eval were not run here because no
API key was available in that environment.** Run `python cli.py --gm` and
`python -m eval.run_eval` with your key to produce `outputs/investigation_raw.md`
and `eval/results.md`, then update the deck's last slide with the pass rate.
