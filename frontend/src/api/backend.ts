// Shared Backend interface: both the real HTTP client and the in-browser mock implement it,
// so components never know which one they're talking to.
import type {
  AddLanguagesRequest, AddLanguagesResponse, CreateRunRequest, CreateRunResponse,
  RunDetail, RunEvent, RunSummary,
  SourcesResponse, TranscriptResponse,
} from "./types";

export class ApiErr extends Error {
  status: number;
  code: string;
  constructor(status: number, code: string, message: string) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

export interface WatchHandlers {
  onEvent?: (e: RunEvent) => void;
  onState?: (r: RunDetail) => void;
  onError?: (e: ApiErr) => void;
}

export interface Backend {
  health(): Promise<boolean>;
  listRuns(limit?: number): Promise<RunSummary[]>;
  getRun(id: string): Promise<RunDetail>;
  createRun(req: CreateRunRequest): Promise<CreateRunResponse>;
  addLanguages(id: string, req: AddLanguagesRequest): Promise<AddLanguagesResponse>;
  cancelRun(id: string): Promise<void>;
  getTranscript(id: string, lang?: string): Promise<TranscriptResponse>;
  getSources(id: string): Promise<SourcesResponse>;
  audioUrl(id: string, lang?: string): string;
  /** Subscribe to live status + events; returns an unsubscribe fn. */
  watchRun(id: string, h: WatchHandlers): () => void;
}

export const USE_MOCK =
  import.meta.env.VITE_USE_MOCK === "1" || import.meta.env.VITE_USE_MOCK === "true";
