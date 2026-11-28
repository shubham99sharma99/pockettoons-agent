"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { API_URL } from "@/lib/api";

type State = "checking" | "ready" | "asleep" | "waking" | "down";

/** Pings GET /health. Any request wakes a sleeping free-tier Render instance. */
async function ping(timeoutMs: number): Promise<boolean> {
  const ctl = new AbortController();
  const t = setTimeout(() => ctl.abort(), timeoutMs);
  try {
    const r = await fetch(`${API_URL}/health`, { cache: "no-store", signal: ctl.signal });
    return r.ok;
  } catch {
    return false;
  } finally {
    clearTimeout(t);
  }
}

const WAKE_LIMIT_S = 150;

export default function ServerStatus() {
  const [state, setState] = useState<State>("checking");
  const [elapsed, setElapsed] = useState(0);
  const cancelled = useRef(false);

  const wake = useCallback(async () => {
    setState("waking");
    setElapsed(0);
    const t0 = Date.now();
    const tick = setInterval(() => setElapsed(Math.round((Date.now() - t0) / 1000)), 1000);
    try {
      while (!cancelled.current && (Date.now() - t0) / 1000 < WAKE_LIMIT_S) {
        if (await ping(20000)) { setState("ready"); return; }
        await new Promise((res) => setTimeout(res, 3000));
      }
      if (!cancelled.current) setState("down");
    } finally {
      clearInterval(tick);
    }
  }, []);

  useEffect(() => {
    cancelled.current = false;
    ping(5000).then((ok) => { if (!cancelled.current) setState(ok ? "ready" : "asleep"); });
    return () => { cancelled.current = true; };
  }, []);

  const label = {
    checking: "Checking server…",
    ready: "Server ready",
    asleep: "Server asleep",
    waking: `Waking server… ${elapsed}s`,
    down: "Server not responding",
  }[state];

  return (
    <span className="server-status" role="status" aria-live="polite">
      <i className={`dot ${state}`} aria-hidden />
      <span>{label}</span>
      {(state === "asleep" || state === "down") && (
        <button className="ghost small" onClick={wake}>{state === "down" ? "Try again" : "Wake server"}</button>
      )}
      {state === "ready" && (
        <button className="ghost small" onClick={() => { setState("checking"); ping(8000).then((ok) => setState(ok ? "ready" : "asleep")); }}
          title="Check the API again">Recheck</button>
      )}
    </span>
  );
}
