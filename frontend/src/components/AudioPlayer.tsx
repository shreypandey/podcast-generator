import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import type { Cast } from "../api";
import { lang as meta } from "../api/languages";
import { fmtDuration } from "../lib/format";

export function AudioPlayer({
  runId,
  language,
  cast,
  topic,
}: {
  runId: string;
  language: string;
  cast?: Cast;
  topic: string;
}) {
  const ref = useRef<HTMLAudioElement>(null);
  const [playing, setPlaying] = useState(false);
  const [cur, setCur] = useState(0);
  const [dur, setDur] = useState(0);
  const src = api.audioUrl(runId, language);

  useEffect(() => {
    // reset transport when the language (and thus source) changes
    setPlaying(false);
    setCur(0);
  }, [src]);

  const toggle = () => {
    const a = ref.current;
    if (!a) return;
    if (a.paused) {
      void a.play();
    } else {
      a.pause();
    }
  };

  const seek = (v: number) => {
    const a = ref.current;
    if (a && isFinite(v)) {
      a.currentTime = v;
      setCur(v);
    }
  };

  const m = meta(language);

  return (
    <div className="card pad player">
      <audio
        ref={ref}
        src={src}
        preload="metadata"
        onPlay={() => setPlaying(true)}
        onPause={() => setPlaying(false)}
        onTimeUpdate={(e) => setCur(e.currentTarget.currentTime)}
        onLoadedMetadata={(e) => setDur(e.currentTarget.duration)}
        onEnded={() => setPlaying(false)}
      />
      <div className="head">
        <div className="art">🎙️</div>
        <div style={{ minWidth: 0 }}>
          <div style={{ fontWeight: 700, fontSize: 16, lineHeight: 1.25 }}>{topic}</div>
          <div className="muted" style={{ fontSize: 13 }}>
            {m.flag} {m.label}
            {cast && ` · ${cast.host.name} & ${cast.expert.name}`}
          </div>
        </div>
      </div>
      <div className="transport">
        <button className="play-btn" onClick={toggle} aria-label={playing ? "Pause" : "Play"}>
          {playing ? "❚❚" : "▶"}
        </button>
        <div className="scrub">
          <span className="time">{fmtDuration(cur)}</span>
          <input
            type="range"
            min={0}
            max={dur || 0}
            step={0.1}
            value={cur}
            onChange={(e) => seek(Number(e.target.value))}
            aria-label="Seek"
          />
          <span className="time">{fmtDuration(dur)}</span>
        </div>
      </div>
    </div>
  );
}
