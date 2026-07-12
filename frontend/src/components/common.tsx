import type { Cast, Metrics, RunStatus } from "../api";
import { fmtDuration, initials, titleCase } from "../lib/format";

export function StatusBadge({ status }: { status: RunStatus }) {
  return (
    <span className={`badge ${status}`}>
      <span className="dot" />
      {titleCase(status)}
    </span>
  );
}

export function Avatar({ name, role }: { name: string; role: "host" | "expert" }) {
  return (
    <span className="avatar" style={{ background: `var(--${role})` }}>
      {initials(name)}
    </span>
  );
}

export function CastRow({ cast }: { cast: Cast }) {
  return (
    <div className="cast">
      <div className="person host">
        <Avatar name={cast.host.name} role="host" />
        <div style={{ minWidth: 0 }}>
          <div className="nm">{cast.host.name}</div>
          <div className="rl">Host · {cast.host.background}</div>
        </div>
      </div>
      <div className="vs">VS</div>
      <div className="person expert">
        <Avatar name={cast.expert.name} role="expert" />
        <div style={{ minWidth: 0 }}>
          <div className="nm">{cast.expert.name}</div>
          <div className="rl">Expert · {cast.expert.background}</div>
        </div>
      </div>
    </div>
  );
}

export function GroundingStat({ metrics }: { metrics: Metrics }) {
  const rate = metrics.grounding_rate;
  const warn = rate != null && rate < 70;
  return (
    <div className="stat" style={{ flexBasis: "100%" }}>
      <div className="k">Grounding rate</div>
      <div className="v">
        {rate == null ? "—" : `${Math.round(rate)}%`}
        {metrics.unverified_count != null && metrics.unverified_count > 0 && (
          <small> · {metrics.unverified_count} flagged unverified</small>
        )}
      </div>
      {rate != null && (
        <div className={`meter ${warn ? "warn" : ""}`}>
          <span style={{ width: `${rate}%` }} />
        </div>
      )}
    </div>
  );
}

export function MetricStats({ metrics, primaryLang }: { metrics: Metrics; primaryLang?: string }) {
  const dur =
    metrics.duration_sec && primaryLang ? metrics.duration_sec[primaryLang] : null;
  return (
    <div className="stat-row">
      <div className="stat">
        <div className="k">Sources</div>
        <div className="v">{metrics.source_count ?? "—"}</div>
      </div>
      <div className="stat">
        <div className="k">Turns</div>
        <div className="v">{metrics.turn_count ?? "—"}</div>
      </div>
      <div className="stat">
        <div className="k">Challenges</div>
        <div className="v">{metrics.challenge_count ?? "—"}</div>
      </div>
      <div className="stat">
        <div className="k">Length</div>
        <div className="v">{fmtDuration(dur)}</div>
      </div>
    </div>
  );
}
