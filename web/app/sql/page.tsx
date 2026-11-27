"use client";
import { useEffect, useRef, useState } from "react";
import { ask, getJSON, postJSON, Answer, API_URL } from "@/lib/api";
import Markdown from "../markdown";

type Col = { name: string; type: string; description?: string };
type Table = { table: string; rows: number; description?: string; columns: Col[] };
type Result = { columns: string[]; rows: unknown[][]; row_count: number; truncated: boolean; elapsed_ms: number };
type Tol = { rel?: number; abs?: number };
type Golden = { id: string; category?: string; question: string; sql: string | null; tol: Tol | null;
  facts: Record<string, string>; rubric: string | null };
type Step = { id: string; name: string; sql?: string; purpose?: string; queryId?: string; summary?: string; error?: string };

function fmt(v: unknown) {
  if (typeof v === "number") return Number.isInteger(v) ? v.toLocaleString() : v.toLocaleString(undefined, { maximumFractionDigits: 4 });
  if (v === null || v === undefined) return <span className="muted">null</span>;
  return String(v);
}

function withinTol(v: number | null | undefined, truth: number | null, tol: Tol | null) {
  if (v === null || v === undefined || truth === null || !tol) return null;
  if (tol.abs !== undefined && Math.abs(v - truth) <= tol.abs) return true;
  if (tol.rel !== undefined && truth !== 0 && Math.abs(v - truth) / Math.abs(truth) <= tol.rel) return true;
  return false;
}

function ResultTable({ r }: { r: Result }) {
  return (
    <>
      <p className="muted" style={{ fontSize: 13, margin: "8px 0" }}>
        {r.row_count.toLocaleString()} row{r.row_count === 1 ? "" : "s"}{r.truncated ? " (showing first 200)" : ""} · {r.elapsed_ms} ms
      </p>
      <div className="wrap" style={{ maxHeight: 380, overflowY: "auto" }}>
        <table className="data">
          <thead><tr>{r.columns.map((c) => <th key={c}>{c}</th>)}</tr></thead>
          <tbody>{r.rows.map((row, i) => <tr key={i}>{row.map((v, j) => <td key={j}>{fmt(v)}</td>)}</tr>)}</tbody>
        </table>
      </div>
    </>
  );
}

export default function SqlPage() {
  const [tables, setTables] = useState<Table[]>([]);
  const [golden, setGolden] = useState<Golden[] | null>(null);
  const [goldenMsg, setGoldenMsg] = useState<string | null>(null);
  const [picked, setPicked] = useState<Golden | null>(null);
  const [refValue, setRefValue] = useState<number | null>(null);

  const [sql, setSql] = useState("SELECT strftime(date, '%Y-%m') AS month, COUNT(DISTINCT user_id) AS mau\nFROM sessions\nGROUP BY 1\nORDER BY 1");
  const [result, setResult] = useState<Result | null>(null);
  const [sqlErr, setSqlErr] = useState<string | null>(null);
  const [sqlBusy, setSqlBusy] = useState(false);

  const [question, setQuestion] = useState("");
  const [running, setRunning] = useState(false);
  const [steps, setSteps] = useState<Step[]>([]);
  const [answer, setAnswer] = useState<Answer | null>(null);
  const [agentErr, setAgentErr] = useState<string | null>(null);
  const [stats, setStats] = useState<string | null>(null);
  const abort = useRef<AbortController | null>(null);

  useEffect(() => {
    getJSON<{ tables: Table[] }>("/schema").then((s) => setTables(s.tables)).catch(() => {});
    fetch(`${API_URL}/eval/questions`, { cache: "no-store" }).then(async (r) => {
      if (r.ok) setGolden((await r.json()).questions);
      else setGoldenMsg((await r.json().catch(() => ({}))).detail ?? `HTTP ${r.status}`);
    }).catch((e) => setGoldenMsg(String(e)));
  }, []);

  async function runSql(text: string, isReference = false) {
    setSqlBusy(true); setSqlErr(null);
    try {
      const r = await postJSON<Result>("/query", { sql: text });
      setResult(r);
      if (isReference) {
        const v = r.rows[0]?.[0];
        setRefValue(typeof v === "number" ? v : v === null || v === undefined ? null : Number(v));
      }
    } catch (e) {
      const m = String((e as Error).message);
      const detail = m.match(/"detail":"(.*)"/)?.[1];
      setSqlErr(detail ? detail.replace(/\\"/g, '"') : m);
      setResult(null);
    } finally { setSqlBusy(false); }
  }

  function pickGolden(id: string) {
    const g = golden?.find((x) => x.id === id) ?? null;
    setPicked(g); setRefValue(null); setAnswer(null); setSteps([]); setStats(null); setAgentErr(null);
    if (!g) return;
    setQuestion(g.question);
    const text = g.sql ?? Object.values(g.facts)[0] ?? "";
    if (text) { setSql(text); runSql(text, !!g.sql); }
  }

  async function runAgent() {
    if (!question.trim() || running) return;
    setRunning(true); setSteps([]); setAnswer(null); setAgentErr(null); setStats(null);
    abort.current = new AbortController();
    try {
      await ask(question, (e) => {
        if (e.type === "tool_call") {
          const inp = (e.input ?? {}) as { query?: string; purpose?: string };
          setSteps((s) => [...s, { id: e.id, name: e.name, sql: inp.query, purpose: inp.purpose }]);
        } else if (e.type === "tool_result") {
          setSteps((s) => s.map((x) => (x.id === e.id ? { ...x, queryId: e.query_id, summary: e.summary, error: e.error } : x)));
        } else if (e.type === "answer") setAnswer(e.answer);
        else if (e.type === "error") setAgentErr(e.message);
        else if (e.type === "done") setStats(`${e.stop} · ${e.tool_calls} tool calls, ${e.sql_calls} SQL · ${e.latency_s}s`);
      }, abort.current.signal);
    } catch (err) {
      if ((err as Error).name !== "AbortError") setAgentErr((err as Error).message);
    } finally { setRunning(false); }
  }

  const verdict = withinTol(answer?.headline_value, refValue, picked?.tol ?? null);
  const sqlSteps = steps.filter((s) => s.sql);

  return (
    <>
      <h1>SQL check</h1>
      <p className="muted">Run your own read-only SQL on the same tables the agent uses, then ask the agent the same question and compare.
        The same guardrails apply: one SELECT, analytics tables only, 200-row cap.</p>

      <details className="panel" style={{ marginBottom: 16 }}>
        <summary><b>Tables</b> ({tables.length}) · click one to preview it</summary>
        <div className="grid" style={{ marginTop: 12 }}>
          {tables.map((t) => (
            <div key={t.table} style={{ fontSize: 13 }}>
              <button className="ghost" style={{ padding: "4px 10px" }}
                onClick={() => { const q = `SELECT * FROM ${t.table} LIMIT 50`; setSql(q); runSql(q); }}>
                {t.table}
              </button> <span className="muted">{t.rows.toLocaleString()} rows</span>
              <div className="muted" style={{ marginTop: 4 }}>{t.columns.map((c) => c.name).join(", ")}</div>
            </div>
          ))}
        </div>
      </details>

      <div className="panel" style={{ marginBottom: 16 }}>
        <div className="row">
          <b>Golden question</b>
          {golden ? (
            <select value={picked?.id ?? ""} onChange={(e) => pickGolden(e.target.value)} style={{ flex: 1, minWidth: 0, padding: 8, borderRadius: 8, border: "1px solid var(--line)", background: "var(--panel)", color: "var(--ink)", font: "inherit" }}>
              <option value="">Pick one to load its reference SQL, or write your own below</option>
              {golden.map((g) => <option key={g.id} value={g.id}>{g.id} · {g.question.length > 90 ? g.question.slice(0, 87) + "..." : g.question}</option>)}
            </select>
          ) : <span className="muted" style={{ fontSize: 13 }}>{goldenMsg ?? "Loading..."}</span>}
        </div>
        {picked && (
          <div style={{ marginTop: 10, fontSize: 14 }}>
            {picked.sql ? (
              <span>Reference answer: <b>{refValue === null ? "..." : fmt(refValue)}</b>
                {picked.tol && <span className="muted"> · passes within {picked.tol.rel !== undefined ? `±${picked.tol.rel * 100}%` : ""}{picked.tol.abs !== undefined ? ` ±${picked.tol.abs}` : ""}</span>}
              </span>
            ) : <span className="muted">No single reference number: this question is graded on reasoning. The editor shows a supporting fact query.</span>}
            {picked.rubric && <details style={{ marginTop: 6 }}><summary>What a good answer looks like</summary><p className="muted">{picked.rubric}</p></details>}
          </div>
        )}
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 440px), 1fr))", gap: 16, alignItems: "start" }}>
        <div className="panel" style={{ minWidth: 0 }}>
          <h2 style={{ marginTop: 0 }}>Your SQL</h2>
          <textarea value={sql} onChange={(e) => setSql(e.target.value)} spellCheck={false}
            style={{ minHeight: 160, fontFamily: "ui-monospace, monospace", fontSize: 13 }}
            onKeyDown={(e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) runSql(sql); }} />
          <div className="row" style={{ marginTop: 8, justifyContent: "space-between" }}>
            <span className="muted" style={{ fontSize: 13 }}>⌘ + Enter to run</span>
            <button onClick={() => runSql(sql)} disabled={sqlBusy || !sql.trim()}>{sqlBusy ? "Running..." : "Run SQL"}</button>
          </div>
          {sqlErr && <p className="error" style={{ marginTop: 10 }}>{sqlErr}</p>}
          {result && <ResultTable r={result} />}
        </div>

        <div className="panel" style={{ minWidth: 0 }}>
          <h2 style={{ marginTop: 0 }}>Agent</h2>
          <textarea value={question} onChange={(e) => setQuestion(e.target.value)} placeholder="Ask the same question in plain English"
            onKeyDown={(e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) runAgent(); }} />
          <div className="row" style={{ marginTop: 8, justifyContent: "flex-end" }}>
            {running && <button className="ghost" onClick={() => abort.current?.abort()}>Stop</button>}
            <button onClick={runAgent} disabled={running || !question.trim()}>{running ? "Working..." : "Ask the agent"}</button>
          </div>
          {agentErr && <p className="error" style={{ marginTop: 10 }}>{agentErr}</p>}

          {answer && (
            <div className="notice" style={{ marginTop: 12 }}>
              <div className="row" style={{ justifyContent: "space-between" }}>
                <span>Agent&apos;s number: <b>{answer.headline_value === null ? "none" : fmt(answer.headline_value)}</b> {answer.unit}</span>
                {verdict !== null && <span className={`pill ${verdict ? "pass" : "fail"}`}>{verdict ? "matches reference" : "does not match"}</span>}
              </div>
              <div style={{ fontSize: 13, marginTop: 4 }}>{answer.headline}</div>
            </div>
          )}

          {(sqlSteps.length > 0 || running) && (
            <>
              <h2>Agent&apos;s queries {running && <span className="muted">(live)</span>}</h2>
              <ul className="steps">
                {sqlSteps.map((s) => (
                  <li key={s.id} style={{ display: "block" }}>
                    <div className="row" style={{ justifyContent: "space-between" }}>
                      <span><span className="tag">{s.queryId ?? "…"}</span> {s.purpose}
                        {s.summary && <span className={s.error ? "err" : "muted"}> → {s.summary}</span>}</span>
                      <button className="ghost" style={{ padding: "2px 10px", fontSize: 12 }}
                        onClick={() => { setSql(s.sql!); runSql(s.sql!); }}>Run in my editor</button>
                    </div>
                    <pre style={{ margin: "6px 0 0" }}>{s.sql}</pre>
                  </li>
                ))}
              </ul>
            </>
          )}

          {answer && (
            <details style={{ marginTop: 12 }}>
              <summary>Full answer · confidence {answer.confidence}</summary>
              <Markdown>{answer.answer_markdown}</Markdown>
            </details>
          )}
          {stats && <p className="muted" style={{ fontSize: 13 }}>Finished ({stats})</p>}
        </div>
      </div>
    </>
  );
}
