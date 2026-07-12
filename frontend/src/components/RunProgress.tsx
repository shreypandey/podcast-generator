import type { RunDetail, Stage } from "../api";

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

export function RunProgress({ detail }: { detail: RunDetail }) {
  const cur = idx(detail.stage);
  const done = detail.status === "succeeded";

  return (
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
  );
}
