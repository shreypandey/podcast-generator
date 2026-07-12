import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, ApiErr } from "../api";
import type { SourceItem, TranscriptResponse } from "../api";
import { LANGUAGES, lang as langMeta } from "../api/languages";
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
  const { detail, error, refresh } = useRunWatch(runId);

  const [activeLang, setActiveLang] = useState("");
  const [selectedAddLang, setSelectedAddLang] = useState("");
  const [pendingSelectLang, setPendingSelectLang] = useState("");
  const [transcripts, setTranscripts] = useState<Record<string, TranscriptResponse>>({});
  const [sources, setSources] = useState<SourceItem[] | null>(null);
  const [tab, setTab] = useState<"transcript" | "sources">("transcript");
  const [canceling, setCanceling] = useState(false);
  const [addingLanguage, setAddingLanguage] = useState(false);
  const [addLanguageError, setAddLanguageError] = useState<string | null>(null);

  const running = detail?.status === "running" || detail?.status === "queued";
  const succeeded = detail?.status === "succeeded";
  const requestedLanguages = detail?.languages?.requested ?? [];
  const readyLanguages = detail?.languages?.ready ?? [];
  const pendingLanguages = requestedLanguages.filter((code) => !readyLanguages.includes(code));
  const addableLanguages = useMemo(
    () => LANGUAGES.filter((language) => !requestedLanguages.includes(language.code)),
    [requestedLanguages]
  );

  // pick default language once we know the run's primary
  useEffect(() => {
    if (!activeLang && detail?.languages?.primary) setActiveLang(detail.languages.primary);
  }, [detail?.languages?.primary, activeLang]);

  useEffect(() => {
    if (!selectedAddLang || !addableLanguages.some((language) => language.code === selectedAddLang)) {
      setSelectedAddLang(addableLanguages[0]?.code ?? "");
    }
  }, [addableLanguages, selectedAddLang]);

  useEffect(() => {
    if (!succeeded || pendingLanguages.length === 0) return;
    const timer = window.setInterval(() => {
      refresh();
    }, 2000);
    return () => window.clearInterval(timer);
  }, [succeeded, pendingLanguages.length, refresh]);

  useEffect(() => {
    if (!pendingSelectLang || !readyLanguages.includes(pendingSelectLang)) return;
    setActiveLang(pendingSelectLang);
    setPendingSelectLang("");
  }, [pendingSelectLang, readyLanguages]);

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

  const addLanguage = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!runId || !selectedAddLang) return;
    setAddingLanguage(true);
    setAddLanguageError(null);
    try {
      await api.addLanguages(runId, { languages: [selectedAddLang] });
      setPendingSelectLang(selectedAddLang);
      await refresh();
    } catch (e) {
      setAddLanguageError(e instanceof ApiErr ? e.message : "Could not start language render.");
    } finally {
      setAddingLanguage(false);
    }
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
          {detail.languages && (
            <div className="language-tools">
              {detail.languages.requested.length > 1 && (
                <LanguageSwitcher
                  languages={detail.languages}
                  value={activeLang}
                  onChange={setActiveLang}
                />
              )}

              {addableLanguages.length > 0 && (
                <form className="add-language" onSubmit={addLanguage}>
                  <select
                    className="input"
                    value={selectedAddLang}
                    onChange={(e) => setSelectedAddLang(e.target.value)}
                    disabled={addingLanguage}
                    aria-label="Add language"
                  >
                    {addableLanguages.map((language) => (
                      <option key={language.code} value={language.code}>
                        {language.label}
                      </option>
                    ))}
                  </select>
                  <button className="btn sm" type="submit" disabled={addingLanguage || !selectedAddLang}>
                    {addingLanguage ? "Adding..." : "Add language"}
                  </button>
                </form>
              )}

              {pendingLanguages.length > 0 && (
                <div className="hint">
                  Rendering {pendingLanguages.map((code) => langMeta(code).label).join(", ")}
                </div>
              )}
              {addLanguageError && <div className="hint err-text">{addLanguageError}</div>}
            </div>
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
