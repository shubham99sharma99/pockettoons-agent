"use client";
import { useEffect, useMemo, useState } from "react";
import { getJSON } from "@/lib/api";

type Col = { name: string; type: string; description?: string };
type Table = { table: string; rows: number; description?: string; columns: Col[] };
type Rel = { from: string; from_column: string; to: string; to_column: string; cardinality: string; kind: string;
  orphan_rows?: number; distinct_values?: number; unmatched_values?: number };
type Relations = { layers: Record<string, string>; primary_keys: Record<string, string[]>; relations: Rel[]; lineage: Record<string, string[]> };

// Hand-placed layout: sources on the top row, marts below, users in the middle so most links are short.
const BOX_W = 230, HEAD = 30, ROW = 20, PAD = 8, GAP_Y = 254;
const POS: Record<string, [number, number]> = {
  content_catalog: [20, 20], marketing_spend: [20, 290],
  content_views: [320, 20], fct_user_day: [320, 290],
  users: [620, 20], fct_user_month: [620, 290],
  sessions: [920, 20], transactions: [920, 200], fct_transactions: [920, 450],
};
const W = 1170;

function boxH(t: Table) { return HEAD + t.columns.length * ROW + PAD; }
function rowY(t: Table, col: string) {
  const i = Math.max(0, t.columns.findIndex((c) => c.name === col));
  return POS[t.table][1] + HEAD + i * ROW + ROW / 2;
}

/** Path from the child's key row to the parent's key row, routed through column gaps. */
function edgePath(child: Table, ccol: string, parent: Table, pcol: string) {
  const [cx] = POS[child.table], [px] = POS[parent.table];
  const cy = rowY(child, ccol), py = rowY(parent, pcol);
  if (cx === px) {   // same column: loop out on the side that has a gap
    const side = cx + BOX_W, out = side + 34;
    return { d: `M${side},${cy} C${out},${cy} ${out},${py} ${side},${py}`, a: [side, cy, 1] as const, b: [side, py, 1] as const };
  }
  const right = cx < px;
  const sx = right ? cx + BOX_W : cx, ex = right ? px : px + BOX_W;
  if (Math.abs(cx - px) <= 300) {
    const m = (sx + ex) / 2;
    return { d: `M${sx},${cy} C${m},${cy} ${m},${py} ${ex},${py}`, a: [sx, cy, right ? 1 : -1] as const, b: [ex, py, right ? -1 : 1] as const };
  }
  // spans more than one column: go along the gap row between the top and bottom tables
  const g1 = sx + (right ? 30 : -30), g2 = ex + (right ? -30 : 30);
  return { d: `M${sx},${cy} H${g1} V${GAP_Y} H${g2} V${py} H${ex}`, a: [sx, cy, right ? 1 : -1] as const, b: [ex, py, right ? -1 : 1] as const };
}

/** Crow's foot (many) or bar (one) at an end point; dir is the direction the line leaves the box. */
function End({ x, y, dir, many }: { x: number; y: number; dir: number; many: boolean }) {
  const k = 12 * dir;
  return many
    ? <g><path d={`M${x + k},${y} L${x},${y - 6} M${x + k},${y} L${x},${y} M${x + k},${y} L${x},${y + 6}`} /><path d={`M${x + k + 3 * dir},${y - 6} V${y + 6}`} /></g>
    : <path d={`M${x + 6 * dir},${y - 6} V${y + 6} M${x + 10 * dir},${y - 6} V${y + 6}`} />;
}

export default function SchemaPage() {
  const [tables, setTables] = useState<Table[]>([]);
  const [rel, setRel] = useState<Relations | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [sel, setSel] = useState<string | null>("users");

  useEffect(() => {
    getJSON<{ tables: Table[] }>("/schema").then((s) => setTables(s.tables)).catch((e) => setErr(String(e)));
    getJSON<Relations>("/schema/relations").then(setRel).catch((e) => setErr(String(e)));
  }, []);

  const byName = useMemo(() => Object.fromEntries(tables.map((t) => [t.table, t])), [tables]);
  const placed = tables.filter((t) => POS[t.table]);
  const H = Math.max(400, ...placed.map((t) => POS[t.table][1] + boxH(t))) + 20;
  const fks = useMemo(() => {
    const m: Record<string, Set<string>> = {};
    rel?.relations.forEach((r) => { (m[r.from] ??= new Set()).add(r.from_column); });
    return m;
  }, [rel]);
  const linked = (t: string) => !sel || t === sel || !!rel?.relations.some((r) => (r.from === sel && r.to === t) || (r.to === sel && r.from === t));
  const selT = sel ? byName[sel] : null;

  return (
    <>
      <h1>Schema</h1>
      <p className="muted">How the tables the agent queries fit together. Lines run from a foreign key to the key it points at:
        a crow&apos;s foot marks the &quot;many&quot; side, a double bar the &quot;one&quot; side. Click a table to highlight its links.</p>
      {err && <p className="error">{err}</p>}

      <div className="legend" style={{ marginTop: 10 }}>
        <span><i style={{ background: "var(--s1)" }} />Source table (dbt staging)</span>
        <span><i style={{ background: "var(--s3)" }} />Mart (built by dbt from sources)</span>
        <span><b>PK</b> primary key · <b>FK</b> foreign key</span>
        <span>Dashed line: shared values, not a key</span>
      </div>

      {rel && placed.length > 0 && (
        <div className="panel wrap" style={{ padding: 8 }}>
          <svg viewBox={`0 0 ${W} ${H}`} style={{ width: "100%", minWidth: 900, display: "block" }} role="img" aria-label="Entity relationship diagram">
            <g fill="none" strokeWidth={1.5}>
              {rel.relations.map((r) => {
                const c = byName[r.from], p = byName[r.to];
                if (!c || !p || !POS[r.from] || !POS[r.to]) return null;
                const e = edgePath(c, r.from_column, p, r.to_column);
                const on = !sel || r.from === sel || r.to === sel;
                const stroke = on ? "var(--ink)" : "var(--line)";
                return (
                  <g key={`${r.from}.${r.from_column}`} stroke={stroke} opacity={on ? 0.85 : 0.6}>
                    <path d={e.d} strokeDasharray={r.kind.startsWith("logical") ? "5 4" : undefined} />
                    <End x={e.a[0]} y={e.a[1]} dir={e.a[2]} many={r.cardinality !== "one-to-one"} />
                    <End x={e.b[0]} y={e.b[1]} dir={e.b[2]} many={r.cardinality === "many-to-many"} />
                  </g>
                );
              })}
            </g>
            {placed.map((t) => {
              const [x, y] = POS[t.table];
              const mart = rel.layers[t.table] === "mart";
              const pk = new Set(rel.primary_keys[t.table] ?? []);
              const on = linked(t.table);
              return (
                <g key={t.table} transform={`translate(${x},${y})`} opacity={on ? 1 : 0.35} style={{ cursor: "pointer" }}
                  onClick={() => setSel(sel === t.table ? null : t.table)}>
                  <rect width={BOX_W} height={boxH(t)} rx={8} fill="var(--panel)" stroke={sel === t.table ? "var(--ink)" : "var(--line)"} strokeWidth={sel === t.table ? 2 : 1} />
                  <path d={`M0,8 a8,8 0 0 1 8,-8 h${BOX_W - 16} a8,8 0 0 1 8,8 v${HEAD - 8} h-${BOX_W} z`} fill={mart ? "var(--s3)" : "var(--s1)"} />
                  <text x={10} y={20} fontSize={13} fontWeight={650} fill="#fff">{t.table}</text>
                  <text x={BOX_W - 10} y={20} fontSize={11} fill="#fff" textAnchor="end">{t.rows.toLocaleString()} rows</text>
                  {t.columns.map((c, i) => {
                    const cy = HEAD + i * ROW + 14;
                    const tag = pk.has(c.name) ? "PK" : fks[t.table]?.has(c.name) ? "FK" : "";
                    return (
                      <g key={c.name}>
                        <title>{`${c.name} (${c.type})${c.description ? `: ${c.description}` : ""}`}</title>
                        <text x={10} y={cy} fontSize={10} fontWeight={700} fill="var(--muted)">{tag}</text>
                        <text x={32} y={cy} fontSize={12} fill="var(--ink)" fontWeight={tag === "PK" ? 650 : 400}>{c.name}</text>
                        <text x={BOX_W - 10} y={cy} fontSize={10.5} fill="var(--muted)" textAnchor="end">{c.type.toLowerCase()}</text>
                      </g>
                    );
                  })}
                </g>
              );
            })}
          </svg>
        </div>
      )}

      {selT && rel && (
        <div className="panel" style={{ marginTop: 12 }}>
          <h2 style={{ marginTop: 0 }}>{selT.table} <span className="muted" style={{ fontWeight: 400, fontSize: 14 }}>
            · {rel.layers[selT.table] === "mart" ? "mart" : "source"} · {selT.rows.toLocaleString()} rows · key ({(rel.primary_keys[selT.table] ?? []).join(", ")})</span></h2>
          {selT.description && <p style={{ marginTop: 0 }}>{selT.description}</p>}
          {rel.lineage[selT.table] && <p className="muted">Built by dbt from: {rel.lineage[selT.table].join(", ")}</p>}
          <div className="wrap">
            <table className="data">
              <thead><tr><th>Column</th><th>Type</th><th>Description</th></tr></thead>
              <tbody>{selT.columns.map((c) => <tr key={c.name}><td><code>{c.name}</code></td><td>{c.type}</td><td>{c.description}</td></tr>)}</tbody>
            </table>
          </div>
        </div>
      )}

      {rel && (
        <>
          <h2>Relationships and integrity checks</h2>
          <div className="panel wrap">
            <table className="data">
              <thead><tr><th>From</th><th>To</th><th>Cardinality</th><th>Type</th><th>Check (run live)</th></tr></thead>
              <tbody>{rel.relations.map((r) => {
                const ok = (r.orphan_rows ?? 0) === 0 && (r.unmatched_values ?? 0) === 0;
                return (
                  <tr key={`${r.from}.${r.from_column}`}>
                    <td><code>{r.from}.{r.from_column}</code></td><td><code>{r.to}.{r.to_column}</code></td>
                    <td>{r.cardinality}</td><td>{r.kind}</td>
                    <td><span className={`pill ${ok ? "pass" : "fail"}`}>{ok ? "holds" : "broken"}</span>{" "}
                      <span className="muted" style={{ fontSize: 13 }}>{r.orphan_rows !== undefined
                        ? `${r.orphan_rows.toLocaleString()} rows with no match`
                        : `${r.unmatched_values} of ${r.distinct_values} values with no match`}</span></td>
                  </tr>
                );
              })}</tbody>
            </table>
          </div>
          <p className="muted" style={{ fontSize: 13 }}>The full model docs, with column tests and lineage graphs, are in the dbt docs site
            (<code>dbt docs serve --port 8080</code> in <code>dbt/</code>, then <a href="http://localhost:8080" target="_blank" rel="noreferrer">localhost:8080</a>).</p>
        </>
      )}
    </>
  );
}
