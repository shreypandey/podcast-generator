import type { RunDetail, RunEvent, Stage } from "../api";
import { lang } from "../api/languages";

// The fine-grained backend stages, in order. These are internal; the UI never shows them raw.
const STAGE_ORDER: Stage[] = [
  "created", "query_plan", "research", "ground", "annotate", "cast", "plan",
  "dialogue", "verify", "review", "humanize", "render", "citations", "complete",
];

// User-facing phases. The many internal stages collapse into four steps a listener
// actually cares about. Within-phase granularity is shown by the progress bar, not the feed.
const GROUPS: { label: string; detail: string; stages: Stage[] }[] = [
  { label: "Collecting sources", detail: "Searching the web with Exa", stages: ["query_plan", "research"] },
  { label: "Extracting facts", detail: "Pulling out claims, each cited to a source", stages: ["ground", "annotate"] },
  {
    label: "Writing the script",
    detail: "Casting the hosts, then a fact-checked, turn-by-turn debate",
    stages: ["cast", "plan", "dialogue", "verify", "review", "humanize"],
  },
  { label: "Producing audio", detail: "Translating & voicing each language", stages: ["render", "citations"] },
];

function idx(stage: Stage): number {
  const i = STAGE_ORDER.indexOf(stage);
  return i < 0 ? 0 : i;
}

// Map raw pipeline events to the handful of plain-language milestones worth surfacing.
// Returns null for internal/per-item chatter (per-source, per-turn, reviewer passes, …) so the
// feed stays readable instead of scrolling technical noise.
function milestone(e: RunEvent): string | null {
  const p = (e.payload ?? {}) as Record<string, unknown>;
  switch (e.kind) {
    case "run.created":
      return "Started";
    case "queries_planned":
      return "Planned the research";
    case "sources_found":
      return p.sources_found ? `Found ${p.sources_found} sources` : "Gathered sources";
    case "source_done":
      // collapse per-source events into a single completion milestone
      return p.sources_done === p.sources_total ? `Read ${p.sources_total} sources for facts` : null;
    case "cast_ready":
      return e.message; // already friendly, e.g. "Cast Alex & Dr. Lena Petrova"
    case "outline_ready":
      return "Outlined the conversation";
    case "turn_done":
      // collapse per-turn events into a single completion milestone
      return p.turns_done === p.turns_total ? `Wrote the debate — ${p.turns_total} turns` : null;
    case "grounding_metric":
      return "Fact-checked every claim";
    case "language_rendered": {
      const code = p.lang ? String(p.lang) : "";
      return code ? `Voiced in ${lang(code).label}` : e.message;
    }
    case "run.succeeded":
      return "Episode ready";
    case "run.failed":
      return e.message;
    default:
      return null; // internal step — don't surface
  }
}

export function RunProgress({ detail, events }: { detail: RunDetail; events: RunEvent[] }) {
  const cur = idx(detail.stage);
  const done = detail.status === "succeeded";

  const feed = events
    .map((e) => ({ e, text: milestone(e) }))
    .filter((x): x is { e: RunEvent; text: string } => x.text != null);

  return (
    <div className="split">
      <div className="card pad">
        <div className="row" style={{ justifyContent: "space-between", marginBottom: 16 }}>
          <div className="section-title">Pipeline</div>
          {detail.progress && !done && (
            <span className="badge running"><span className="dot" />{detail.progress.label}</span>
          )}
        </div>
        <div className="timeline">
          {GROUPS.map((g, i) => {
            const first = idx(g.stages[0]);
            const last = idx(g.stages[g.stages.length - 1]);
            const state = done || cur > last ? "done" : cur >= first ? "active" : "pending";
            const showBar = state === "active" && detail.progress;
            return (
              <div key={g.label} className={`tl-step ${state}`}>
                <div className="tl-rail">
                  <div className="tl-node">
                    {state === "done" ? "✓" : state === "active" ? <span className="spin" /> : i + 1}
                  </div>
                  {i < GROUPS.length - 1 && <div className="tl-line" />}
                </div>
                <div className="tl-body">
                  <div className="tl-name">{g.label}</div>
                  <div className="tl-detail">{g.detail}</div>
                  {showBar && detail.progress && (
                    <div className="meter" style={{ maxWidth: 220 }}>
                      <span
                        style={{
                          width: `${Math.round((detail.progress.current / Math.max(1, detail.progress.total)) * 100)}%`,
                          background: "linear-gradient(90deg, var(--accent), #b06dfc)",
                        }}
                      />
                    </div>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </div>

      <div className="card pad">
        <div className="section-title" style={{ marginBottom: 12 }}>Activity</div>
        {feed.length === 0 ? (
          <div className="faint" style={{ fontSize: 13 }}>Getting started…</div>
        ) : (
          <div className="feed">
            {feed
              .slice()
              .reverse()
              .slice(0, 8)
              .map(({ e, text }, i) => (
                <div className="feed-line" key={`${e.event_id}-${i}`}>
                  <span className="tick">{e.status === "succeeded" ? "🎧" : "✓"}</span>
                  <span className="msg">{text}</span>
                </div>
              ))}
          </div>
        )}
      </div>
    </div>
  );
}
