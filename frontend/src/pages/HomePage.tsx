import { useEffect, useState } from "react";
import { api } from "../api";
import type { RunSummary } from "../api";
import { CreateRunForm } from "../components/CreateRunForm";
import { RunList } from "../components/RunList";

const FEATURES = [
  { icon: "⚖️", title: "Real debate", body: "A sharp host and a domain expert genuinely push on the evidence — not two agreeable narrators." },
  { icon: "🔎", title: "Verifiable grounding", body: "Every claim links to a source, with the exact supporting quote. Overreach is flagged, not hidden." },
  { icon: "🌐", title: "Multilingual", body: "One debate, voiced in English and 10 Indian languages — translated and spoken, not subtitled." },
  { icon: "🎚️", title: "Deep steering", body: "Set length, research depth, focus, and tone. The pipeline adapts sources, facts, and arc." },
];

export function HomePage() {
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let alive = true;
    api
      .listRuns(12)
      .then((r) => alive && setRuns(r))
      .catch(() => alive && setRuns([]))
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
  }, []);

  return (
    <div className="container stack" style={{ gap: 36 }}>
      <header className="stack" style={{ gap: 0, marginTop: 8 }}>
        <span className="eyebrow">Grounded audio, on any topic</span>
        <h1 className="hero-title">
          Turn a topic into a<br />two-host debate you can trust.
        </h1>
        <p className="hero-sub">
          Live research → grounded facts → a genuine expert debate → audio in your language —
          with every spoken claim traceable to a real source.
        </p>
      </header>

      <div className="split" style={{ alignItems: "start" }}>
        <CreateRunForm />
        <div className="grid-cards" style={{ gridTemplateColumns: "1fr" }}>
          {FEATURES.map((f) => (
            <div className="card pad" key={f.title} style={{ display: "flex", gap: 14 }}>
              <div style={{ fontSize: 22 }}>{f.icon}</div>
              <div>
                <div style={{ fontWeight: 700, fontSize: 15 }}>{f.title}</div>
                <div className="muted" style={{ fontSize: 13.5, marginTop: 2 }}>{f.body}</div>
              </div>
            </div>
          ))}
        </div>
      </div>

      <section className="stack" style={{ gap: 16 }}>
        <div className="row" style={{ justifyContent: "space-between" }}>
          <h2 style={{ fontSize: 20 }}>Recent episodes</h2>
        </div>
        {loading ? (
          <div className="empty"><div className="spinner-lg" style={{ margin: "0 auto" }} /></div>
        ) : (
          <RunList runs={runs} />
        )}
      </section>
    </div>
  );
}
