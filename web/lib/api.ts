export const API_URL = (process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000").replace(/\/$/, "");

export type AgentEvent =
  | { type: "start"; question: string; model: string }
  | { type: "text"; text: string }
  | { type: "tool_call"; id: string; name: string; input: unknown }
  | { type: "tool_result"; id: string; name: string; query_id?: string; error?: string; summary: string }
  | { type: "answer"; answer: Answer | null; submitted: boolean }
  | { type: "error"; message: string }
  | { type: "done"; stop: string; tool_calls?: number; sql_calls?: number; latency_s?: number };

export interface Answer {
  answer_markdown: string;
  headline: string;
  headline_value: number | null;
  unit: string;
  confidence: string;
  query_ids: string[];
  assumptions: string[];
}

export async function getJSON<T>(path: string): Promise<T> {
  const r = await fetch(`${API_URL}${path}`, { cache: "no-store" });
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
  return r.json();
}

export async function postJSON<T>(path: string, body: unknown): Promise<T> {
  const r = await fetch(`${API_URL}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
  return r.json();
}

/** POST /ask and parse the Server-Sent Events stream (EventSource cannot POST). */
export async function ask(question: string, onEvent: (e: AgentEvent) => void, signal?: AbortSignal) {
  const r = await fetch(`${API_URL}/ask`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
    body: JSON.stringify({ question }),
    signal,
  });
  if (!r.ok || !r.body) {
    let msg = `${r.status}`;
    try { msg = (await r.json()).detail ?? msg; } catch { /* not json */ }
    throw new Error(msg);
  }
  const reader = r.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true }).replace(/\r\n/g, "\n");
    let idx;
    while ((idx = buf.indexOf("\n\n")) >= 0) {
      const chunk = buf.slice(0, idx);
      buf = buf.slice(idx + 2);
      const data = chunk.split("\n").filter((l) => l.startsWith("data:")).map((l) => l.slice(5).trim()).join("\n");
      if (!data || data === "{}") continue;
      try { onEvent(JSON.parse(data)); } catch { /* ignore malformed */ }
    }
  }
}
