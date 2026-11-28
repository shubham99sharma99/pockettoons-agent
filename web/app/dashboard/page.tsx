"use client";
import { useEffect, useState } from "react";
import { getJSON } from "@/lib/api";
import { BarList, LineChart, Spark } from "../charts";

type Month = { month: string; mau: number; paying_users: number; new_users: number; payer_rate: number;
  subscription_revenue: number; ppv_revenue: number; refunds: number; gross_revenue: number; net_revenue: number;
  arppu: number; refund_rows: number; refunds_stored_positive: number; charge_failure_rate: number };
type Dash = { monthly: Month[]; daily: { date: string; dau: number }[];
  channels: { channel: string; signups: number; spend: number | null; cost_per_signup: number | null }[];
  platforms: { platform: string; sessions: number; users: number }[];
  latest_month: string; definitions: Record<string, string> };

const int = (n: number) => Math.round(n).toLocaleString();
const usd = (n: number) => (Math.abs(n) >= 10000 ? `${n < 0 ? "-" : ""}$${(Math.abs(n) / 1000).toFixed(1)}k`
  : `${n < 0 ? "-" : ""}$${Math.abs(n).toLocaleString(undefined, { maximumFractionDigits: 0 })}`);
const usdK = (n: number) => `$${(n / 1000).toFixed(0)}k`;
const pct = (n: number) => `${(n * 100).toFixed(1)}%`;
const monthName = (m: string) => new Date(`${m}-01T00:00:00`).toLocaleString(undefined, { month: "short", year: "numeric" });
const short = (m: string) => new Date(`${m}-01T00:00:00`).toLocaleString(undefined, { month: "short" });

function Kpi({ label, rows, k, fmt, def, rate }: {
  label: string; rows: Month[]; k: keyof Month; fmt: (n: number) => string; def?: string; rate?: boolean;
}) {
  const cur = rows[rows.length - 1][k] as number;
  const prev = rows.length > 1 ? (rows[rows.length - 2][k] as number) : null;
  let delta = "";
  if (prev !== null && prev !== 0) {
    const d = rate ? (cur - prev) * 100 : ((cur - prev) / Math.abs(prev)) * 100;
    delta = `${d >= 0 ? "▲" : "▼"} ${Math.abs(d).toFixed(1)}${rate ? " pts" : "%"} vs ${short(rows[rows.length - 2].month)}`;
  }
  return (
    <div className="panel kpi" title={def}>
      <div className="l">{label}</div>
      <div className="v">{fmt(cur)}</div>
      <div className="d">{delta}</div>
      <Spark values={rows.map((r) => r[k] as number)} />
    </div>
  );
}

export default function DashboardPage() {
  const [d, setD] = useState<Dash | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => { getJSON<Dash>("/dashboard").then(setD).catch((e) => setErr(String(e))); }, []);

  if (err) return <><h1>Dashboard</h1><p className="error">{err}</p></>;
  if (!d) return <><h1>Dashboard</h1><p className="muted">Loading...</p></>;

  const m = d.monthly, last = m[m.length - 1], labels = m.map((r) => short(r.month));
  const def = d.definitions;
  const paid = d.channels.filter((c) => c.cost_per_signup !== null);
  const totalSessions = d.platforms.reduce((a, p) => a + p.sessions, 0);

  return (
    <>
      <h1>Dashboard</h1>
      <p className="muted">{monthName(last.month)} compared with the month before. Data runs from {d.daily[0]?.date} to{" "}
        {d.daily[d.daily.length - 1]?.date}, computed live from the same read-only tables the agent uses. Hover a tile for its definition.</p>

      <div className="grid" style={{ marginTop: 12 }}>
        <Kpi label="Monthly active users" rows={m} k="mau" fmt={int} def={def.mau} />
        <Kpi label="Paying users" rows={m} k="paying_users" fmt={int} def={def.paying_users} />
        <Kpi label="Payer rate" rows={m} k="payer_rate" fmt={pct} def={def.payer_rate} rate />
        <Kpi label="Net revenue" rows={m} k="net_revenue" fmt={usd} def={def.net_revenue} />
        <Kpi label="Revenue per paying user" rows={m} k="arppu" fmt={(n) => `$${n.toFixed(2)}`} def={def.arppu} />
        <Kpi label="New users" rows={m} k="new_users" fmt={int} def={def.new_users} />
        <Kpi label="Charge failure rate" rows={m} k="charge_failure_rate" fmt={pct} def={def.charge_failure_rate} rate />
        <Kpi label="Refunds" rows={m} k="refunds" fmt={usd} def="Successful refunds in the month, always counted as negative." />
      </div>

      {last.refunds_stored_positive > 0 && (
        <p className="notice" style={{ marginTop: 12 }}>
          Data quality: {last.refunds_stored_positive.toLocaleString()} of {last.refund_rows.toLocaleString()} refund rows in{" "}
          {monthName(last.month)} are stored with a positive amount. Net revenue here subtracts every refund, so it differs
          from a plain <code>SUM(amount_usd)</code>.
        </p>
      )}

      <div className="cols2" style={{ marginTop: 12 }}>
        <div className="panel">
          <h2 style={{ marginTop: 0 }}>Daily active users</h2>
          <LineChart labels={d.daily.map((r) => r.date.slice(5))} format={int} tickEvery={30}
            series={[{ name: "DAU", color: "var(--s1)", values: d.daily.map((r) => r.dau) }]} />
        </div>
        <div className="panel">
          <h2 style={{ marginTop: 0 }}>Gross revenue by product</h2>
          <LineChart labels={labels} format={usdK} series={[
            { name: "Subscriptions", color: "var(--s1)", values: m.map((r) => r.subscription_revenue) },
            { name: "Pay-per-view", color: "var(--s2)", values: m.map((r) => r.ppv_revenue) }]} />
        </div>
        <div className="panel">
          <h2 style={{ marginTop: 0 }}>Payer rate</h2>
          <LineChart labels={labels} format={pct} zero={false}
            series={[{ name: "Payer rate", color: "var(--s1)", values: m.map((r) => r.payer_rate) }]} />
        </div>
        <div className="panel">
          <h2 style={{ marginTop: 0 }}>MAU and paying users</h2>
          <LineChart labels={labels} format={int} series={[
            { name: "MAU", color: "var(--s1)", values: m.map((r) => r.mau) },
            { name: "Paying users", color: "var(--s2)", values: m.map((r) => r.paying_users) }]} />
        </div>
        <div className="panel">
          <h2 style={{ marginTop: 0 }}>Signups by channel, {monthName(last.month)}</h2>
          <BarList format={int} rows={d.channels.map((c) => ({ label: c.channel, value: c.signups,
            detail: c.spend === null ? "No paid spend" : `Spend ${usd(c.spend)} · $${c.cost_per_signup!.toFixed(2)} per signup` }))} />
          <h2>Cost per signup, paid channels</h2>
          <BarList format={(n) => `$${n.toFixed(2)}`} rows={[...paid].sort((a, b) => a.cost_per_signup! - b.cost_per_signup!)
            .map((c) => ({ label: c.channel, value: c.cost_per_signup!, detail: `${usd(c.spend!)} spend / ${int(c.signups)} signups` }))} />
          <p className="muted" style={{ fontSize: 12.5 }}>Cost per signup is not cost per payer. Ask the agent which channels convert.</p>
        </div>
        <div className="panel">
          <h2 style={{ marginTop: 0 }}>Sessions by platform, {monthName(last.month)}</h2>
          <BarList format={pct} rows={d.platforms.map((p) => ({ label: p.platform, value: p.sessions / totalSessions,
            detail: `${int(p.sessions)} sessions · ${int(p.users)} users` }))} />
        </div>
      </div>

      <details className="panel" style={{ marginTop: 12 }}>
        <summary>Monthly numbers as a table, with definitions</summary>
        <div className="wrap" style={{ marginTop: 8 }}>
          <table className="data">
            <thead><tr><th>Month</th><th>MAU</th><th>Paying users</th><th>Payer rate</th><th>Subscriptions</th><th>PPV</th>
              <th>Refunds</th><th>Net revenue</th><th>ARPPU</th><th>New users</th></tr></thead>
            <tbody>{m.map((r) => (
              <tr key={r.month}><td>{r.month}</td><td>{int(r.mau)}</td><td>{int(r.paying_users)}</td><td>{pct(r.payer_rate)}</td>
                <td>{usd(r.subscription_revenue)}</td><td>{usd(r.ppv_revenue)}</td><td>{usd(r.refunds)}</td>
                <td>{usd(r.net_revenue)}</td><td>${r.arppu.toFixed(2)}</td><td>{int(r.new_users)}</td></tr>))}
            </tbody>
          </table>
        </div>
        <ul className="muted" style={{ fontSize: 13 }}>{Object.entries(def).map(([k, v]) => <li key={k}><code>{k}</code>: {v}</li>)}</ul>
      </details>
    </>
  );
}
