import { useNavigate } from "react-router-dom";
import type { RunSummary } from "../api";
import { lang as meta } from "../api/languages";
import { fmtRelative } from "../lib/format";
import { StatusBadge } from "./common";

export function RunList({ runs }: { runs: RunSummary[] }) {
  const nav = useNavigate();
  if (runs.length === 0) {
    return (
      <div className="empty">
        <div className="big">🎧</div>
        No episodes yet. Generate your first one above.
      </div>
    );
  }
  return (
    <div className="grid-cards">
      {runs.map((r) => (
        <button className="card run-card" key={r.run_id} onClick={() => nav(`/runs/${r.run_id}`)}>
          <div className="row" style={{ justifyContent: "space-between" }}>
            <StatusBadge status={r.status} />
            <span className="faint" style={{ fontSize: 12 }}>{fmtRelative(r.created_at)}</span>
          </div>
          <div className="topic">{r.topic}</div>
          <div className="meta">
            <span>{r.length}</span>
            <span>·</span>
            <span>depth {r.depth}</span>
            {r.languages && (
              <>
                <span>·</span>
                <span>{r.languages.requested.map((c) => meta(c).flag).join(" ")}</span>
              </>
            )}
            {r.metrics?.grounding_rate != null && (
              <>
                <span>·</span>
                <span>{Math.round(r.metrics.grounding_rate)}% grounded</span>
              </>
            )}
          </div>
        </button>
      ))}
    </div>
  );
}
