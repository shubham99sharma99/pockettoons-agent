"use client";
import { useEffect, useState } from "react";
import { getJSON } from "@/lib/api";
import Markdown from "../markdown";

type Row = {
  id: string; category: string; question: string; pass: boolean; failure_type: string; headline?: string;
  numeric?: { truth: number | null; candidates: number[]; pass: boolean };
  judge?: { pass: boolean; score: number; rationale: string };
  agent: { tool_calls?: number; latency_s?: number };
  answer_markdown?: string;
};
type Summary = {
  available: boolean; message?: string; run_at: string; model: string; judge_model: string; n: number; passed: number;
  pass_rate: number; by_category: Record<string, { n: number; pass: number }>; failure_types: Record<string, number>;
  median_latency_s: number; median_tool_calls: number; results: Row[];
};

export default function EvalPage() {
  const [s, setS] = useState<Summary | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  useEffect(() => { getJSON<Summary>("/eval/results").then(setS).catch((e) => setErr(String(e))); }, []);

  if (err) return <p className="error">{err}</p>;
  if (!s) return <p className="muted">Loading...</p>;
  if (!s.available) return (<><h1>Eval</h1><p className="notice">{s.message}</p></>);

  return (
    <>
      <h1>Eval</h1>
      <p className="muted">Golden questions scored numerically within a tolerance and by an LLM judge. Run {s.run_at} · agent <code>{s.model}</code> · judge <code>{s.judge_model}</code></p>
      <div className="grid">
        <div className="panel kpi"><div className="v">{s.passed}/{s.n}</div><div className="l">passed ({Math.round(s.pass_rate * 100)}%)</div></div>
        <div className="panel kpi"><div className="v">{s.median_tool_calls}</div><div className="l">median tool calls</div></div>
        <div className="panel kpi"><div className="v">{s.median_latency_s}s</div><div className="l">median latency</div></div>
        {Object.entries(s.by_category).map(([c, v]) => (
          <div key={c} className="panel kpi"><div className="v">{v.pass}/{v.n}</div><div className="l">{c}</div></div>
        ))}
      </div>
      <h2>Results</h2>
      <div className="panel wrap">
        <table className="data">
          <thead><tr><th>ID</th><th>Category</th><th>Question</th><th>Result</th><th>Failure type</th><th>Tools</th></tr></thead>
          <tbody>
            {s.results.map((r) => (
              <>
                <tr key={r.id} onClick={() => setOpen(open === r.id ? null : r.id)} style={{ cursor: "pointer" }}>
                  <td>{r.id}</td><td>{r.category}</td><td>{r.question}</td>
                  <td><span className={`pill ${r.pass ? "pass" : "fail"}`}>{r.pass ? "PASS" : "FAIL"}</span></td>
                  <td>{r.failure_type}</td><td>{r.agent.tool_calls}</td>
                </tr>
                {open === r.id && (
                  <tr key={r.id + "-d"}><td colSpan={6}>
                    {r.numeric && <p>Expected <b>{r.numeric.truth}</b>; agent gave {JSON.stringify(r.numeric.candidates)}</p>}
                    {r.judge && <p className="muted">Judge ({r.judge.score}/10): {r.judge.rationale}</p>}
                    {r.answer_markdown && <details><summary>Agent answer</summary><Markdown>{r.answer_markdown}</Markdown></details>}
                  </td></tr>
                )}
              </>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}
