"use client";
import { useRef, useState } from "react";
import { ask, AgentEvent, Answer } from "@/lib/api";
import Markdown from "./markdown";

const SAMPLES = [
  "What was MAU in October 2026?",
  "Is Android checkout broken?",
  "What was total net revenue from June to November 2026?",
  "How are we doing in LatAm?",
  "MAU is up 20% QoQ but revenue is flat. Figure out what's happening and what we should do about it.",
];

type Step = { id: string; name: string; input: unknown; summary?: string; queryId?: string; error?: string };

export default function AskPage() {
  const [q, setQ] = useState("");
  const [running, setRunning] = useState(false);
  const [steps, setSteps] = useState<Step[]>([]);
  const [notes, setNotes] = useState("");
  const [answer, setAnswer] = useState<Answer | null>(null);
  const [done, setDone] = useState<Extract<AgentEvent, { type: "done" }> | null>(null);
  const [error, setError] = useState<string | null>(null);
  const abort = useRef<AbortController | null>(null);

  async function run(question: string) {
    if (!question.trim() || running) return;
    setRunning(true); setSteps([]); setNotes(""); setAnswer(null); setDone(null); setError(null);
    abort.current = new AbortController();
    try {
      await ask(question, (e) => {
        if (e.type === "text") setNotes((n) => n + e.text);
        else if (e.type === "tool_call") setSteps((s) => [...s, { id: e.id, name: e.name, input: e.input }]);
        else if (e.type === "tool_result")
          setSteps((s) => s.map((x) => (x.id === e.id ? { ...x, summary: e.summary, queryId: e.query_id, error: e.error } : x)));
        else if (e.type === "answer") setAnswer(e.answer);
        else if (e.type === "error") setError(e.message);
        else if (e.type === "done") setDone(e);
      }, abort.current.signal);
    } catch (err) {
      if ((err as Error).name !== "AbortError") setError((err as Error).message);
    } finally {
      setRunning(false);
    }
  }

  return (
    <>
      <h1>Ask a product question</h1>
      <p className="muted">Plain English, no SQL. The agent checks data quality, runs read-only queries and cites every number (Q1, Q2, ...).</p>
      <div className="panel">
        <textarea value={q} onChange={(e) => setQ(e.target.value)} placeholder="e.g. Why did payer rate fall in Q2?"
          onKeyDown={(e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) run(q); }} />
        <div className="row" style={{ marginTop: 10, justifyContent: "space-between" }}>
          <div className="chips">
            {SAMPLES.map((s) => <button key={s} className="chip" onClick={() => { setQ(s); run(s); }} disabled={running}>{s.length > 60 ? s.slice(0, 57) + "..." : s}</button>)}
          </div>
          <div className="row">
            {running && <button className="ghost" onClick={() => abort.current?.abort()}>Stop</button>}
            <button onClick={() => run(q)} disabled={running || !q.trim()}>{running ? "Working..." : "Ask"}</button>
          </div>
        </div>
      </div>

      {error && <p className="error">{error}</p>}

      {(steps.length > 0 || running) && (
        <div className="panel" style={{ marginTop: 16 }}>
          <h2 style={{ marginTop: 0 }}>Investigation steps {running && <span className="muted">(live)</span>}</h2>
          <ul className="steps">
            {steps.map((s) => (
              <li key={s.id}>
                <span className="tag">{s.queryId ?? "·"}</span>
                <span><b>{s.name}</b>{" "}
                  {s.name === "run_sql" && typeof s.input === "object" && s.input && "purpose" in s.input ? String((s.input as { purpose: string }).purpose) : ""}
                  {s.summary && <span className={s.error ? "err" : "muted"}> → {s.summary}</span>}
                </span>
              </li>
            ))}
          </ul>
          {notes && <details style={{ marginTop: 8 }}><summary>Agent notes</summary><Markdown>{notes}</Markdown></details>}
        </div>
      )}

      {answer && (
        <div className="panel" style={{ marginTop: 16 }}>
          <div className="row" style={{ justifyContent: "space-between" }}>
            <h2 style={{ marginTop: 0 }}>Answer</h2>
            <span className="muted">Confidence: {answer.confidence} · evidence {answer.query_ids.join(", ") || "none"}</span>
          </div>
          <Markdown>{answer.answer_markdown}</Markdown>
          {answer.assumptions?.length > 0 && <p className="muted">Assumptions: {answer.assumptions.join("; ")}</p>}
        </div>
      )}
      {done && <p className="muted">Finished ({done.stop}) · {done.tool_calls} tool calls, {done.sql_calls} SQL · {done.latency_s}s</p>}
    </>
  );
}
