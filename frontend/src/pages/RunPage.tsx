import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api";
import type { SourceItem, TranscriptResponse } from "../api";
import { AudioPlayer } from "../components/AudioPlayer";
import { CastRow, StatusBadge } from "../components/common";
import { LanguageSwitcher } from "../components/LanguageSwitcher";
import { RunProgress } from "../components/RunProgress";
import { SourcesPanel } from "../components/SourcesPanel";
import { TranscriptView } from "../components/TranscriptView";
import { useRunWatch } from "../hooks/useRunWatch";
import { fmtRelative } from "../lib/format";

export function RunPage() {
  const { runId } = useParams<{ runId: string }>();
  const { detail, error } = useRunWatch(runId);

  const [activeLang, setActiveLang] = useState("");
  const [transcripts, setTranscripts] = useState<Record<string, TranscriptResponse>>({});
  const [sources, setSources] = useState<SourceItem[] | null>(null);
  const [tab, setTab] = useState<"transcript" | "sources">("transcript");
  const [canceling, setCanceling] = useState(false);

  const running = detail?.status === "running" || detail?.status === "queued";
  const succeeded = detail?.status === "succeeded";

  // pick default language once we know the run's primary
  useEffect(() => {
    if (!activeLang && detail?.languages?.primary) setActiveLang(detail.languages.primary);
  }, [detail?.languages?.primary, activeLang]);

  // load transcript for the active language when it becomes ready
  useEffect(() => {
    if (!runId || !activeLang) return;
    if (!detail?.languages?.ready.includes(activeLang)) return;
    if (transcripts[activeLang]) return;
    let alive = true;
    api
      .getTranscript(runId, activeLang)
      .then((t) => alive && setTranscripts((p) => ({ ...p, [activeLang]: t })))
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, [runId, activeLang, detail?.languages?.ready, transcripts]);

  // load sources once available
  useEffect(() => {
    if (!runId || sources || !detail?.artifacts.sources_url) return;
    let alive = true;
    api
      .getSources(runId)
      .then((r) => alive && setSources(r.sources))
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, [runId, sources, detail?.artifacts.sources_url]);

  const cancel = async () => {
    if (!runId) return;
    setCanceling(true);
    try {
      await api.cancelRun(runId);
    } catch {
      /* watch will reflect terminal state */
    }
    setCanceling(false);
  };

  const transcript = transcripts[activeLang];
  const cast = detail?.cast ?? transcript?.cast;

  const header = useMemo(
    () => (
      <div className="stack" style={{ gap: 14 }}>
        <Link to="/" className="link" style={{ fontSize: 13 }}>← All episodes</Link>
        <div className="row wrap" style={{ justifyContent: "space-between", gap: 12 }}>
          <div>
            <h1 style={{ fontSize: 26 }}>{detail?.topic ?? "Loading…"}</h1>
            {detail && (
              <div className="muted" style={{ fontSize: 13, marginTop: 4 }}>
                {detail.length} · depth {detail.depth} · started {fmtRelative(detail.created_at)}
              </div>
            )}
          </div>
          <div className="row">
            {detail && <StatusBadge status={detail.status} />}
            {running && (
              <button className="btn danger sm" onClick={cancel} disabled={canceling}>
                {canceling ? "Canceling…" : "Cancel"}
              </button>
            )}
          </div>
        </div>
      </div>
    ),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [detail, running, canceling]
  );

  if (error && error.status === 404) {
    return (
      <div className="container">
        {header}
        <div className="empty">
          <div className="big">🔍</div>
          Run not found. It may have been removed.
        </div>
      </div>
    );
  }

  if (!detail) {
    return (
      <div className="container">
        {header}
        <div className="empty"><div className="spinner-lg" style={{ margin: "0 auto" }} /></div>
      </div>
    );
  }

  return (
    <div className="container stack" style={{ gap: 24 }}>
      {header}

      {cast && (
        <div className="card pad">
          <CastRow cast={cast} />
        </div>
      )}

      {detail.status === "failed" && (
        <div className="banner err">
          ⚠ This run failed. {detail.error ?? "An unknown error occurred."}
        </div>
      )}

      {detail.status === "canceled" && (
        <div className="banner" style={{ background: "var(--surface-2)", color: "var(--text-muted)" }}>
          This run was canceled.
        </div>
      )}

      {running && <RunProgress detail={detail} />}

      {succeeded && (
        <>
          {detail.languages && detail.languages.requested.length > 1 && (
            <LanguageSwitcher
              languages={detail.languages}
              value={activeLang}
              onChange={setActiveLang}
            />
          )}

          {activeLang && (
            <AudioPlayer runId={detail.run_id} language={activeLang} cast={cast} topic={detail.topic} />
          )}

          <div className="card pad">
            <div className="tabs">
              <button
                className="tab"
                aria-selected={tab === "transcript"}
                onClick={() => setTab("transcript")}
              >
                Transcript
                {transcript && <span className="count">{transcript.turns.length}</span>}
              </button>
              <button
                className="tab"
                aria-selected={tab === "sources"}
                onClick={() => setTab("sources")}
              >
                Sources
                {sources && <span className="count">{sources.length}</span>}
              </button>
            </div>

            {tab === "transcript" &&
              (transcript ? (
                <TranscriptView data={transcript} />
              ) : (
                <div className="empty"><div className="spinner-lg" style={{ margin: "0 auto" }} /></div>
              ))}

            {tab === "sources" &&
              (sources ? (
                <SourcesPanel sources={sources} />
              ) : (
                <div className="empty faint">Sources not available.</div>
              ))}
          </div>
        </>
      )}
    </div>
  );
}
