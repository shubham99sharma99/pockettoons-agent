"use client";
import { useEffect, useState } from "react";
import { getJSON, postJSON } from "@/lib/api";

type Metric = { name: string; label?: string; description?: string; type: string; caveat?: string; sql?: string };
type Catalog = { metrics: Metric[]; analytical_definitions: Record<string, { description: string }>; segments: Record<string, string>; periods: Record<string, string> };
type Q = { columns: string[]; rows: (string | number)[][] };

const MONTHLY = `
WITH m AS (SELECT strftime(date, '%Y-%m') AS month, COUNT(DISTINCT user_id) AS mau FROM sessions GROUP BY 1),
r AS (SELECT strftime(month, '%Y-%m') AS month, COUNT(DISTINCT user_id) FILTER (WHERE is_payer) AS paying_users,
             SUM(net_revenue) AS net_revenue_as_stored FROM fct_user_month GROUP BY 1)
SELECT month, mau, paying_users, ROUND(paying_users * 100.0 / mau, 2) AS payer_rate_pct,
       ROUND(net_revenue_as_stored, 0) AS net_revenue_as_stored
FROM m JOIN r USING (month) ORDER BY 1`;

export default function MetricsPage() {
  const [cat, setCat] = useState<Catalog | null>(null);
  const [monthly, setMonthly] = useState<Q | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    getJSON<Catalog>("/metrics").then(setCat).catch((e) => setErr(String(e)));
    postJSON<Q>("/query", { sql: MONTHLY }).then(setMonthly).catch((e) => setErr(String(e)));
  }, []);

  return (
    <>
      <h1>Metrics</h1>
      <p className="muted">Governed definitions from the dbt semantic layer, plus a monthly snapshot computed live by a read-only query.</p>
      {err && <p className="error">{err}</p>}
      {monthly && (
        <div className="panel wrap">
          <h2 style={{ marginTop: 0 }}>Monthly snapshot</h2>
          <table className="data">
            <thead><tr>{monthly.columns.map((c) => <th key={c}>{c}</th>)}</tr></thead>
            <tbody>{monthly.rows.map((r, i) => <tr key={i}>{r.map((v, j) => <td key={j}>{typeof v === "number" ? v.toLocaleString() : v}</td>)}</tr>)}</tbody>
          </table>
          <p className="muted" style={{ fontSize: 13 }}>Revenue here follows the documented sign convention as stored. Ask the agent whether that convention holds.</p>
        </div>
      )}
      {cat && (
        <>
          <h2>Metric catalog</h2>
          <div className="panel wrap">
            <table className="data">
              <thead><tr><th>Metric</th><th>Type</th><th>Definition</th></tr></thead>
              <tbody>
                {cat.metrics.map((m) => (
                  <tr key={m.name}>
                    <td><b>{m.label ?? m.name}</b><br /><code>{m.name}</code></td>
                    <td>{m.type}</td>
                    <td>{m.description}{m.caveat && <><br /><span className="muted">Caveat: {m.caveat}</span></>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <h2>Analytical definitions</h2>
          <div className="panel wrap">
            <table className="data"><tbody>
              {Object.entries(cat.analytical_definitions).map(([k, v]) => <tr key={k}><td><code>{k}</code></td><td>{v.description}</td></tr>)}
            </tbody></table>
          </div>
          <h2>Segments and periods</h2>
          <div className="grid">
            {Object.entries({ ...cat.segments, ...cat.periods }).map(([k, v]) => (
              <div key={k} className="panel"><b>{k}</b><br /><span className="muted" style={{ fontSize: 13 }}>{v}</span></div>
            ))}
          </div>
        </>
      )}
    </>
  );
}
