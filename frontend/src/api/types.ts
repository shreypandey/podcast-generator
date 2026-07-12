// Types for the backend contract (API_REQUIREMENTS.md) plus the frontend-requested
// enhancements in API_CONTRACT_REVIEW.md. Fields the backend may not implement yet are
// marked optional so the UI degrades gracefully (feature-checks, not hard dependencies).

export type RunStatus = "queued" | "running" | "succeeded" | "failed" | "canceled";

export type Stage =
  | "created" | "query_plan" | "research" | "ground" | "annotate" | "cast"
  | "plan" | "dialogue" | "verify" | "review" | "humanize" | "render"
  | "citations" | "complete" | "failed";

export type Length = "short" | "medium" | "long";

export interface Progress {
  current: number;
  total: number;
  label: string;
}

export interface Metrics {
  grounding_rate: number | null;
  source_count: number | null;
  turn_count: number | null;
  unverified_count?: number | null;
  challenge_count?: number | null;
  // per-language map, e.g. { "en-IN": 171.5, "hi-IN": null }
  duration_sec?: Record<string, number | null>;
}

export interface Persona {
  name: string;
  background: string;
  gender?: string;
  voice?: string;
}
export interface Cast {
  host: Persona;
  expert: Persona;
}

// requested: language dimension on the run (P0 #1)
export interface RunLanguages {
  requested: string[];
  ready: string[];
  primary: string;
}

export interface RunSummary {
  run_id: string;
  topic: string;
  length: Length;
  depth: number;
  status: RunStatus;
  stage: Stage;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  error: string | null;
  metrics?: Metrics;
  languages?: RunLanguages;
}

export interface RunDetail extends RunSummary {
  progress?: Progress;
  metrics: Metrics;
  cast?: Cast; // requested (P1 #4)
  artifacts: {
    audio_url: string | null;
    transcript_url: string | null;
    sources_url: string | null;
    episode_url?: string | null;
  };
}

export interface CreateRunRequest {
  topic: string;
  length: Length;
  depth: number;
  languages?: string[]; // requested (P0 #1)
  focus_questions?: string[]; // requested (P2 #10)
  tone?: string;
}

export interface CreateRunResponse {
  run_id: string;
  status: RunStatus;
  status_url: string;
  events_url: string;
}

export interface AddLanguagesRequest {
  languages: string[];
}

export interface AddLanguagesResponse {
  run_id: string;
  status: RunStatus;
  languages: RunLanguages;
  queued_languages?: string[];
}

// SSE / poll event
export interface RunEvent {
  event_id: number;
  ts: string;
  stage: Stage;
  kind: string;
  status: RunStatus;
  message: string;
  payload?: Record<string, unknown>;
}

// transcript — the compact source-link list (transcript.sources[])
export interface Citation {
  number: number;
  id: string; // source id, e.g. S1
  title: string;
  url: string;
}

// transcript.citations[] — the rich, quote-bearing form (P1 #3, now in the contract)
export interface CitationDetail {
  number: number;
  fact_id?: string;
  source_id: string;
  source_title: string;
  source_url: string;
  quote: string;
}

export interface TranscriptTurn {
  idx: number;
  speaker: "host" | "expert";
  speaker_name: string;
  text: string;
  spoken: string;
  move: string;
  verified: boolean;
  citation_numbers: number[];
  // requested (P1 #6 timing, optional): enables audio<->transcript sync
  t_start?: number;
  t_end?: number;
}

export interface TranscriptResponse {
  run_id: string;
  topic: string;
  language?: string;
  turns: TranscriptTurn[];
  sources: Citation[];
  citations?: CitationDetail[]; // rich quotes, keyed by citation number
  cast?: Cast;
}

export interface SourceItem {
  id: string;
  title: string;
  url: string;
  origin: string;
  query_ids: string[];
  query_intents: string[];
  // requested (P2 #8)
  search_rank?: number;
  snippet?: string;
  quality_score?: number;
  fact_ids?: string[];
}

export interface SourcesResponse {
  run_id: string;
  sources: SourceItem[];
}

export interface ApiError {
  error: { code: string; message: string; details?: unknown };
}
