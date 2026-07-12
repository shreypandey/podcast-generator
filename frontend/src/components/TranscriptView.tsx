import { useEffect, useState } from "react";
import type { CitationDetail, TranscriptResponse } from "../api";
import { Avatar } from "./common";

interface PopState {
  cite: CitationDetail | { number: number; source_title: string; source_url: string; quote?: string };
  x: number;
  y: number;
}

export function TranscriptView({ data }: { data: TranscriptResponse }) {
  const [pop, setPop] = useState<PopState | null>(null);
  const [showEnglish, setShowEnglish] = useState(false);
  const isEnglish = (data.language ?? "en-IN") === "en-IN";

  // number -> rich citation (quote) or fallback to compact source link
  const byNumber = new Map<number, PopState["cite"]>();
  for (const s of data.sources) {
    byNumber.set(s.number, { number: s.number, source_title: s.title, source_url: s.url });
  }
  for (const c of data.citations ?? []) byNumber.set(c.number, c);

  useEffect(() => {
    if (!pop) return;
    const close = () => setPop(null);
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && close();
    window.addEventListener("scroll", close, true);
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("scroll", close, true);
      window.removeEventListener("keydown", onKey);
    };
  }, [pop]);

  const openCite = (e: React.MouseEvent, n: number) => {
    e.stopPropagation();
    const cite = byNumber.get(n);
    if (!cite) return;
    const r = (e.target as HTMLElement).getBoundingClientRect();
    const x = Math.min(r.left, window.innerWidth - 380);
    const y = r.bottom + 8;
    setPop({ cite, x: Math.max(12, x), y });
  };

  return (
    <div onClick={() => setPop(null)}>
      <div className="row" style={{ justifyContent: "space-between", marginBottom: 8 }}>
        <div className="section-title">Transcript</div>
        {!isEnglish && (
          <button className="btn ghost sm" onClick={() => setShowEnglish((v) => !v)}>
            {showEnglish ? "Hide English" : "Show original English"}
          </button>
        )}
      </div>

      <div className="transcript">
        {data.turns.map((t) => (
          <div key={t.idx} className={`turn ${t.speaker}`}>
            <Avatar name={t.speaker_name} role={t.speaker} />
            <div className="grow">
              <div className="who">
                <span className="name">{t.speaker_name}</span>
                {t.move && t.move !== "intro" && t.move !== "outro" && (
                  <span className={`badge move ${t.move === "challenge" ? "challenge" : "soft"}`}>{t.move}</span>
                )}
                {!t.verified && (
                  <span
                    className="unverified-tag"
                    title="This expert claim reaches beyond the cited evidence. Shown honestly rather than hidden (accept-and-flag)."
                  >
                    unverified
                  </span>
                )}
              </div>
              <div className="say">
                {t.spoken || t.text}
                {t.citation_numbers.map((n) => (
                  <span key={n} className="cite" onClick={(e) => openCite(e, n)} role="button" tabIndex={0}>
                    {n}
                  </span>
                ))}
                {!isEnglish && showEnglish && <span className="en-orig">EN · {t.text}</span>}
              </div>
            </div>
          </div>
        ))}
      </div>

      {pop && (
        <div className="pop" style={{ left: pop.x, top: pop.y }} onClick={(e) => e.stopPropagation()}>
          <div className="card">
            <div className="eyebrow" style={{ marginBottom: 8 }}>Source [{pop.cite.number}]</div>
            {"quote" in pop.cite && pop.cite.quote ? (
              <div className="q">“{pop.cite.quote}”</div>
            ) : (
              <div className="muted" style={{ fontSize: 13 }}>Cited from this source.</div>
            )}
            <div className="src">
              <span>↳</span>
              <a href={pop.cite.source_url} target="_blank" rel="noreferrer">
                {pop.cite.source_title}
              </a>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
