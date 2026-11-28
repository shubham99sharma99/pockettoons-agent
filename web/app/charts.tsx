"use client";
import { useState } from "react";

export type Series = { name: string; color: string; values: (number | null)[] };

function niceTicks(min: number, max: number, n = 4) {
  if (max === min) max = min + 1;
  const step0 = (max - min) / n;
  const mag = Math.pow(10, Math.floor(Math.log10(step0)));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= step0) ?? step0;
  const lo = Math.floor(min / step) * step, hi = Math.ceil(max / step) * step;
  const out: number[] = [];
  for (let v = lo; v <= hi + step / 2; v += step) out.push(+v.toFixed(10));
  return out;
}

/** Line chart with a crosshair tooltip. One y-axis only. */
export function LineChart({ series, labels, format, height = 220, zero = true, tickEvery }: {
  series: Series[]; labels: string[]; format: (n: number) => string; height?: number; zero?: boolean; tickEvery?: number;
}) {
  const [hover, setHover] = useState<number | null>(null);
  const W = 640, H = height, L = 52, R = 12, T = 10, B = 26;
  const all = series.flatMap((s) => s.values).filter((v): v is number => v !== null);
  const ticks = niceTicks(zero ? Math.min(0, ...all) : Math.min(...all), Math.max(...all));
  const y0 = ticks[0], y1 = ticks[ticks.length - 1];
  const n = labels.length;
  const x = (i: number) => L + (n === 1 ? 0 : (i * (W - L - R)) / (n - 1));
  const y = (v: number) => T + (1 - (v - y0) / (y1 - y0)) * (H - T - B);
  const every = tickEvery ?? Math.max(1, Math.ceil(n / 6));
  const path = (vals: (number | null)[]) => vals.map((v, i) => (v === null ? "" : `${i && vals[i - 1] !== null ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`)).join("");

  function move(e: React.MouseEvent<SVGSVGElement>) {
    const r = e.currentTarget.getBoundingClientRect();
    const px = ((e.clientX - r.left) / r.width) * W;
    setHover(Math.max(0, Math.min(n - 1, Math.round(((px - L) / (W - L - R)) * (n - 1)))));
  }

  return (
    <div className="chart">
      {series.length > 1 && (
        <div className="legend">{series.map((s) => <span key={s.name}><i style={{ background: s.color }} />{s.name}</span>)}</div>
      )}
      <svg viewBox={`0 0 ${W} ${H}`} onMouseMove={move} onMouseLeave={() => setHover(null)} role="img"
        aria-label={series.map((s) => s.name).join(", ")}>
        {ticks.map((t) => (
          <g key={t}>
            <line x1={L} x2={W - R} y1={y(t)} y2={y(t)} stroke="var(--grid)" strokeWidth={1} />
            <text x={L - 8} y={y(t) + 4} textAnchor="end" fontSize={11} fill="var(--muted)">{format(t)}</text>
          </g>
        ))}
        {labels.map((l, i) => i % every === 0 && (
          <text key={l} x={x(i)} y={H - 6} textAnchor="middle" fontSize={11} fill="var(--muted)">{l}</text>
        ))}
        {series.map((s) => <path key={s.name} d={path(s.values)} fill="none" stroke={s.color} strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />)}
        {n <= 12 && series.map((s) => s.values.map((v, i) => v !== null && (
          <circle key={s.name + i} cx={x(i)} cy={y(v)} r={4} fill={s.color} stroke="var(--panel)" strokeWidth={2} />)))}
        {hover !== null && (
          <g>
            <line x1={x(hover)} x2={x(hover)} y1={T} y2={H - B} stroke="var(--muted)" strokeWidth={1} strokeDasharray="3 3" />
            {series.map((s) => s.values[hover] !== null && (
              <circle key={s.name} cx={x(hover)} cy={y(s.values[hover]!)} r={5} fill={s.color} stroke="var(--panel)" strokeWidth={2} />))}
          </g>
        )}
        <rect x={L} y={T} width={W - L - R} height={H - T - B} fill="transparent" />
      </svg>
      {hover !== null && (
        <div className="tip" style={{ left: `${(x(hover) / W) * 100}%`, top: 0, transform: `translateX(${x(hover) > W * 0.6 ? "-105%" : "8px"})` }}>
          <b>{labels[hover]}</b>
          {series.map((s) => (
            <div key={s.name}><i style={{ display: "inline-block", width: 8, height: 8, borderRadius: 2, background: s.color, marginRight: 6 }} />
              {series.length > 1 ? `${s.name}: ` : ""}{s.values[hover] === null ? "n/a" : format(s.values[hover]!)}</div>
          ))}
        </div>
      )}
    </div>
  );
}

/** Horizontal bars, one series, direct-labelled; hover shows the detail line. */
export function BarList({ rows, format }: {
  rows: { label: string; value: number; detail?: string }[]; format: (n: number) => string;
}) {
  const [hover, setHover] = useState<number | null>(null);
  const max = Math.max(...rows.map((r) => r.value), 0) || 1;
  return (
    <div className="bars">
      {rows.map((r, i) => (
        <div key={r.label} className="b" onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)}>
          <span>{r.label}</span>
          <div className="track"><div className="fill" style={{ width: `${(r.value / max) * 100}%` }} /></div>
          <span style={{ fontVariantNumeric: "tabular-nums" }}>{format(r.value)}</span>
          {hover === i && r.detail && <span className="muted" style={{ gridColumn: "2 / 4", fontSize: 12 }}>{r.detail}</span>}
        </div>
      ))}
    </div>
  );
}

/** Tiny trend line for a KPI tile. */
export function Spark({ values }: { values: number[] }) {
  if (values.length < 2) return null;
  const W = 100, H = 26, lo = Math.min(...values), hi = Math.max(...values), span = hi - lo || 1;
  const pts = values.map((v, i) => `${(i * W) / (values.length - 1)},${H - 3 - ((v - lo) / span) * (H - 6)}`).join(" ");
  return <svg viewBox={`0 0 ${W} ${H}`} style={{ width: 100, height: 26, display: "block", marginTop: 6 }} aria-hidden>
    <polyline points={pts} fill="none" stroke="var(--s1)" strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />
  </svg>;
}
