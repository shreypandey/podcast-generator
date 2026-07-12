// In-browser mock backend: simulates the whole pipeline (staged progress + live events) and
// serves the enhanced contract, so the entire UI is demonstrable with VITE_USE_MOCK=1 and no
// server. Uses the real mRNA run's multilingual data; synthesizes a plausible episode for any
// other topic.
import { ApiErr, type Backend, type WatchHandlers } from "./backend";
import { lang as langMeta } from "./languages";
import {
  MRNA_CAST, MRNA_CITATIONS, MRNA_SOURCES, MRNA_TRANSCRIPT_SOURCES, mrnaTurns,
} from "./mockData";
import { makeToneWavDataUri } from "./wav";
import type {
  Cast, CitationDetail, Citation, CreateRunRequest, Metrics, Progress,
  RunDetail, RunEvent, RunLanguages, RunStatus, RunSummary, SourceItem, Stage,
  TranscriptResponse, TranscriptTurn,
} from "./types";

const TONE = makeToneWavDataUri(9, 174);
const nowIso = () => new Date().toISOString();

interface Episode {
  cast: Cast;
  sources: SourceItem[];
  transcriptSources: Citation[];
  citations: CitationDetail[];
  turnsByLang: (lang: string) => TranscriptTurn[];
  turnCount: number;
}

function isMrna(topic: string): boolean {
  const t = topic.toLowerCase();
  return t.includes("mrna") || t.includes("vaccine");
}

// --- synthetic episode for arbitrary topics -------------------------------------------------
function synthEpisode(topic: string): Episode {
  const cast: Cast = {
    host: { name: "Maya", background: "curious generalist host", gender: "female", voice: "priya" },
    expert: { name: "Dr. Rao", background: `specialist on ${topic}`, gender: "male", voice: "aditya" },
  };
  const sources: SourceItem[] = [
    { id: "S1", title: `${topic}: an overview`, url: "https://example.org/overview", origin: "exa",
      query_ids: ["Q1"], query_intents: ["core_explainer"], search_rank: 1, quality_score: 0.9,
      fact_ids: ["F1", "F2"], snippet: `A grounded primer on ${topic}.` },
    { id: "S2", title: `Recent findings on ${topic}`, url: "https://example.org/findings", origin: "exa",
      query_ids: ["Q2"], query_intents: ["recent_current"], search_rank: 2, quality_score: 0.78,
      fact_ids: ["F3"], snippet: `New data reshaping how we think about ${topic}.` },
  ];
  const citations: CitationDetail[] = [
    { number: 1, fact_id: "F2", source_id: "S1", source_title: sources[0].title,
      source_url: sources[0].url, quote: `The core mechanism behind ${topic} is well established.` },
    { number: 2, fact_id: "F3", source_id: "S2", source_title: sources[1].title,
      source_url: sources[1].url, quote: `Recent studies report notable, if debated, effects.` },
  ];
  const base: Array<[TranscriptTurn["speaker"], string, string, boolean, number[]]> = [
    ["host", "intro", `Welcome! Today we're digging into ${topic} — and why it matters more than you'd think.`, true, []],
    ["expert", "intro", `Glad to be here. It's a genuinely fascinating area, so let's get into it.`, true, []],
    ["host", "ask", `Let's start simple — what's actually going on under the hood here?`, true, []],
    ["expert", "explain", `At its core, the mechanism is surprisingly elegant, and it's well documented.`, true, [1]],
    ["host", "challenge", `That's the clean story — but how solid is the evidence when you push on it?`, true, []],
    ["expert", "explain", `Fair. The recent findings are promising, though I'd call them still contested.`, false, [2]],
    ["expert", "outro", `So the takeaway: real progress, real open questions — that's what makes it exciting.`, true, []],
    ["host", "outro", `Thanks for walking us through it. And thanks all for listening — stay curious!`, true, []],
  ];
  const turns: TranscriptTurn[] = base.map(([speaker, move, text, verified, cites], idx) => ({
    idx, speaker, move, text, spoken: text, verified,
    speaker_name: speaker === "host" ? cast.host.name : cast.expert.name,
    citation_numbers: cites,
  }));
  return {
    cast, sources, transcriptSources: citations.map((c) => ({
      number: c.number, id: c.source_id, title: c.source_title, url: c.source_url,
    })),
    citations, turnsByLang: () => turns, turnCount: turns.length,
  };
}

function mrnaEpisode(): Episode {
  return {
    cast: MRNA_CAST,
    sources: MRNA_SOURCES,
    transcriptSources: MRNA_TRANSCRIPT_SOURCES,
    citations: MRNA_CITATIONS,
    turnsByLang: mrnaTurns,
    turnCount: mrnaTurns("en-IN").length,
  };
}

// --- one simulated run ----------------------------------------------------------------------
interface Sched {
  at: number; // ms from startedAt
  stage: Stage;
  ev: Omit<RunEvent, "event_id" | "ts">;
  progress?: Progress;
}

interface MockRun {
  id: string;
  req: CreateRunRequest;
  createdAt: string;
  startedAt: number; // epoch ms
  episode: Episode;
  langs: string[];
  sched: Sched[];
  totalMs: number;
  renderDoneAt: Map<string, number>; // lang -> ms offset ready
  forced?: { status: RunStatus; atElapsed: number; error?: string };
}

function buildSchedule(ep: Episode, langs: string[]): { sched: Sched[]; total: number; renderDoneAt: Map<string, number> } {
  const s: Sched[] = [];
  const nSrc = ep.sources.length;
  const nTurns = ep.turnCount;
  s.push({ at: 0, stage: "created", ev: { stage: "created", kind: "run.created", status: "running", message: "Run created" } });
  s.push({ at: 500, stage: "query_plan", ev: { stage: "query_plan", kind: "queries_planned", status: "running", message: "Planned search queries", payload: { n_queries: 4 } } });
  s.push({ at: 1300, stage: "research", ev: { stage: "research", kind: "sources_found", status: "running", message: `Found ${nSrc} sources`, payload: { sources_found: nSrc } } });
  // grounding, one event per source
  for (let i = 0; i < nSrc; i++) {
    const sid = ep.sources[i].id;
    s.push({
      at: 2000 + i * 700, stage: "ground",
      ev: { stage: "ground", kind: "source_done", status: "running", message: `Grounded source ${sid}`,
        payload: { source_id: sid, sources_done: i + 1, sources_total: nSrc, facts_so_far: (i + 1) * 4 } },
      progress: { current: i + 1, total: nSrc, label: `Grounding source ${i + 1} of ${nSrc}` },
    });
  }
  const gEnd = 2000 + nSrc * 700;
  s.push({ at: gEnd + 300, stage: "annotate", ev: { stage: "annotate", kind: "tension_annotated", status: "running", message: "Annotated fact tension" } });
  s.push({ at: gEnd + 900, stage: "cast", ev: { stage: "cast", kind: "cast_ready", status: "running", message: `Cast ${ep.cast.host.name} & ${ep.cast.expert.name}` } });
  s.push({ at: gEnd + 1500, stage: "plan", ev: { stage: "plan", kind: "outline_ready", status: "running", message: "Planned episode outline" } });
  // dialogue, one event per turn
  const dStart = gEnd + 2200;
  const enTurns = ep.turnsByLang("en-IN");
  for (let i = 0; i < nTurns; i++) {
    const t = enTurns[i];
    s.push({
      at: dStart + i * 520, stage: "dialogue",
      ev: { stage: "dialogue", kind: "turn_done", status: "running", message: `${t.speaker === "host" ? ep.cast.host.name : ep.cast.expert.name}: ${t.move}`,
        payload: { turns_done: i + 1, turns_total: nTurns, speaker: t.speaker, move: t.move } },
      progress: { current: i + 1, total: nTurns, label: `Writing dialogue (${i + 1}/${nTurns})` },
    });
  }
  const dEnd = dStart + nTurns * 520;
  s.push({ at: dEnd + 400, stage: "verify", ev: { stage: "verify", kind: "grounding_metric", status: "running", message: "Verified expert claims" } });
  s.push({ at: dEnd + 1000, stage: "review", ev: { stage: "review", kind: "review_done", status: "running", message: "Reviewer panel pass" } });
  s.push({ at: dEnd + 1600, stage: "humanize", ev: { stage: "humanize", kind: "humanize_done", status: "running", message: "Humanized delivery" } });
  // render, one event per language
  const renderDoneAt = new Map<string, number>();
  const rStart = dEnd + 2200;
  langs.forEach((lc, i) => {
    const at = rStart + i * 1000;
    renderDoneAt.set(lc, at);
    s.push({
      at, stage: "render",
      ev: { stage: "render", kind: "language_rendered", status: "running", message: `Rendered ${langMeta(lc).label}`,
        payload: { lang: lc, languages_done: i + 1, languages_total: langs.length } },
      progress: { current: i + 1, total: langs.length, label: `Rendering ${langMeta(lc).label}` },
    });
  });
  const rEnd = rStart + langs.length * 1000;
  s.push({ at: rEnd + 200, stage: "citations", ev: { stage: "citations", kind: "citations_done", status: "running", message: "Attached citations" } });
  const total = rEnd + 700;
  s.push({ at: total, stage: "complete", ev: { stage: "complete", kind: "run.succeeded", status: "succeeded", message: "Episode ready" } });
  return { sched: s, total, renderDoneAt };
}

function groundingStats(ep: Episode) {
  const turns = ep.turnsByLang("en-IN");
  const body = turns.filter((t) => t.speaker === "expert" && t.move !== "intro" && t.move !== "outro");
  const verified = body.filter((t) => t.verified).length;
  const rate = body.length ? Math.round((verified / body.length) * 100) : 100;
  const unverified = turns.filter((t) => t.speaker === "expert" && !t.verified).length;
  const challenge = turns.filter((t) => t.move === "challenge").length;
  return { rate, unverified, challenge };
}

const store = new Map<string, MockRun>();
let seq = 0;
function newId(): string {
  const d = new Date();
  const p = (n: number) => String(n).padStart(2, "0");
  seq += 1;
  return `${d.getFullYear()}${p(d.getMonth() + 1)}${p(d.getDate())}-${p(d.getHours())}${p(d.getMinutes())}${p(d.getSeconds())}${seq}`;
}

function makeRun(req: CreateRunRequest, startOffsetMs = 0): MockRun {
  const ep = isMrna(req.topic) ? mrnaEpisode() : synthEpisode(req.topic);
  const langs = req.languages && req.languages.length ? req.languages : ["en-IN"];
  const { sched, total, renderDoneAt } = buildSchedule(ep, langs);
  const startedAt = Date.now() - startOffsetMs;
  return {
    id: newId(), req, createdAt: new Date(startedAt).toISOString(), startedAt,
    episode: ep, langs, sched, totalMs: total, renderDoneAt,
  };
}

function elapsed(mr: MockRun): number {
  return Date.now() - mr.startedAt;
}

function readiness(mr: MockRun, el: number): RunLanguages {
  const ready = mr.langs.filter((lc) => (mr.renderDoneAt.get(lc) ?? Infinity) <= el);
  return { requested: mr.langs, ready, primary: mr.langs[0] };
}

function computeDetail(mr: MockRun): RunDetail {
  const el = elapsed(mr);
  const { rate, unverified, challenge } = groundingStats(mr.episode);
  let status: RunStatus = "running";
  let stage: Stage = "created";
  let progress: Progress | undefined;

  // last scheduled step reached
  for (const step of mr.sched) {
    if (step.at <= el) {
      stage = step.stage;
      if (step.progress) progress = step.progress;
    }
  }

  if (mr.forced) {
    status = mr.forced.status;
  } else if (el >= mr.totalMs) {
    status = "succeeded";
    stage = "complete";
    progress = undefined;
  }

  const lr = readiness(mr, mr.forced ? mr.forced.atElapsed : el);
  const succeeded = status === "succeeded";
  const passedVerify = el >= (mr.sched.find((s) => s.stage === "verify")?.at ?? Infinity);
  const passedResearch = el >= (mr.sched.find((s) => s.stage === "research")?.at ?? Infinity);
  const passedDialogue = el >= (mr.sched.find((s) => s.stage === "verify")?.at ?? Infinity);
  const passedCast = el >= (mr.sched.find((s) => s.stage === "cast")?.at ?? Infinity);

  const duration_sec: Record<string, number | null> = {};
  for (const lc of mr.langs) {
    duration_sec[lc] = lr.ready.includes(lc) ? Math.round((150 + mr.episode.turnCount * 4) * 10) / 10 : null;
  }

  const metrics: Metrics = {
    grounding_rate: passedVerify || succeeded ? rate : null,
    source_count: passedResearch ? mr.episode.sources.length : null,
    turn_count: passedDialogue || succeeded ? mr.episode.turnCount : null,
    unverified_count: passedVerify || succeeded ? unverified : null,
    challenge_count: passedDialogue || succeeded ? challenge : null,
    duration_sec,
  };

  return {
    run_id: mr.id,
    topic: mr.req.topic,
    length: mr.req.length,
    depth: mr.req.depth,
    status,
    stage,
    created_at: mr.createdAt,
    started_at: mr.createdAt,
    finished_at: status === "succeeded" || status === "canceled" || status === "failed" ? nowIso() : null,
    error: mr.forced?.error ?? null,
    languages: lr,
    progress,
    cast: passedCast || succeeded ? mr.episode.cast : undefined,
    metrics,
    artifacts: {
      audio_url: succeeded ? `/api/runs/${mr.id}/audio` : null,
      transcript_url: succeeded ? `/api/runs/${mr.id}/transcript` : null,
      sources_url: passedResearch ? `/api/runs/${mr.id}/sources` : null,
      episode_url: succeeded ? `/api/runs/${mr.id}/episode` : null,
    },
  };
}

function toSummary(d: RunDetail): RunSummary {
  return {
    run_id: d.run_id, topic: d.topic, length: d.length, depth: d.depth,
    status: d.status, stage: d.stage, created_at: d.created_at, started_at: d.started_at,
    finished_at: d.finished_at, error: d.error, metrics: d.metrics, languages: d.languages,
  };
}

// seed a few finished runs so the dashboard isn't empty on first load
function seed() {
  if (store.size) return;
  const seeds: Array<[CreateRunRequest, number]> = [
    [{ topic: "how mRNA vaccines work", length: "short", depth: 3, languages: ["en-IN", "hi-IN", "ta-IN"] }, 3_600_000],
    [{ topic: "the economics of desalination", length: "medium", depth: 3, languages: ["en-IN"] }, 7_200_000],
    [{ topic: "why the sky is blue", length: "short", depth: 2, languages: ["en-IN", "hi-IN"] }, 86_400_000],
  ];
  for (const [req, ago] of seeds) {
    const mr = makeRun(req, ago + 60_000); // fully elapsed
    store.set(mr.id, mr);
  }
  // one failed run for the error-view path
  const failed = makeRun({ topic: "an intentionally broken topic", length: "short", depth: 1, languages: ["en-IN"] }, 5_400_000);
  failed.forced = { status: "failed", atElapsed: 3000, error: "Research stage failed: Exa returned no usable sources." };
  store.set(failed.id, failed);
}

async function tick() {
  // small artificial latency so loading states are visible
  await new Promise((r) => setTimeout(r, 120));
}

export const mockBackend: Backend = {
  async health() {
    return true;
  },

  async listRuns(limit = 20) {
    seed();
    await tick();
    return Array.from(store.values())
      .map(computeDetail)
      .sort((a, b) => (a.created_at < b.created_at ? 1 : -1))
      .slice(0, limit)
      .map(toSummary);
  },

  async getRun(id) {
    seed();
    await tick();
    const mr = store.get(id);
    if (!mr) throw new ApiErr(404, "not_found", "Run not found");
    return computeDetail(mr);
  },

  async createRun(req) {
    seed();
    await tick();
    const mr = makeRun(req, 0);
    store.set(mr.id, mr);
    return {
      run_id: mr.id,
      status: "queued",
      status_url: `/api/runs/${mr.id}`,
      events_url: `/api/runs/${mr.id}/events`,
    };
  },

  async cancelRun(id) {
    await tick();
    const mr = store.get(id);
    if (!mr) throw new ApiErr(404, "not_found", "Run not found");
    const d = computeDetail(mr);
    if (d.status !== "running" && d.status !== "queued")
      throw new ApiErr(409, "conflict", "Run is already finished");
    mr.forced = { status: "canceled", atElapsed: elapsed(mr) };
  },

  async getTranscript(id, lang) {
    await tick();
    const mr = store.get(id);
    if (!mr) throw new ApiErr(404, "not_found", "Run not found");
    const lc = lang || mr.langs[0];
    const d = computeDetail(mr);
    if (!d.languages?.ready.includes(lc))
      throw new ApiErr(409, "not_ready", `Transcript for ${lc} is not ready`);
    return {
      run_id: mr.id,
      topic: mr.req.topic,
      language: lc,
      cast: mr.episode.cast,
      turns: mr.episode.turnsByLang(lc),
      sources: mr.episode.transcriptSources,
      citations: mr.episode.citations,
    } satisfies TranscriptResponse;
  },

  async getSources(id) {
    await tick();
    const mr = store.get(id);
    if (!mr) throw new ApiErr(404, "not_found", "Run not found");
    const d = computeDetail(mr);
    if (!d.artifacts.sources_url) throw new ApiErr(409, "not_ready", "Sources are not ready");
    return { run_id: mr.id, sources: mr.episode.sources };
  },

  audioUrl(_id, _lang) {
    return TONE;
  },

  watchRun(id, h: WatchHandlers) {
    let stopped = false;
    let lastAt = -1;
    const mr = store.get(id);
    if (!mr) {
      h.onError?.(new ApiErr(404, "not_found", "Run not found"));
      return () => {};
    }
    let evId = 0;
    const timer = window.setInterval(() => {
      if (stopped) return;
      const el = mr.forced ? mr.forced.atElapsed : elapsed(mr);
      // fire newly-due events
      for (const step of mr.sched) {
        if (step.at > lastAt && step.at <= el) {
          if (mr.forced && step.at > mr.forced.atElapsed) continue;
          evId += 1;
          h.onEvent?.({ event_id: evId, ts: nowIso(), ...step.ev });
        }
      }
      lastAt = el;
      const d = computeDetail(mr);
      h.onState?.(d);
      if (mr.forced) {
        h.onEvent?.({
          event_id: ++evId, ts: nowIso(), stage: d.stage,
          kind: mr.forced.status === "canceled" ? "run.failed" : "run.failed",
          status: mr.forced.status, message: mr.forced.error ?? "Run canceled",
        });
        stopped = true;
        clearInterval(timer);
      } else if (d.status === "succeeded") {
        stopped = true;
        clearInterval(timer);
      }
    }, 300);

    return () => {
      stopped = true;
      clearInterval(timer);
    };
  },
};
