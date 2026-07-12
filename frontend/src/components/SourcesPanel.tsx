import type { SourceItem } from "../api";

function hostname(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}

export function SourcesPanel({ sources }: { sources: SourceItem[] }) {
  return (
    <div className="stack" style={{ gap: 12 }}>
      <div className="section-title">
        Sources <span className="faint">· {sources.length}</span>
      </div>
      {sources.map((s, i) => (
        <div className="source-item" key={s.id}>
          <div className="num">{i + 1}</div>
          <div className="grow" style={{ minWidth: 0 }}>
            <a href={s.url} target="_blank" rel="noreferrer" className="title link" style={{ display: "block" }}>
              {s.title || hostname(s.url)}
            </a>
            <div className="url">{hostname(s.url)}</div>
            {s.snippet && (
              <div className="muted" style={{ fontSize: 13, marginTop: 6 }}>{s.snippet}</div>
            )}
            <div className="tags">
              <span className="tag">{s.origin}</span>
              {s.query_intents.map((q) => (
                <span className="tag" key={q}>{q.replace(/_/g, " ")}</span>
              ))}
              {typeof s.quality_score === "number" && (
                <span className="tag">quality {Math.round(s.quality_score * 100)}%</span>
              )}
              {s.fact_ids && s.fact_ids.length > 0 && (
                <span className="tag">{s.fact_ids.length} facts</span>
              )}
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}
