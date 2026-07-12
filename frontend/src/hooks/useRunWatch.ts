import { useEffect, useRef, useState } from "react";
import { api, ApiErr } from "../api";
import type { RunDetail, RunEvent } from "../api";

// Subscribes to a run's live status + event feed via the active backend (mock or real).
export function useRunWatch(runId: string | undefined) {
  const [detail, setDetail] = useState<RunDetail | null>(null);
  const [events, setEvents] = useState<RunEvent[]>([]);
  const [error, setError] = useState<ApiErr | null>(null);
  const seen = useRef<Set<number>>(new Set());

  useEffect(() => {
    if (!runId) return;
    setDetail(null);
    setEvents([]);
    setError(null);
    seen.current = new Set();

    const stop = api.watchRun(runId, {
      onState: (d) => setDetail(d),
      onEvent: (e) => {
        // de-dupe (SSE + poll can overlap)
        const key = e.event_id || Date.now();
        if (seen.current.has(key)) return;
        seen.current.add(key);
        setEvents((prev) => [...prev, e]);
      },
      onError: (err) => setError(err),
    });
    return stop;
  }, [runId]);

  return { detail, events, error };
}
