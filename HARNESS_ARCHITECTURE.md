# Podcast Generator Harness Architecture

Current implementation reference for the backend harness: what runs, which agent owns which
decision, what artifacts are persisted, and why the main design choices exist.

Companion docs:

- `STATE.md` — high-level project state and open risks
- `progress.md` — dated decision log
- `ARCHITECTURE.md` / `SCRIPT_GENERATION.md` — earlier design docs; useful context, but this
  file is the current harness map

---

## 1. What The Harness Is

The product is not a single model prompt. It is a staged harness that turns:

```text
Brief(topic, length, depth, language, steering)
  -> researched sources
  -> grounded facts
  -> planned podcast arc
  -> verified two-speaker script
  -> humanized delivery
  -> language-specific audio/transcript
```

The harness exists because the reasoning model is strong but not reliable enough to one-shot a
long, grounded, natural podcast. Code owns state, budgets, retries, artifact persistence,
coverage, role boundaries, verification, and render assembly. The model is asked to do narrow
jobs with bounded context.

Core principle:

```text
Let agents make judgment calls.
Let code enforce structure, budgets, persistence, and invariants.
```

---

## 2. End-To-End Pipeline

```text
Brief
  |
  v
resolve_settings
  |
  v
Research
  - Query planner
  - Exa overfetch per query
  - URL dedupe and ranking
  |
  v
SourceCorpus
  |
  v
Grounding
  - parallel source-level extraction
  - fact classification
  - source-balanced reduce
  - quality scoring
  - tension annotation
  |
  v
FactSheet
  |
  v
Planning
  - cast Host/Expert personas
  - outline listener learning ladder
  - repair fact coverage and segment count
  |
  v
Cast + Outline
  |
  v
Dialogue
  - intro
  - per-turn Director -> Speaker -> Verifier loop
  - segment reviewer panel
  - host-led outro
  |
  v
Script
  |
  v
Humanize
  - per-turn spoken delivery text
  - pace
  - acronym backstop
  |
  v
Render
  - translate for non-English
  - per-language humanize
  - parallel TTS
  - clean transcript + evidence transcript
  |
  v
Episode(s)
```

The current orchestrator is linear code in `backend/app/orchestrator.py`. It is deliberately
not a LangGraph graph yet; the stages are simple, persisted, and easy to rerun. A graph
framework may become useful once we add resumable workflows, richer branching, human review
states, or interactive "Join" sessions.

---

## 3. Main Artifacts

All major stage outputs are Pydantic models in `backend/app/artifacts.py` and are written into
`backend/runs/<run_id>/`.

| Artifact | Produced By | Purpose |
|---|---|---|
| `brief.json` | orchestrator | Canonical user request: topic, length, depth, languages, angle/focus, tone/style |
| `query_plan.json` | research/query-planner | Planned Exa searches with intents |
| `source.json` | research | Ranked source corpus with query provenance |
| `factsheet.json` | ground | Atomic grounded facts, quotes, quality scores, fact types, tension metadata |
| `cast.json` | director/cast | Host and Expert personas, gender, Bulbul voice |
| `outline.json` | director/outline | Learning-ladder segments, listener questions, terms to define, fact coverage |
| `script.json` | dialogue/humanize | Canonical English turns plus verification state; later includes `spoken` and `pace` |
| `delivery_plan_<lang>.json` | render/delivery | Phrase-level delivery text, per-phrase pace, and pause timing |
| `episode_<lang>.json` | render | Render result for one language, including transcript deliveries and cited sources |
| `transcript_<lang>.md` | citations/render | Public listener transcript: no citations, no source dump, no unverified markers |
| `transcript_evidence_<lang>.md` | citations/render | Debug/evidence transcript: citations, sources, verification markers |
| `manifest.json` | run logger | Prompt/response/latency/usage/retry audit trail |

Important split:

```text
Public transcript = listener-facing artifact.
Evidence transcript = development/debug/source-explorer artifact.
```

This split exists because inline citations, `_unverified_` markers, and source dumps made the
early public transcripts feel like generated evidence reports rather than publishable podcast
scripts.

---

## 4. Settings And Budgets

`config.resolve_settings(brief)` converts user-facing controls into stage budgets.

Current depth budgets:

| Depth | Queries | Grounding Sources | Final Facts |
|---|---:|---:|---:|
| 1 | 2 | 4 | 8 |
| 2 | 3 | 6 | 12 |
| 3 | 4 | 8 | 16 |
| 4 | 5 | 10 | 22 |
| 5 | 5 | 12 | 28 |

Current body-turn ranges:

| Length | Min | Target | Max |
|---|---:|---:|---:|
| short | 6 | 8 | 10 |
| medium | 14 | 18 | 20 |
| long | 22 | 28 | 32 |

The range matters. A fixed exact target caused filler and digression: once the story was
basically complete, the loop still generated another technical body turn just to hit the old
count. The loop may now end after the minimum when a segment naturally closes, while retaining
a max cap for long topics.

---

## 5. Agents And Their Contracts

### 5.1 Orchestrator

The orchestrator is code, not an agent.

Responsibilities:

- create the run directory
- resolve settings
- instantiate Sarvam and Exa clients
- call stages in order
- persist each artifact
- log every model call to the manifest
- enforce cancellation checkpoints for API/job runs
- keep full-pipeline execution serialized operationally

Design decision:

Small models should not own control flow. The orchestrator owns deterministic workflow,
budgets, persistence, and retries.

### 5.2 Query Planner

Location: `backend/app/agents/query_planner.py`

Input:

- topic
- number of query budget
- angle/focus settings

Output:

- `QueryPlan` with query IDs, intents, text, rationale, priority

What it does:

- expands the topic into source-seeking searches, not generic web searches
- adds angle-specific source pressure
- sends myth-busting topics toward misconception/FAQ/fact-check/official sources
- sends controversy topics toward critique/limitations/safety reviews
- sends current topics toward recent/current-status searches

Fallback exists because query planning is upstream of retrieval; the pipeline should still
work if the planner fails.

### 5.3 Research Stage

Location: `backend/app/stages/research.py`

This is not an agent. It is deterministic source acquisition and ranking.

Responsibilities:

- call Exa per planned query
- overfetch per query so dedupe does not starve the source budget
- dedupe URLs
- rank for query diversity
- persist query provenance on each `Source`

Nuance:

Exa may return fewer useful sources than requested after dedupe or source-quality filtering.
The overfetch scaling was added because higher depth budgets were otherwise not enough to
produce enough unique grounding candidates.

### 5.4 Grounder

Location: `backend/app/agents/grounder.py`, `backend/app/stages/ground.py`

The Grounder is the evidence authority.

Jobs:

- extract atomic facts from source chunks
- attach source quotes
- classify fact type:
  - `mechanism`
  - `finding`
  - `stat`
  - `caveat`
  - `counterclaim`
  - `example`
  - `misconception`
  - `background`
- assign story role:
  - `explain`
  - `illustrate`
  - `challenge`
  - `context`
  - `transition`
- compute calibrated deterministic quality score/notes
- reduce candidate facts into a source-balanced final FactSheet
- annotate tension/conflicts/caveats
- verify Expert turns against the FactSheet and source quotes

Design decisions:

- Source-level grounding is parallelized with `ThreadPoolExecutor`.
- Chunk-level parallelism is intentionally deferred to avoid more API pressure.
- Quote-less new-style facts are dropped; old fallback claims are tolerated only for backward
  compatibility.
- FactSheet is still the grounding seam. Full RAG is a possible future evolution, but the
  FactSheet gives context economy, citation units, global conflict detection, coverage control,
  and per-turn verification.

### 5.5 Director

Location: `backend/app/agents/director.py`

The Director owns structure.

Jobs:

- cast Host and Expert personas
- assign gender-compatible Bulbul voices
- plan the outline
- decide every next body beat
- choose speaker, move, and fact focus
- ration challenge turns
- review each completed segment with a reviewer panel

Director output for a turn:

```json
{
  "speaker": "host|expert",
  "move": "ask|explain|illustrate|react|connect|advance|transition|challenge",
  "fact_focus": ["F1"],
  "intent": "one-line turn instruction",
  "segment_status": "continue|close"
}
```

Critical rules:

- Host turns use `fact_focus=[]`.
- Expert explain/illustrate turns should focus at least one fact.
- Challenge only fires on tension-tagged facts and only while challenge budget remains.
- The next turn must answer or follow from the previous turn.
- If a new entity/example appears, the Director must bridge it; no dropped-in examples.
- Learning ladder must be respected before advancing.

### 5.6 Host

Location: `backend/app/agents/speaker.py`

The Host is a smart generalist and listener proxy.

Can:

- ask prerequisite questions
- react
- connect points already said
- push back with reasoning
- ask for analogies and examples
- slow the Expert down when jargon appears

Cannot:

- introduce specific researched facts
- introduce statistics, figures, dates, study findings
- cite facts directly

Design decision:

The Host is not dumb, but the Host does not hold the research. This keeps the conversation
natural and shrinks verification to Expert turns. A host who recites exact stats feels fake.

### 5.7 Expert

Location: `backend/app/agents/speaker.py`

The Expert is the sole fact-bearing speaker.

Can:

- explain grounded facts
- illustrate grounded facts
- surface caveats and uncertainty
- give the recap

Cannot:

- use outside knowledge beyond focused facts
- pose the Host's driving audience questions
- end by handing the question back to the Host
- introduce unsupported specifics

Design decision:

The Expert explains and answers. Earlier runs showed the Expert sometimes behaved like the
Host by asking the driving question. The prompt and consistency reviewer now guard that role
boundary.

### 5.8 Reviewer Panel

Location: `backend/app/agents/director.py`

After each segment, the Director runs focused reviewers in parallel:

- continuity
- consistency
- liveliness

Jobs:

- catch fabricated back-references
- catch persona bleed
- catch abrupt entity introductions
- catch repetition/flatness
- suggest revisions

Nuance:

The reviewer panel is a safety net, not a guarantee. Generation-side constraints still matter.
The panel can miss unsupported but fluent lines, so Grounder verification remains separate.

### 5.9 Humanizer

Location: `backend/app/agents/humanizer.py`, `backend/app/stages/humanize.py`

The humanizer rewrites delivery, not facts.

Input:

- canonical verified `turn.text`
- short conversation window
- tone/style settings

Output on each turn:

- `turn.spoken`
- `turn.pace`

Responsibilities:

- add natural spoken phrasing
- convert stiff written phrasing into oral phrasing
- add modest fillers/disfluencies
- preserve acronyms with deterministic placeholder protection
- keep canonical `turn.text` unchanged for citations and verification

Design decision:

Naturalness should not mutate the verified canonical script. Audio can use `spoken`; source
explorer and verification use `text`.

### 5.10 Translator / Per-Language Render

Location: `backend/app/adapters/sarvam_translate.py`, `backend/app/stages/render.py`

The English script is the pivot. Non-English episodes translate from canonical English, then
run language-specific humanization before delivery planning and TTS.

Design decisions:

- English bypasses translation.
- Non-English translation uses Mayura with modern-colloquial style.
- Native-script guard prevents Hindi/Tamil drifting into romanized text.
- Per-language meaning check is designed but deferred.
- Bulbul voices are reused cross-language.

### 5.11 Delivery Planner

Location: `backend/app/stages/delivery.py`, `backend/app/stages/render.py`,
`backend/app/adapters/sarvam_tts.py`

The delivery planner owns phrase-level timing. It does not rewrite the script. It takes the final
spoken delivery text for a turn, splits it into stable phrase chunks, assigns pace and pause
settings to each phrase, and persists the result as `delivery_plan_<lang>.json`.

Inputs:

- final per-language delivery text
- turn speaker and move
- base `turn.pace`

Outputs:

- `DeliveryPlan`
- `TurnDelivery`
- `DeliveryPhrase`
- phrase timeline consumed by the TTS assembler

Nuance:

Sarvam Bulbul exposes `pace` per TTS request, not per word. Phrase-level pacing is therefore
implemented by making multiple small TTS requests per turn, each with its own pace, then joining
the phrase audio with controlled pauses. This improves teaching rhythm without letting an LLM
insert timing markup into the canonical script.

Tradeoffs:

- More TTS requests per episode.
- Higher rate-limit risk.
- `PHRASE_RENDER_MAX_WORKERS` is lower than general `RENDER_MAX_WORKERS`.
- TTS retries respect server `Retry-After` when available.

---

## 6. The Learning Ladder

This is a central quality lever.

Problem observed:

Longer scripts did not automatically become better podcasts. The model produced a longer Q&A,
but still jumped into expert terms before listener prerequisites.

Current implementation:

Each `Segment` has:

```json
{
  "goal": "what this part does",
  "listener_question": "what the listener needs answered before moving on",
  "terms_to_define": ["terms allowed only after plain-language setup"],
  "fact_ids": ["facts this segment may cover"]
}
```

Generic ladder:

```text
ordinary problem
  -> plain object
  -> basic input/output
  -> mental model / analogy
  -> mechanism
  -> evidence
  -> tradeoff or controversy
  -> recap
```

Podcast-specific behavior:

If the Expert gets dense, the Director should prefer a Host react/connect turn like:

- "Wait, what does that mean in everyday terms?"
- "Can you give me a concrete example?"

Design decision:

The ladder is generic across topics, but its execution is format-specific. For this podcast
format, the Host carries listener confusion and controls pacing.

---

## 7. One Sample Dialogue Loop

Given:

- current segment goal
- current `listener_question`
- current `terms_to_define`
- segment facts
- recent turns
- coverage counts
- recent beat pattern
- challenge budget
- style/angle settings

The loop is:

```python
recent = turns[-CONTEXT_WINDOW_TURNS:]

view = build_director_view(
    topic=topic,
    segment=segment,
    facts=segment_facts,
    recent_turns=recent,
    coverage=coverage,
    recent_beats=recent_beats,
    challenge_budget=remaining_challenges,
    settings=settings,
)

beat = director.next_beat(view)

if beat would create ask/explain monotony:
    beat = director.next_beat(view, extra="vary the move")

beat = repair_speaker_sequence(beat, recent, body_count)

if beat.speaker == "expert":
    focus = repair_focus(
        beat.fact_focus,
        segment_fact_ids,
        fact_by_id,
        coverage,
        challenges_left,
        angle=settings.angle,
    )
else:
    focus = []

ladder_instruction = build_speaker_ladder_instruction(
    segment.listener_question,
    segment.terms_to_define,
    body_count,
    beat,
)

text = speaker.generate(
    role=beat.speaker,
    persona=host_or_expert,
    beat=beat,
    facts=[fact.claim for fact in focus],
    recent_turns=recent,
    extra_instruction=ladder_instruction,
)

if speaker opened with a banned back-reference:
    text = regenerate_with_forward_directive()

if beat.speaker == "expert":
    ok, unsupported = grounder.verify_turn(text, factsheet)
    while not ok and repairs_left:
        text = speaker.generate(extra_instruction="drop unsupported specifics")
        ok, unsupported = grounder.verify_turn(text, factsheet)
    verified = ok
else:
    verified = True

append Turn(
    speaker=beat.speaker,
    move=beat.move,
    text=text,
    cited_fact_ids=focus,
    verified=verified,
)

update coverage and recent beat pattern

if beat.segment_status == "close" and segment/body range allows closing:
    end segment

run reviewer panel on segment
apply bounded revisions
```

Then, after the body loop:

```text
if last body turn is Expert:
  Host asks for the three things listeners should remember
  Expert recaps
  Host signs off
else:
  Expert answers the existing Host bridge with recap
  Host signs off
```

This host-led outro exists because `Expert -> Expert outro` felt like a skipped transition.

---

## 8. Speaker Sequence Rules

The body is forced to stay conversational:

- first body turn must be Host
- repeated Expert is repaired into a Host reaction/follow-up
- repeated Host is repaired into an Expert answer
- outro is host-led/adaptive to avoid same-speaker transition

Nuance:

Earlier versions allowed the Expert to take two turns in a row to develop an idea. That looked
reasonable in a prompt, but sample transcripts felt like skipped dialogue glue. The harness now
prefers explicit Host bridges.

---

## 9. Verification Policy

Only Expert body turns are verified.

Why:

- Host cannot introduce specific facts.
- Expert is the only fact-bearer.
- This keeps verification focused and cheaper.

Verifier behavior:

- compares Expert text against FactSheet claims and source quotes
- if unsupported, one bounded repair is attempted
- if still unsupported, `verified=false`
- public transcript hides verification markers
- evidence transcript shows `_unverified_`

Current policy:

```text
Accept-and-flag.
```

That means the run continues even if a turn remains unsupported after repair. This preserves
observability and does not hide model overreach. Before production, this may need to become
stricter for public output: repair harder, omit unsupported turns, or force a fallback line.

---

## 10. Challenge And Debate

Challenge is not manufactured.

The Director may choose `challenge` only when:

- the focused fact has `TENSION`
- challenge budget remains

Tension comes from:

- weak evidence
- caveats
- counterclaims
- conflicts with another fact
- empirical/interpretive/normative tension labels

Design decision:

Correctness and challenge are separate axes.

```text
Unsupported claim -> Grounder repair/flag.
Supported but caveated/conflicted claim -> Director may challenge.
Plain supported claim -> explain/illustrate/connect.
```

This prevents fake debate where one speaker says something wrong just so another can correct
it.

---

## 11. Length And Pacing

The harness uses body-turn ranges rather than exact counts.

Why:

Exact counts caused filler. The model would add a late technical turn to hit the target, which
then created abrupt transitions into the outro.

Current behavior:

- each length has min/target/max body turns
- the loop must reach minimum
- after minimum, a segment close may end the body
- target is a guide, not a forced quota
- max is a hard cap

This should reduce digression while preserving enough room for complex topics.

---

## 12. Source And Fact Quality Decisions

Key choices:

- planned queries beat one broad search
- higher depth means more queries, sources, and facts
- source-level grounding is parallel
- reduce keeps source diversity so one dominant source does not starve others
- fact priority normally favors mechanism/finding/stat/example before caveat
- at least one caveat/challenge fact is preserved when available
- Director views show fact type, story role, quality score, quotes, and use count
- focus repair prefers high-value unused facts

Nuance:

Earlier runs became caveat-heavy when caveats were globally ranked too high. Now caveats are
guaranteed but not allowed to dominate the basic explanation.

---

## 13. Steering

User controls:

- length
- depth
- languages
- angle
- focus questions
- custom angle
- tone
- style
- custom style

How steering is applied:

- query planner receives angle/focus
- fallback queries are angle-aware
- Director fact priority is angle-aware
- dialogue view includes angle/style
- speaker prompt includes tone/style
- humanizer receives tone/style

Hard override:

```text
Grounding, role boundaries, and citations override steering.
```

Example:

If the user asks for myth-busting, research should seek misconception/fact-check/consensus
sources, but the Expert still cannot invent a myth or cite unsupported claims.

---

## 14. Rendering And Localization

Render stage:

- takes canonical script
- translates non-English turns
- humanizes per language
- plans phrase-level delivery
- runs TTS per phrase with per-phrase pace
- assembles WAVs with phrase/turn/outro pauses
- writes clean and evidence transcripts

Important decisions:

- English is pivot language.
- Translation is after reasoning, not before.
- Native-language reasoning is deferred.
- Meaning-preservation check is designed but deferred.
- Ducked backchannels, interruptions, overlap, crossfade, and full timeline mixing are deferred.

---

## 15. Failure Modes We Have Seen

### Expert Behaves Like Host

Symptom:

Expert asks the driving audience question.

Mitigation:

- Expert prompt says it explains/answers, not poses curiosity questions.
- consistency reviewer flags persona bleed.

### Public Transcript Looks Like Evidence Dump

Symptom:

Markdown citations, source list, `_unverified_` tags leak into listener transcript.

Mitigation:

- clean public transcript
- separate evidence transcript

### Same-Speaker Transition Into Outro

Symptom:

Expert body turn followed by Expert outro feels like a skipped Host bridge.

Mitigation:

- adaptive host-led outro
- Host asks for recap if body ended on Expert

### Longer Script Still Jumps Too Fast

Symptom:

More turns but same expert-first structure.

Mitigation:

- segment `listener_question`
- segment `terms_to_define`
- Director learning-ladder rule
- speaker ladder instruction
- podcast-specific Host clarifier rule

### Technical Concept Collapsed Incorrectly

Symptom:

Word order, attention, and masking collapsed into one wrong explanation.

Mitigation:

- generic prerequisite ladder helps, but not a domain-specific guard
- better facts/source selection still matter
- verifier catches unsupported claims but not all conceptual pedagogy issues

### Unsupported Expert Examples

Symptom:

Expert invents a concrete example that sounds plausible but is not in the facts.

Mitigation:

- verifier flags
- one repair attempt

Open concern:

Accept-and-flag is still not production-safe if the clean transcript hides the flag. A stricter
pre-publication policy is needed before launch.

---

## 16. Current Open Design Questions

1. **Should unverified Expert turns be allowed into public output?**
   Current answer: yes, accept-and-flag for development. Production probably needs stricter
   fallback or omission.

2. **Should we add a hard early-term gate?**
   Current ladder is prompt/code-assisted, not a deterministic banned-term gate. The transformer
   test showed this may still be too soft.

3. **Should the FactSheet evolve toward RAG?**
   Possible, but FactSheet remains useful for citations, tension, global coverage, and compact
   per-turn context.

4. **Should this migrate to LangGraph?**
   Not necessary for the current linear run. Potentially useful when we need resumable branches,
   human approval states, retry policies per node, interactive Join, and partial regeneration.

5. **Should render include timeline-level audio production?**
   Eventually yes for interruptions, overlap, crossfade, backchannels, and better pacing. Bulbul
   has no word timestamps, so true overlap is limited.

---

## 17. Mental Model For Future Changes

When adding a quality feature, decide which layer owns it:

| Problem | Owner |
|---|---|
| Search breadth/source intent | Query planner + research |
| Source credibility/fact extraction | Grounder |
| Narrative order/pacing | Director + code budgets |
| Listener onboarding | Outline ladder + Host behavior |
| Natural wording | Speaker |
| Factual correctness | Grounder verifier |
| Conversational variety | Director + reviewer panel |
| Spoken delivery | Humanizer |
| Localization | Translate + per-language humanizer |
| Audio realism | Render/mixer |
| UI visibility | Frontend/source explorer |

Default rule:

```text
If the behavior must always happen, encode it in code.
If it requires judgment, ask an agent.
If it affects public trust, persist it as an artifact.
```
