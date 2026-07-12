# NotebookLM-Quality Readiness

What it takes for this project to become a genuinely good podcast generator, comparable in user value to NotebookLM Audio Overviews.

## Current Position

The backend is no longer a toy pipeline. It has a grounded research loop, typed artifacts, citations, verification, host/expert roles, steering, multilingual rendering, and job APIs. The next quality jump is less about prompt tweaks and more about productizing the listening and source workflow.

## What Already Exists

- Live research through Exa.
- Query planning with angle/focus-aware source discovery.
- Source-diverse grounding.
- FactSheet with fact types, source quotes, quality scores, and citations.
- Per-turn expert verification and bounded repair.
- Host/expert role separation.
- Evidence-driven challenge/tension.
- Reviewer-panel editor.
- Length/depth steering.
- Angle/focus steering.
- Tone/style steering.
- Multilingual render path with English, Hindi, and Tamil validated.
- Per-language transcript citations.
- Backend job runner, API, event stream, and persisted artifacts.

## Major Gaps

- No polished frontend yet.
- No first-class source upload/import workflow.
- No source selection or "use only my sources" mode.
- No source explorer UX.
- Audio still behaves like generated dialogue plus TTS concatenation, not a fully produced podcast.
- Timeline mixer, interruptions, crossfades, loudness normalization, and overlap are still deferred.
- No meaning-preservation check for translated fact-bearing turns.
- No full quality-eval harness for comparing runs.
- No interactive "Join" experience.
- Production reliability, resumability, retries, and deployment controls are incomplete.

## Roadmap To NotebookLM-Level Product Quality

### 1. Build M5 Frontend

This is the highest-leverage next step. Users need to create runs, steer them, watch progress, inspect evidence, listen to audio, and read cited transcripts without touching backend files.

M5 should expose:

- Topic/source input.
- Length, depth, language controls.
- Angle/focus/tone/style controls.
- Live pipeline progress.
- Audio playback per language.
- Transcript with source citations.
- Source explorer.
- Artifact/debug view.
- Run history.
- Failure/cancel/retry UX.

### 2. Make It Source-First

NotebookLM feels powerful because users bring material and the system transforms it. This project needs a proper source workflow, not only topic-to-web-research.

Required:

- URL import.
- Text/Markdown upload.
- PDF upload.
- Future YouTube transcript ingestion.
- User source library per run.
- Toggle between "research the web" and "use only my sources."
- Source inclusion/exclusion before generation.
- Source credibility and freshness metadata.

### 3. Improve Audio Production

The biggest perceptual gap is audio quality. Good scripts still feel synthetic if the audio is just turn-by-turn TTS with hard joins.

Required:

- Timeline mixer.
- Crossfades at joins.
- Loudness normalization.
- Better silence modeling.
- Scripted interruptions.
- Approximate backchannels.
- Speaker-specific pace and delivery profiles.
- Audio QA metrics: duration, clipping, silence gaps, failed chunks.
- Optional alternate TTS provider evaluation if Bulbul quality becomes the ceiling.

### 4. Add A Real Eval Harness

The project needs repeatable quality measurement, not only manual listening.

Track:

- Grounding rate.
- Unsupported claim rate.
- Citation coverage.
- Source diversity.
- Source credibility.
- Role violations.
- Expert asking host-style driving questions.
- Repetition.
- Segment coherence.
- Angle adherence.
- Tone/style adherence.
- Audio duration.
- Render failures.
- Translation drift.
- End-to-end latency and cost.

Each live run should produce a scorecard so changes can be compared.

### 5. Add Translation Meaning Checks

For multilingual output, citations only remain trustworthy if translated turns preserve the English source meaning.

Required:

- Meaning check only for fact-bearing expert turns.
- Bilingual judge: English canonical turn vs translated turn.
- Check numbers, entities, negation, claim direction, and caveats.
- On drift: stricter re-translate once.
- If still drifting: keep-and-flag with a translation-fidelity metric.

### 6. Add Regeneration And Editing UX

Users should be able to iterate without restarting from scratch.

Examples:

- Make it shorter.
- Make it more skeptical.
- Make it beginner-friendly.
- Focus more on safety.
- Use only these sources.
- Remove this source.
- Regenerate this segment.
- Regenerate only Hindi audio.
- Re-render audio with a different tone.

### 7. Add Interactive Join Last

Interactive Q&A should come after the batch product is strong.

Required flow:

- User asks a spoken or typed question.
- Retrieve from existing source corpus and FactSheet.
- Optionally do fresh web research.
- Generate a grounded answer.
- Verify answer.
- Render response in the current language.
- Resume the episode cleanly.

## Practical Priority

The next 60% of product quality comes from:

1. M5 frontend.
2. Source workflow.
3. Audio production.
4. Eval harness.

The backend has enough intelligence now. The product needs usability, evidence visibility, and better listening quality.
