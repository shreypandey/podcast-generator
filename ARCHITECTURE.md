# Architecture — Harness & Artifact Contracts

Companion to `REQUIREMENTS.md`. Defines the pipeline, the subagents (role-conditioned
Sarvam-105B calls), and the typed artifacts that flow between stages.

## 1. Two pipelines, one seam

The system splits into a **language-agnostic content pipeline** (always English, where the
small model is strongest) and a **per-language render pipeline**. The seam is the
`VerifiedScript`. One content run → N language Episodes.

```
CONTENT PIPELINE  (English, run once)
  Brief ─► Research ─► Grounding ─► Outline ─► Dialogue ─► Verify ─► VerifiedScript
            (Exa)     (map-reduce)            (turn-by-turn)  (judge)
                                                                     │
                                                                     ▼  (per language)
RENDER PIPELINE   (repeatable, cheap)
  VerifiedScript ─► Translate ─► Meaning-check ─► TTS ─► Assemble ─► Episode
                    (Sarvam-      (verifier       (Bulbul)
                     Translate)    subagent)
```

Every stage: **validate output against schema → on failure, repair (bounded retries) →
persist artifact → gate → next stage.** Any stage is independently re-runnable from
persisted inputs.

## 2. Subagents (role-conditioned model calls)

Script generation uses **four** agents (Grounder, Director, Host, Expert) — the full design
and rationale live in **`SCRIPT_GENERATION.md`**. The render pipeline adds two more. Upstream
research uses a query-planner.

| Subagent | Job | Temp | Key guardrail |
|---|---|---|---|
| `query-planner` | Brief → angle/focus-aware search sub-questions (upstream research) | low | ≤ N queries (budget); specialized sources for angles like myth-busting/current/controversy |
| **`grounder`** | corpus → annotated FactSheet; verify each turn's claims | low | claim must cite a fact ID; verifies **both** speakers |
| **`director`** | build arc; per-turn pick speaker/move/facts + interrupt/backchannel; segment health | low-med | challenge only on tension-flagged facts |
| **`host`** | sharp generalist co-host: incisive questions, own knowledge, substantive pushback | high | may only use FactSheet IDs |
| **`expert`** | deep specialist: explain, illustrate, surface caveats/conflicts | med | may only use FactSheet IDs |
| `translator` | turn → target language (Sarvam-Translate) | — | `modern-colloquial` + spoken form |
| `meaning-checker` | translated turn ⇄ English source equivalence | low | drift → bounded re-translate |

> The Director subsumes the old `outline-planner` + `editor`; the Grounder subsumes
> `fact-extractor` + `claim-verifier`. The old "opposing-stance host-a/host-b" model is
> replaced by **Host + Expert** with **evidence-driven** tension. See `SCRIPT_GENERATION.md`.

## 3. Hard constraints (encode in code, not prompts)

- **TTS (Bulbul):** ≤ 2,500 chars/request; 11 languages; distinct speaker per host.
- **Translate (Sarvam-Translate):** ≤ 2,000 chars/request → **governing chunk size**,
  applied per host turn so speaker/voice mapping stays aligned.
- **LLM (Sarvam-105B):** 128K context, but chunk long sources anyway (small-model attention).

## 4. Artifact schemas (v0.1, illustrative)

```jsonc
// Brief — output of intake
{
  "topic": "str",
  "length": "short|medium|long",
  "depth": 1,                         // 1..5; scales queries/sources/facts/detail
  "languages": ["hi-IN", "en-IN"],    // subset of the 11 Bulbul languages
  "angle": "balanced|mechanism|current|controversy|practical|mythbusting|beginner",
  "focus_questions": ["str"],         // up to 5 short questions; query-planner + dialogue emphasis
  "custom_angle": "str",
  "tone": "conversational|serious|energetic|calm|investigative",
  "style": "curious_expert|debate|storytelling|classroom|news_analysis",
  "custom_style": "str"
}

// QueryPlan — output of angle/focus-aware research planning
{
  "topic": "str",
  "queries": [
    { "id": "Q1", "intent": "core_explainer|primary_official|caveat_critique|recent_current|example_case",
      "query": "str", "rationale": "str", "priority": 1 }
  ]
}

// SourceCorpus — output of research
{
  "run_id": "str",
  "sources": [
    { "id": "S1", "url": "str", "title": "str", "text": "str",
      "highlights": ["str"], "origin": "exa|user",
      "query_ids": ["Q1"], "query_intents": ["core_explainer"],
      "search_rank": 1 }
  ]
}

// FactSheet — output of grounding (the ONLY evidence the script may use)
// Facts include source excerpts, calibrated quality scores, type/use labels, and tension
// metadata so Director coverage, verification, and challenge are evidence-driven.
{
  "run_id": "str",
  "facts": [
    { "id": "F1", "claim": "str", "source_ids": ["S1"],
      "source_quotes": ["short exact supporting excerpt"],
      "fact_type": "mechanism|finding|stat|caveat|counterclaim|example|misconception|background",
      "story_role": "explain|illustrate|challenge|context|transition",
      "quality_score": 0.0,
      "quality_notes": ["why this fact was promoted or penalized"],
      "evidence_strength": "weak|moderate|strong",
      "conflicts_with": ["F12"], "caveats": ["str"],
      "tension_type": "empirical|interpretive|normative|none" }
  ]
}

// Outline — output of planning
{
  "run_id": "str",
  "segments": [
    { "id": "SEG1", "goal": "str", "fact_ids": ["F1","F2"],
      "stance_map": { "A": "str", "B": "str" } }
  ]
}

// VerifiedScript — canonical English, the render seam (see SCRIPT_GENERATION.md §11)
{
  "run_id": "str",
  "language": "en-IN",
  "turns": [
    { "idx": 0, "speaker": "host|expert", "text": "str", "move": "explain",
      "cited_fact_ids": ["F1"], "verified": true,
      "cutoff": false, "pace": 1.0,
      "events": [ { "type": "interrupt|backchannel", "speaker": "host",
                    "cue": "mm-hmm", "anchor_frac": 0.6 } ] }
  ]
}

// Episode — output of render, per language
{
  "run_id": "str",
  "language": "hi-IN",
  "audio_path": "str",
  "transcript": [
    { "idx": 0, "host": "A", "text_src": "str", "text_tgt": "str",
      "cited_fact_ids": ["F1"], "meaning_ok": true,
      "audio_chunks": ["path1.wav"], "t_start": 0.0, "t_end": 12.4 }
  ]
}
```

## 5. Run manifest (observability)

Each run writes a manifest logging, per stage: inputs/outputs (artifact refs), every
prompt/response, token usage, decoding params, validation + gate outcomes, retries, and
cache hits. This is the audit trail the harness is evaluated on.
