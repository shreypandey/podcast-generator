import type { RunDetail, RunEvent, Stage } from "../api";

// The fine-grained backend stages, grouped into human-readable pipeline steps.
const STAGE_ORDER: Stage[] = [
  "created", "query_plan", "research", "ground", "annotate", "cast", "plan",
  "dialogue", "verify", "review", "humanize", "render", "citations", "complete",
];

const GROUPS: { label: string; detail: string; stages: Stage[] }[] = [
  { label: "Research", detail: "Planning queries & searching with Exa", stages: ["query_plan", "research"] },
  { label: "Grounding", detail: "Extracting cited facts & tension", stages: ["ground", "annotate"] },
  { label: "Casting & outline", detail: "Choosing the two hosts & arc", stages: ["cast", "plan"] },
  { label: "Writing the debate", detail: "Turn-by-turn, verified against sources", stages: ["dialogue", "verify", "review"] },
  { label: "Humanizing", detail: "Natural spoken delivery", stages: ["humanize"] },
  { label: "Rendering audio", detail: "Translate & voice per language", stages: ["render", "citations"] },
];

function idx(stage: Stage): number {
  const i = STAGE_ORDER.indexOf(stage);
  return i < 0 ? 0 : i;
}

export function RunProgress({ detail, events }: { detail: RunDetail; events: RunEvent[] }) {
  const cur = idx(detail.stage);
  const done = detail.status === "succeeded";

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
        <div className="section-title" style={{ marginBottom: 12 }}>Live activity</div>
        {events.length === 0 ? (
          <div className="faint" style={{ fontSize: 13 }}>Waiting for the first update…</div>
        ) : (
          <div className="feed">
            {[...events].reverse().map((e, i) => (
              <div className="feed-line" key={`${e.event_id}-${i}`}>
                <span className="t">{new Date(e.ts).toLocaleTimeString([], { hour12: false })}</span>
                <span className="s">{e.stage}</span>
                <span className="muted">{e.message}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
