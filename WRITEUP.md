# Write-up

**Architecture.** A seeded simulator writes six tables to DuckDB; dbt builds typed
staging views, two marts (`fct_user_day`, `fct_user_month`) and MetricFlow metrics, and
ships data tests (one of which, `assert_refunds_negative`, catches the planted bug).
The agent is a Claude (Opus 5.5) tool-calling loop with nine tools: schema, metric
catalog, playbook, column profile, guarded SQL, canned data-quality checks, a
volume/mix/rate/price revenue bridge, a hypothesis register, and `submit_answer`,
which rejects uncited numbers. An optional NVIDIA NIM provider (`agent/nim.py`) runs the same
loop and guardrails on open models through an OpenAI-compatible API, for cheap iteration and a
like-for-like comparison with Claude on the eval. Most accuracy comes from the semantic layer and the
data-quality step, not from the model: the prompt tells it to verify conventions,
compare within segments and decompose before explaining. Text-to-SQL alone fails the
brief (no decomposition, no pivots); multi-agent setups were not worth the time.

**What the agent never sees.** The generator config, the eval answer key and any
statement of the planted effects. The prompt describes the free allowance as
"undocumented; infer it from the data". A test fails the build if agent-visible text
names a planted date, the limit values, or the refund bug.

**Where it breaks (expected; confirm with the live eval).** Ambiguous questions
(picks a reading silently), retention definitions (classic vs rolling), mix effects
read as behaviour when it skips the within-segment check, trusting documented
conventions when it skips DQ checks, and long investigations that stop before the
bridge closes. Numeric scoring catches wrong numbers; the LLM judge catches missed
traps and overclaiming. Hardest categories: data-quality traps and end-to-end.

**Fixes to the reference sample.** Live eval wired end to end (numeric + judge,
saved results, API endpoint); no answer hints in the prompt or semantic layer; the
answer key is recomputed from the database on every eval run, so it cannot go stale;
SQL calls are counted by tool name and tested; scoring is automatic.

**Production for a 20-person product team.**
*Cost and latency:* simple questions take ~3-6 tool calls, investigations 20-40;
log tokens and wall-clock per question (the eval reports medians) and route simple
lookups to a cheaper model or lower effort once the eval shows quality holds.
Prompt caching covers the stable system prompt and tool list.
*Guardrails:* read-only replica, SELECT-only parser and table allowlist, timeouts,
row caps, PII kept out of the semantic layer, per-user rate limits, citations required.
*Monitoring:* the eval is a regression gate on every prompt, tool or model change;
log every query, verdict and answer; thumbs up/down in the UI; weekly review of a
sample; track "not testable" rate and bridge residual as health signals.
*Data contracts:* the DQ checks become scheduled dbt tests (refund sign by method,
duplicate charges, freshness) so the next logging bug pages data engineering first.

**With more time.** A critic pass that tries to refute each root cause before the
report; charts in the agent's own report; cached metric queries via MetricFlow;
feeding analyst edits back into the semantic layer; repeated eval runs to measure
variance rather than a single pass/fail.

**Tools used.** Python, DuckDB, dbt + MetricFlow, sqlglot, the Anthropic SDK,
FastAPI, Next.js, Marp, Claude Code for implementation.
