// Real HTTP client against the FastAPI backend (same-origin /api/*). Status comes from
// polling GET /api/runs/{id} (the documented fallback); live events use SSE when available.
import { ApiErr, type Backend, type WatchHandlers } from "./backend";
import type {
  CreateRunRequest, CreateRunResponse, RunDetail, RunEvent, RunSummary,
  SourcesResponse, TranscriptResponse,
} from "./types";

const TERMINAL = new Set(["succeeded", "failed", "canceled"]);

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(path, {
      ...init,
      headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
    });
  } catch {
    throw new ApiErr(0, "network_error", "Could not reach the server.");
  }
  if (!res.ok) {
    let code = "error";
    let message = `Request failed (${res.status})`;
    try {
      const body = await res.json();
      if (body?.error) {
        code = body.error.code ?? code;
        message = body.error.message ?? message;
      }
    } catch {
      /* non-JSON error body */
    }
    throw new ApiErr(res.status, code, message);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export const realBackend: Backend = {
  async health() {
    try {
      const r = await req<{ status: string }>("/api/health");
      return r.status === "healthy";
    } catch {
      return false;
    }
  },

  async listRuns(limit = 20) {
    const r = await req<{ runs: RunSummary[] }>(`/api/runs?limit=${limit}`);
    return r.runs;
  },

  getRun(id) {
    return req<RunDetail>(`/api/runs/${id}`);
  },

  createRun(body: CreateRunRequest) {
    return req<CreateRunResponse>("/api/runs", { method: "POST", body: JSON.stringify(body) });
  },

  async cancelRun(id) {
    await req(`/api/runs/${id}/cancel`, { method: "POST" });
  },

  getTranscript(id, lang) {
    const q = lang ? `?lang=${encodeURIComponent(lang)}` : "";
    return req<TranscriptResponse>(`/api/runs/${id}/transcript${q}`);
  },

  getSources(id) {
    return req<SourcesResponse>(`/api/runs/${id}/sources`);
  },

  audioUrl(id, lang) {
    const q = lang ? `?lang=${encodeURIComponent(lang)}` : "";
    return `/api/runs/${id}/audio${q}`;
  },

  watchRun(id, h: WatchHandlers) {
    let stopped = false;
    let timer: number | undefined;

    const poll = async () => {
      if (stopped) return;
      try {
        const detail = await this.getRun(id);
        if (stopped) return;
        h.onState?.(detail);
        if (TERMINAL.has(detail.status)) {
          stop();
          return;
        }
      } catch (e) {
        if (e instanceof ApiErr) h.onError?.(e);
      }
      timer = window.setTimeout(poll, 1500);
    };

    // Best-effort SSE for the live event feed; polling drives authoritative state.
    let es: EventSource | undefined;
    try {
      es = new EventSource(`/api/runs/${id}/events`);
      es.onmessage = (ev) => {
        try {
          h.onEvent?.(JSON.parse(ev.data) as RunEvent);
        } catch {
          /* ignore malformed event */
        }
      };
      es.onerror = () => es?.close();
    } catch {
      /* SSE unsupported; polling still works */
    }

    const stop = () => {
      stopped = true;
      if (timer) clearTimeout(timer);
      es?.close();
    };

    poll();
    return stop;
  },
};
