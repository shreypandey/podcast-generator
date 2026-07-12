# Podcast Generator — Requirements (v0.1)

A grounded, multilingual, two-host podcast generator. Turns a **topic (± user sources)**
into an audio episode where **two experts genuinely debate** — with every claim traceable
to a real source. Aims to beat NotebookLM on four axes: **real expert debate, verifiable
grounding, deep steering, interactive Q&A.**

**Fixed stack:** [Exa](https://exa.ai) (research) · **Sarvam-105B** (generation/reasoning) ·
**Sarvam-Translate** (localization) · **Sarvam Bulbul** (TTS).

---

## 1. Why the harness is the product (eval framing)

Sarvam-105B is a Mixture-of-Experts model with only **~10.3B active parameters** — at
inference it behaves like a *small* model. It cannot one-shot a long, grounded,
multi-persona debate. So the product **is the harness**: a pipeline of narrow, verifiable
steps with typed contracts, validation, and repair loops.

The two evaluation criteria map directly to sections below:
- **"How to build a harness?"** → §6 (Harness).
- **"How to work with small models?"** → §7 (Small-model techniques).

## 2. Success criteria

| Criterion | Target |
|---|---|
| Grounding rate | ≥ 95% of spoken claims map to a cited source (measured by verifier) |
| Debate quality | Genuine disagreement/challenge, not two agreeable hosts (rubric-scored) |
| Language purity | Correct target language + correct voice per language; no code-mix leakage |
| Meaning preservation | Translated turns preserve source meaning (verifier subagent gate) |
| Reliability | Pipeline resumable; a single failed stage never loses the run |
| Cost/latency | Budgeted and observable per run |

## 3. Scope decisions (locked)

- **Languages:** the **11 Bulbul-speakable languages only** (10 Indian + Indian English).
  Audio and transcript coverage are identical — every supported language is fully spoken.
- **Input:** **hybrid** — user topic + optional user sources, enriched by live Exa research.
- **Differentiators (all four in scope):** real expert debate · verifiable grounding ·
  deep steering · interactive Q&A.
- **Multilingual strategy:** **pivot-and-translate.** All reasoning (research → debate →
  verification) happens in **English** (the model's strongest language); the verified
  English script is then translated per target language and spoken. See §5.7.
- **Deliverable:** monorepo — `backend/` (Python/FastAPI) + `frontend/` (React/Next.js).
- **Persistence (v1):** flat files / SQLite. Revisit for scale.

## 4. Personas & use cases

- **Researcher/student** — topic → ~10-min grounded episode with visible sources.
- **Regional listener** — the same episode rendered in Hindi / Tamil / etc.
- **Curious listener** — pauses mid-episode, asks a question, hosts answer from the corpus.

## 5. Functional requirements

### 5.1 Intake & steering
User provides a topic, optional sources (URLs/docs), and steering knobs → a structured
**Brief**: length, depth (1–5), output language(s), angle/focus questions, optional custom
angle, tone/style presets, and optional custom style. The system auto-casts a Host and Expert;
role boundaries stay fixed regardless of steering.

### 5.2 Research (Exa, hybrid)
Decompose the Brief into angle/focus-aware sub-questions → Exa `search` + `contents`
(highlights/summaries) → merge with user sources → dedupe/rank → **SourceCorpus** with stable
source IDs. Example: myth-busting should deliberately seek misconception, FAQ, fact-check, and
official-facts sources rather than only generic explainers.

### 5.3 Grounding
Map-reduce over the corpus: extract atomic, individually-cited claims → **FactSheet**.
The FactSheet is the **only** evidence the script may use.

### 5.4–5.6 Script generation (English, canonical) — see `SCRIPT_GENERATION.md`
Four agents — **Grounder, Director, Host, Expert** — produce the canonical English
**VerifiedScript**. Highlights (full design + rationale in `SCRIPT_GENERATION.md`):
- **Host is a sharp peer**, not a novice; the **Grounder verifies both speakers**.
- **Per-turn Director** picks speaker/move/facts and any interrupt/backchannel.
- **Two axes:** correctness = Grounder silent fix (never dramatized); **challenge = Director,
  evidence-driven only** — fires on tension-flagged facts, so debate density scales with the
  actual evidence (no manufactured conflict).
- Turn-by-turn generation with short context windows; named degeneration guards.

### 5.7 Rendering (per language) — translate → verify → speak
For each target language:
1. **Translate** each host turn via **Sarvam-Translate** with `modern-colloquial` style +
   **spoken-form** output. Chunk to the **2,000-char** translate limit, per turn.
2. **Meaning-preservation check** — a dedicated **verifier subagent** compares each
   translated turn against its English source, flags semantic drift, and triggers bounded
   re-translation.
3. **TTS** via **Bulbul**: split into ≤**2,500-char** single-speaker chunks at sentence
   boundaries; map each host to a distinct, language-appropriate speaker; synthesize
   per chunk (cached, retried).
4. **Assemble** — **timeline mixer** (not plain concatenation): sequential placement +
   tight-butt/crossfade for scripted interruptions + ducked overlap tracks for backchannels +
   inter-turn micro-gaps and per-chunk `pace` for pacing (Bulbul has no SSML/timestamps) +
   loudness-normalize → **Episode** (audio + timestamped, cited transcript).
   One VerifiedScript → many-language Episodes.

### 5.8 Interactive Q&A ("Join the conversation") — DEFERRED TO THE END
**Built last**, after the whole batch system works. Live runtime (separate from the batch
orchestrator): listener question → **Sarvam STT** → retrieve from the existing corpus
(+ optional fresh Exa) → grounded answer → render (translate/TTS) → resume. See
`SCRIPT_GENERATION.md` §13.

## 6. The Harness (eval criterion #1)

- **Typed artifacts / contracts** between every stage (JSON schemas — see `ARCHITECTURE.md`):
  `Brief → SourceCorpus → FactSheet → Outline → Script → VerifiedScript → Episode`.
- **Stage orchestrator** — deterministic DAG/state machine; each stage output **persisted**
  and independently **re-runnable / resumable**.
- **Validation + repair** — schema-validate every model output; on failure, re-ask with the
  parse error (bounded retries).
- **Guardrail gates** between stages — hallucination gate (unsupported claims),
  language-purity gate, meaning-preservation gate, safety gate.
- **Caching / idempotency** — Exa results, translations, and TTS chunks keyed by content
  hash (cost + latency).
- **Budgets** — max searches / tokens / TTS calls per run; hard stops.
- **Observability** — full prompt/response/token/validation logs + a per-run manifest.

## 7. Working with small models (eval criterion #2)

1. **Decompose** — every model call does one narrow job with a tight contract.
2. **Structured output + schema validation + repair** — constrain the output space.
3. **Aggressive grounding** — facts always in-context; outside knowledge forbidden;
   citation IDs required (kills hallucination).
4. **Short generation windows** — turn-by-turn, not whole-episode (small models drift over
   long outputs).
5. **Few-shot exemplars** — show the debate-turn format; small models lean on examples.
6. **Role/persona conditioning** — specialized subagents (planner, host A, host B, verifier,
   editor, translator, meaning-checker) = distinct system prompts.
7. **Verifier passes** — a second cheap call judges the first rather than trusting one shot.
8. **Chunked map-reduce** — even with 128K context, chunk long sources for reliable attention.
9. **Do-it-in-code** — chunking, dedup, citation formatting, char-limit splitting are
   deterministic code, not model tasks.
10. **Per-stage decoding params** — low temperature for extraction/verification, higher for
    dialogue.
11. **Keep the model in English** — reason and argue in English; only *translate* into the
    target language (§5.7). Never ask the small model to reason in a low-resource language.

## 8. System architecture (monorepo)

- **`backend/`** — Python / FastAPI. The harness/orchestrator + job queue for long runs +
  REST API + SSE/WebSocket for live progress and interactive Q&A. Persists runs/artifacts.
  Adapters: **Exa**, **Sarvam LLM**, **Sarvam-Translate**, **Sarvam Bulbul TTS**,
  **Sarvam STT (Saaras v3)** — for voice Join, added last — and a **timeline audio mixer**.
- **`frontend/`** — React / Next.js. Steering form, live pipeline progress, source explorer,
  transcript-with-citations, multi-language audio player, interactive Q&A panel.
- **Shared** — JSON schema / type definitions for the artifacts.

## 9. Non-functional

Generation runs in minutes → stream progress. Cost/latency budgets enforced. Resumable +
observable. Quality metrics tracked (grounding rate, debate-tension score, language purity,
meaning-preservation pass rate).

## 10. Phasing

- **M0** — Repo scaffold + config/keys + thin vertical slice
  (topic → 1 Exa result → 1 fact → 2-line script → TTS → audio file).
- **M1** — Full pipeline, **English**, one-shot, persisted artifacts + observability.
  *Includes an early spike to de-risk Sarvam-105B debate quality.*
- **M2** — Grounding + verifier + citations (differentiator: verifiable grounding).
- **M3** — Expert-debate quality + deep steering (differentiators: debate + steering).
- **M4** — **Render pipeline** (translate → meaning-check → TTS) decoupled from content;
  prove on Hindi + Tamil, then fan out to the remaining 9 languages.
- **M5** — Frontend polish + metrics dashboard.
- **M6** — **"Join the conversation" (interactive Q&A) — built last**: live runtime + Sarvam STT.

## 11. Risks / open questions

- Sarvam-105B quality on sustained English debate — de-risk with an M1 spike before building
  scaffolding around assumptions.
- Bulbul rate limits / latency; concatenation artifacts at segment joins.
- Translation style-flattening dulling persona voice — mitigated by `modern-colloquial` +
  spoken form + the meaning-preservation subagent.
- Persistence choice (flat files/SQLite vs. Postgres) — revisit after M2.
