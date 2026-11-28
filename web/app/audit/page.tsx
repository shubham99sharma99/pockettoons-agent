"use client";
import { Fragment, useCallback, useEffect, useState } from "react";
import { API_URL } from "@/lib/api";

type AgentQuery = { tool?: string; sql?: string; purpose?: string; query_id?: string; error?: string; summary?: string };
type Event = { id: number; ts: number; kind: string; client: string | null; status: string; summary: string;
  latency_ms: number | null; detail: Record<string, unknown> & { queries?: AgentQuery[] } };
type Log = { events: Event[]; totals: Record<string, number>; statuses: Record<string, number> };

const KINDS: Record<string, string> = { ask: "Agent question", query: "SQL query", eval_run: "Eval run" };
const PLURAL: Record<string, string> = { ask: "Agent questions", query: "SQL queries", eval_run: "Eval runs" };
const selStyle = { padding: 8, borderRadius: 8, border: "1px solid var(--line)", background: "var(--panel)", color: "var(--ink)", font: "inherit" };

function when(ts: number) {
  return new Date(ts * 1000).toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

function Detail({ e }: { e: Event }) {
  const d = e.detail;
  return (
    <div style={{ fontSize: 13, padding: "4px 0 10px" }}>
      {e.kind === "ask" && (
        <>
          <p style={{ margin: "4px 0" }}><b>Question:</b> {e.summary}</p>
          {d.headline !== undefined && <p style={{ margin: "4px 0" }}><b>Answer headline:</b> {String(d.headline)}
            {d.headline_value !== null && d.headline_value !== undefined && <> · value <code>{String(d.headline_value)}</code> {String(d.unit ?? "")}</>}
            {d.confidence !== undefined && <> · confidence {String(d.confidence)}</>}</p>}
          <p className="muted" style={{ margin: "4px 0" }}>Stop: {String(d.stop ?? "")} · {String(d.tool_calls ?? 0)} tool calls, {String(d.sql_calls ?? 0)} SQL</p>
          {(d.queries ?? []).length > 0 && (
            <ul className="steps">{(d.queries ?? []).map((q, i) => (
              <li key={i} style={{ display: "block" }}>
                <span className="tag">{q.query_id ?? q.tool}</span> {q.purpose}
                {q.summary && <span className={q.error ? "err" : "muted"}> → {q.summary}</span>}
                {q.sql && <pre style={{ margin: "6px 0 0" }}>{q.sql}</pre>}
              </li>))}
            </ul>
          )}
        </>
      )}
      {e.kind !== "ask" && <pre style={{ margin: "4px 0" }}>{e.summary}</pre>}
      {d.rows !== undefined && <p className="muted" style={{ margin: "4px 0" }}>{String(d.rows)} rows{d.truncated ? " (truncated to 200)" : ""}</p>}
      {d.error !== undefined && <p className="error" style={{ margin: "6px 0" }}>{String(d.error)}</p>}
    </div>
  );
}

export default function AuditPage() {
  const [log, setLog] = useState<Log | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [kind, setKind] = useState("");
  const [status, setStatus] = useState("");
  const [q, setQ] = useState("");
  const [open, setOpen] = useState<number | null>(null);
  const [live, setLive] = useState(true);
  const [more, setMore] = useState(true);

  const load = useCallback(async (beforeId?: number) => {
    const p = new URLSearchParams({ limit: "100" });
    if (kind) p.set("kind", kind);
    if (status) p.set("status", status);
    if (q.trim()) p.set("q", q.trim());
    if (beforeId) p.set("before_id", String(beforeId));
    try {
      const r = await fetch(`${API_URL}/audit?${p}`, { cache: "no-store" });
      const body = await r.json();
      if (!r.ok) { setErr(body.detail ?? `HTTP ${r.status}`); return; }
      setErr(null);
      setMore(body.events.length === 100);
      setLog((prev) => (beforeId && prev ? { ...body, events: [...prev.events, ...body.events] } : body));
    } catch (e) { setErr(String(e)); }
  }, [kind, status, q]);

  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    if (!live) return;
    const t = setInterval(() => load(), 10000);
    return () => clearInterval(t);
  }, [live, load]);

  const totals = log?.totals ?? {};
  const statuses = log?.statuses ?? {};

  return (
    <>
      <h1>Audit log</h1>
      <p className="muted">Every agent question, SQL query and eval run that reached the API: when, from which client (a salted hash, never the IP),
        what ran and how it ended. Stored in its own small SQLite file, separate from the analytics database. On the free Render server it starts empty after each redeploy.</p>

      {err && <p className="error">{err}</p>}

      <div className="grid" style={{ margin: "12px 0" }}>
        {Object.keys(KINDS).map((k) => (
          <div key={k} className="panel kpi"><div className="l">{PLURAL[k]}</div><div className="v">{(totals[k] ?? 0).toLocaleString()}</div></div>
        ))}
        <div className="panel kpi"><div className="l">Errors, rejected or rate limited</div>
          <div className="v">{Object.entries(statuses).filter(([s]) => s !== "ok").reduce((a, [, n]) => a + n, 0).toLocaleString()}</div></div>
      </div>

      <div className="panel">
        <div className="row" style={{ marginBottom: 10 }}>
          <select value={kind} onChange={(e) => setKind(e.target.value)} style={selStyle} aria-label="Event type">
            <option value="">All events</option>
            {Object.entries(KINDS).map(([k, l]) => <option key={k} value={k}>{l}</option>)}
          </select>
          <select value={status} onChange={(e) => setStatus(e.target.value)} style={selStyle} aria-label="Status">
            <option value="">Any status</option>
            {Object.keys(statuses).sort().map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search question, SQL or error" aria-label="Search"
            style={{ ...selStyle, flex: 1, minWidth: 160 }} />
          <label className="muted" style={{ fontSize: 13 }}><input type="checkbox" checked={live} onChange={(e) => setLive(e.target.checked)} /> Auto-refresh</label>
          <button className="ghost" onClick={() => load()}>Refresh</button>
        </div>

        <div className="wrap">
          <table className="data">
            <thead><tr><th>Time</th><th>Type</th><th>Status</th><th>Question or SQL</th><th>Client</th><th style={{ textAlign: "right" }}>Time taken</th></tr></thead>
            <tbody>
              {log?.events.map((e) => (
                <Fragment key={e.id}>
                  <tr onClick={() => setOpen(open === e.id ? null : e.id)} style={{ cursor: "pointer" }}>
                    <td style={{ whiteSpace: "nowrap" }}>{when(e.ts)}</td>
                    <td style={{ whiteSpace: "nowrap" }}>{KINDS[e.kind] ?? e.kind}</td>
                    <td><span className={`pill ${e.status === "ok" ? "pass" : "fail"}`}>{e.status}</span></td>
                    <td style={{ maxWidth: 420 }}>
                      <div style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", fontFamily: e.kind === "query" ? "ui-monospace, monospace" : undefined, fontSize: e.kind === "query" ? 12.5 : undefined }}>
                        {e.summary.replace(/\s+/g, " ").trim()}
                      </div>
                    </td>
                    <td><code>{e.client ?? "-"}</code></td>
                    <td style={{ textAlign: "right", whiteSpace: "nowrap" }}>{e.latency_ms === null ? "-" : e.latency_ms >= 1000 ? `${(e.latency_ms / 1000).toFixed(1)} s` : `${e.latency_ms} ms`}</td>
                  </tr>
                  {open === e.id && <tr><td colSpan={6}><Detail e={e} /></td></tr>}
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
        {log && log.events.length === 0 && <p className="muted">No events match.</p>}
        {log && more && log.events.length > 0 && (
          <div className="row" style={{ justifyContent: "center", marginTop: 10 }}>
            <button className="ghost" onClick={() => load(log.events[log.events.length - 1].id)}>Load older</button>
          </div>
        )}
      </div>
    </>
  );
}
