import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, ApiErr } from "../api";
import type { CreateRunRequest, Length } from "../api";
import { LANGUAGES } from "../api/languages";

const LENGTHS: { value: Length; label: string; hint: string }[] = [
  { value: "short", label: "Short", hint: "~6 turns" },
  { value: "medium", label: "Medium", hint: "~10 turns" },
  { value: "long", label: "Long", hint: "~16 turns" },
];

const DEPTH_LABEL = ["", "Skim", "Light", "Balanced", "Deep", "Exhaustive"];

export function CreateRunForm() {
  const nav = useNavigate();
  const [topic, setTopic] = useState("");
  const [length, setLength] = useState<Length>("medium");
  const [depth, setDepth] = useState(3);
  const [langs, setLangs] = useState<string[]>(["en-IN"]);
  const [tone, setTone] = useState("");
  const [focus, setFocus] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const toggleLang = (code: string) => {
    setLangs((prev) =>
      prev.includes(code)
        ? prev.length === 1
          ? prev // keep at least one
          : prev.filter((c) => c !== code)
        : [...prev, code]
    );
  };

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!topic.trim()) {
      setErr("Enter a topic to get started.");
      return;
    }
    setBusy(true);
    setErr(null);
    const body: CreateRunRequest = {
      topic: topic.trim(),
      length,
      depth,
      languages: langs,
    };
    const fq = focus.split("\n").map((s) => s.trim()).filter(Boolean);
    if (fq.length) body.focus_questions = fq;
    if (tone.trim()) body.tone = tone.trim();
    try {
      const res = await api.createRun(body);
      nav(`/runs/${res.run_id}`);
    } catch (e) {
      setErr(e instanceof ApiErr ? e.message : "Failed to start the run.");
      setBusy(false);
    }
  };

  return (
    <form className="card pad stack" onSubmit={submit} style={{ gap: 20 }}>
      <div className="field">
        <label htmlFor="topic">Topic</label>
        <textarea
          id="topic"
          className="input"
          placeholder="e.g. how mRNA vaccines work, the economics of desalination…"
          value={topic}
          onChange={(e) => setTopic(e.target.value)}
          rows={2}
          autoFocus
        />
        <span className="hint">
          A grounded, two-host debate is researched, written, verified, and voiced for you.
        </span>
      </div>

      <div className="row wrap" style={{ gap: 28, alignItems: "flex-start" }}>
        <div className="field">
          <label>Length</label>
          <div className="segmented" role="group" aria-label="Episode length">
            {LENGTHS.map((l) => (
              <button
                key={l.value}
                type="button"
                aria-pressed={length === l.value}
                onClick={() => setLength(l.value)}
                title={l.hint}
              >
                {l.label}
              </button>
            ))}
          </div>
        </div>

        <div className="field grow" style={{ minWidth: 220 }}>
          <label htmlFor="depth">
            Research depth · <span className="muted">{DEPTH_LABEL[depth]}</span>
          </label>
          <div className="slider-row">
            <input
              id="depth"
              type="range"
              min={1}
              max={5}
              value={depth}
              onChange={(e) => setDepth(Number(e.target.value))}
            />
            <span className="mono" style={{ width: 18, textAlign: "center", fontWeight: 700 }}>
              {depth}
            </span>
          </div>
          <span className="hint">More depth = more sources and facts, longer run.</span>
        </div>
      </div>

      <div className="field">
        <label>Languages <span className="muted">· {langs.length} selected</span></label>
        <div className="chips">
          {LANGUAGES.map((l) => {
            const on = langs.includes(l.code);
            return (
              <button
                key={l.code}
                type="button"
                className="chip"
                aria-pressed={on}
                onClick={() => toggleLang(l.code)}
              >
                <span className="flag">{l.flag}</span>
                {l.label}
                <span className="faint" style={{ fontWeight: 500 }}>{l.native}</span>
                {on && <span className="check">✓</span>}
              </button>
            );
          })}
        </div>
        <span className="hint">
          One debate is written in English, then translated & voiced per language.
        </span>
      </div>

      <details className="adv">
        <summary>Advanced steering</summary>
        <div className="stack" style={{ marginTop: 14 }}>
          <div className="field">
            <label htmlFor="tone">Tone</label>
            <input
              id="tone"
              className="input"
              placeholder="e.g. curious and rigorous, warm and plain-spoken…"
              value={tone}
              onChange={(e) => setTone(e.target.value)}
            />
          </div>
          <div className="field">
            <label htmlFor="focus">Focus questions <span className="muted">(one per line)</span></label>
            <textarea
              id="focus"
              className="input"
              placeholder={"What are the tradeoffs?\nWhat does the evidence actually show?"}
              value={focus}
              onChange={(e) => setFocus(e.target.value)}
              rows={3}
            />
          </div>
          <span className="hint">
            Steering fields are sent when the backend supports them; ignored otherwise.
          </span>
        </div>
      </details>

      {err && <div className="banner err">⚠ {err}</div>}

      <button className="btn primary lg" type="submit" disabled={busy}>
        {busy ? "Starting…" : "Generate episode →"}
      </button>
    </form>
  );
}
