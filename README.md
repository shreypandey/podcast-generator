# Podcast Generator

A grounded, multilingual, **two-host podcast generator** — like NotebookLM, but where the two
hosts *genuinely debate* and **every spoken claim is traceable to a real source**. Give it a
topic (and optional sources); it researches, stages an evidence-driven Host-vs-Expert
conversation, and renders it to audio in any of **11 languages**.

Built to beat NotebookLM on four axes:

- **Real expert debate** — a sharp Host and a deep Expert with evidence-driven tension, not two agreeable narrators.
- **Verifiable grounding** — every claim cites a fact; every fact cites a source, with the supporting quote shown inline.
- **Deep steering** — length, depth, angle, focus questions, tone/style, and target languages.
- **Interactive Q&A** — pause mid-episode and ask a question ("Join the conversation"). *Deferred to last.*

**Fixed stack:** [Exa](https://exa.ai) (research) · **Sarvam-105B** (generation & reasoning) ·
**Sarvam-Translate** (localization) · **Sarvam Bulbul** (TTS).

---

## How it works

The system is a **harness**, not a single prompt: Sarvam-105B is a Mixture-of-Experts model
with only ~10.3B active parameters, so it behaves like a *small* model. It can't one-shot a
long, grounded, multi-persona debate — so the product is a pipeline of narrow, verifiable steps
with typed contracts, schema validation, and repair loops.

It splits into a **language-agnostic content pipeline** (always English, where the small model
is strongest) and a **per-language render pipeline**. The seam is the `VerifiedScript` — one
content run fans out to N language episodes.

```
CONTENT PIPELINE  (English, run once)
  Brief ─► Research ─► Grounding ─► Outline ─► Dialogue ─► Verify ─► VerifiedScript
            (Exa)     (map-reduce)            (4 agents)    (judge)
                                                                 │
                                                                 ▼  (per language)
RENDER PIPELINE   (repeatable, cheap)
  VerifiedScript ─► Translate ─► Meaning-check ─► TTS ─► Assemble ─► Episode
                    (Sarvam-      (verifier        (Bulbul)   (timeline
                     Translate)    subagent)                   mixer)
```

The four script agents — **Grounder, Director, Host, Expert** — turn the FactSheet into the
canonical English script. Correctness is a silent Grounder fix; *challenge* is Director-driven
and evidence-only, so debate density scales with the actual evidence. See
[`SCRIPT_GENERATION.md`](SCRIPT_GENERATION.md).

## Repository layout

This is a **monorepo**:

| Path | What |
|---|---|
| [`backend/`](backend/) | Python / FastAPI. The harness/orchestrator, job runner, REST API + SSE progress, and the four service adapters (Exa, Sarvam LLM/Translate/TTS). Also serves the compiled frontend same-origin. |
| [`frontend/`](frontend/) | React + Vite + TypeScript UI — steering form, live pipeline progress, transcript with inline citations, source explorer, multi-language audio player. Ships with an in-browser mock backend, so it runs with no server. |
| Docs (root) | [`REQUIREMENTS.md`](REQUIREMENTS.md), [`ARCHITECTURE.md`](ARCHITECTURE.md), [`SCRIPT_GENERATION.md`](SCRIPT_GENERATION.md), [`API_REQUIREMENTS.md`](API_REQUIREMENTS.md), [`UI_REQUIREMENTS.md`](UI_REQUIREMENTS.md), [`progress.md`](progress.md). |

## Quick start

### Backend (the generator)

```bash
cd backend
cp .env.example .env        # fill in EXA_API_KEY and SARVAM_API_KEY
uv sync

# One-shot CLI run → writes a timestamped runs/<id>/ with all artifacts + episode.wav
uv run python -m app.run "the economics of desalination"

# Or serve the API (+ compiled frontend if built)
uv run uvicorn app.main:app --reload    # http://localhost:8000
```

### Frontend (the UI)

```bash
cd frontend
npm install

# Standalone demo — no backend needed (in-browser mock)
VITE_USE_MOCK=1 npm run dev              # http://localhost:5173

# Against the real backend (proxies /api -> :8000)
npm run dev
```

Try the topic **"how mRNA vaccines work"** in mock mode for the full multilingual
(English / Hindi / Tamil) demo with real citations and honestly-flagged unverified turns.

For production, `npm run build` compiles the SPA into `frontend/dist/`, which the FastAPI
backend serves same-origin alongside `/api/*`.

## Status

| Milestone | State |
|---|---|
| M0 — Thin vertical slice (topic → Exa → fact → script → TTS → audio) | ✅ |
| M1 — Full English pipeline (4-agent loop) + observability | ✅ |
| M2 — Grounding + verifier + citations | ✅ |
| M3 — Expert-debate quality + deep steering | ✅ |
| M4 — Render pipeline (translate → TTS), confirmed for en/hi/ta | 🔨 meaning-check deferred |
| M5 — Frontend + metrics | 🔨 UI built |
| M6 — Interactive Q&A ("Join the conversation") | ⬜ built last |

See [`progress.md`](progress.md) for the living status tracker.

## Languages

The **11 Bulbul-speakable languages**: English (India), Hindi, Bengali, Tamil, Telugu, Marathi,
Gujarati, Kannada, Malayalam, Punjabi, and Odia. Audio and transcript coverage are identical —
every supported language is fully spoken.
