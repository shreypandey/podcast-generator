# Script Generation — Design & Rationale

The complete design for turning a **source corpus → a verified, performance-annotated
English script** (`VerifiedScript`). This is the hardest part of the system and the seam
that feeds the render pipeline.

Every decision below is stated as **Decision → Why → Nuance** so the reasoning is
recoverable later. Companion docs: `REQUIREMENTS.md`, `ARCHITECTURE.md`.

**Scope of this doc.** Corpus (already fetched) → `VerifiedScript`. It *decides* the
performance structure (interruptions, backchannels) but does **not** realize audio.
Explicitly **out of scope / deferred**: research/Exa retrieval (upstream), TTS + translation
(render pipeline), and the **"Join the conversation" feature — deferred to the very end of
the project**, built last once everything else works.

---

## 0. Design philosophy (the backbone "why")

**Decision.** The product *is* the harness, not the model call.
**Why.** Sarvam-105B is MoE with **~10.3B active parameters** — at inference it behaves like
a *small* model. It cannot one-shot a long, grounded, multi-voice debate. So we decompose
script generation into narrow, verifiable steps and make **code** responsible for structure,
grounding, continuity, and repair — leaving the model only the one job it does well: writing
a single in-character line given tight context.

Two constraints drive every choice:
1. **Small models drift over long output and long context** → short generation units, short
   context windows.
2. **Small models hallucinate and can't reliably self-judge in one shot** → external
   grounding + a separate verifier pass + bounded repair.

---

## 1. The four agents

**Decision.** Exactly four role-conditioned agents: **Grounder, Director, Host, Expert.**
**Why.** Each is a *narrow* job with a clean contract — the way to get quality from a small
model. Merging them (e.g., "one agent that writes and fact-checks itself") reintroduces the
one-shot failure we're avoiding.

| Agent | Charter | Speaks? | Bears facts? | Temp | Why this boundary |
|---|---|---|---|---|---|
| **Grounder** | Evidence authority: builds the annotated FactSheet; verifies every turn's claims against it | no | is the source of truth | ~0.1 | Correctness must be owned by something with **no incentive to be interesting** — separate from the speakers |
| **Director** | Conductor: builds the arc; per turn decides *who speaks, which move, which facts, and any interrupt/backchannel*; runs segment health checks | no | no | ~0.3 | Continuity and pacing can't live in a speaker with a short context window — a small model won't self-regulate structure |
| **Host** | Sharp generalist co-host: asks incisive questions, reasons, reacts, pushes back — but does **not** introduce specific researched facts | yes | no (general knowledge only) | ~0.7 | See §2 — a smart peer, not a novice, but not the source of specifics |
| **Expert** | Deep domain specialist: explains, illustrates, honestly surfaces caveats/conflicts | yes | **yes (sole fact-bearer)** | ~0.5 | Depth + intellectual honesty is where real "expert" texture comes from |

**Nuance — orchestrator ≠ agent.** The Director is an *agent* (judgment). The **orchestrator
is code**: context assembly, chunking, caching, retries, budgets, state. Never ask a small
model to do what code does deterministically.

## 2. The speaker model: Host + Expert (both smart)

**Decision.** Two speakers — a **Host** and an **Expert**. The **Host is a sharp peer, not a
naive question-asker**, but only the **Expert holds the research (the FactSheet)**. The Host
reasons, asks, reacts, and pushes back from general knowledge or what the Expert has already
said — it never introduces specific statistics, figures, or study findings. The Grounder
therefore verifies **the Expert's** claims; Host turns carry no new facts to check.
**Why.**
- *Not two opposing experts arguing scripted stances* — that manufactures fake conflict, the
  exact failure that makes debates feel performed. Tension must be **earned from the
  evidence** (§5), not assigned.
- *Not a dumb host* — a novice "setup man" is condescending and flat. A smart generalist who
  asks the questions an intelligent listener has, and occasionally knows something the Expert
  didn't foreground, creates real back-and-forth.
- Difference between them is **breadth vs. depth and function**, not intelligence.

**Nuance — why the Host doesn't bear facts.** An audience-proxy who rattles off precise
researched statistics reads as unnatural ("how does the host know that exact number?"). Giving
the FactSheet only to the Expert makes the roles realistic *and* shrinks the grounding surface
to Expert turns only, simplifying verification (§5). The Host may still *echo* a figure the
Expert just stated — that's referencing the conversation, not sourcing a new fact.

## 3. Shared state

**Decision.** One `ScriptState` accumulates; agents see **views** over it, never the raw blob.
**Why.** Controlling exactly what each agent sees is how we keep a small model on-task and
force continuity to live in the Director/state rather than in a speaker's fallible memory.

```jsonc
ScriptState {
  factsheet:  [ annotated facts — §4 ],
  outline:    [ segments: goal + fact_ids + tension_flags ],
  transcript: [ turns so far ],
  cursor:     { segment_idx, turn_idx },
  coverage:   { fact_id → times_used },     // repetition guard
  tension_budget_used, turn_budget_used,    // pacing + cost caps
}
```

## 4. Stage 1 — Grounding: the annotated FactSheet

**Decision.** Map-reduce over corpus chunks → atomic, individually-cited claims, **each
annotated with tension metadata**. This FactSheet is the **only** evidence any turn may use.
**Why.** Two reasons, both central:
1. **Grounding kills hallucination** — facts live in-context with citation IDs; outside
   knowledge is forbidden. This is the single biggest lever for a small model's reliability.
2. **Deciding *where* legitimate tension exists is done here, once, grounded** — *not*
   spontaneously mid-dialogue. A small model asked "is this a good place to argue?" will
   invent disputes to seem lively. We compute tension from evidence instead.

```jsonc
{ "id":"F7", "claim":"...", "source_ids":["S3"],
  "evidence_strength":"weak|moderate|strong",
  "conflicts_with":["F12"],                 // genuine empirical forks
  "caveats":["small sample, n=40"],
  "tension_type":"empirical|interpretive|normative|none" }
```

**Nuance.** Map-reduce (chunk → extract → merge) is used even though the model has 128K
context, because small-model **attention degrades across large contexts** — chunking gives
reliable extraction.

## 5. The two axes — correctness vs. challenge (central principle)

**Decision.** Factual correctness and conversational challenge are **orthogonal** and owned by
**different agents**:

- **Correctness = Grounder, silent, pre-speech.** An unsupported/overreaching claim is a
  *defect*: regenerate the turn with a correct fact **before it is ever spoken.** Never
  dramatized.
- **Challenge = Director move, on true claims only.** A challenge is "that's true, but is it
  the whole picture?" — it operates on statements that are *already grounded*.

**Why.** Collapsing them produces dishonest theater — letting a host say something false so
the other can "correct" it. That wastes tokens and misleads the listener. By the time a turn
airs, everything in it is true; challenge then works only on the interpretation/significance.

`Wrong → Grounder fixes silently. True-but-contested → Director calls a challenge. Else → explain/ask/illustrate/react/advance.`

### 5.1 When challenge fires (evidence-driven)
**Decision.** A challenge fires **only when the current beat lands on a fact flagged** with
`conflicts_with`, weak `evidence_strength`, `caveats`, or `normative` tension — rationed by a
**tension budget**.
**Why.** Precision over recall: an ungrounded challenge reads as manufactured drama. Making
challenge *data-driven from the FactSheet* means **debate density scales with how much genuine
tension the evidence actually holds** — a settled topic yields a mostly-collaborative episode;
a contested one yields more friction. That honesty is what beats "two agreeable enthusiasts."
**Nuance — the boundary with correctness:** a claim stretched *beyond support* = Grounder fix;
a *defensible-but-aggressive interpretation* of a supported fact = legitimate challenge.

## 6. Stage 2 — Planning: the arc

**Decision.** Director turns the FactSheet into an **outline**: an opening hook, ordered
segments (each with a goal + the fact IDs it must cover + any tension flags in that cluster),
and a closing.
**Why.** A small model has no global view while writing a single line; the arc must be planned
externally. Narrative sequencing (start concrete/relatable → build → biggest genuine tension
mid-to-late → resolve) is a Director-level decision, not something to hope emerges turn by turn.

## 7. Stage 3 — The turn loop (the core)

**Decision.** **Per-turn Director.** Three agent calls per turn:
`Director.next_beat → Speaker.generate → Grounder.verify`.
**Why per-turn (not a pre-planned beat-sheet).** Maximum adaptivity: the Director reacts to
what was *actually just said* — repairing pacing, spotting flatness, deploying a challenge
exactly when the conversation reaches a flagged fact. The cost (3× calls/turn) is the
accepted price of quality with a ~10B-active model; Director/Grounder calls are cheap and
short.

```
for each segment:
  loop:
    1. DIRECTOR.next_beat(state view) →
         { speaker: host|expert,
           move: ask|explain|illustrate|react|challenge|connect|advance|transition,
           fact_focus: [F-ids],
           intent: "one-line instruction",
           beat_type: turn|interrupt|backchannel,   // §9
           segment_status: continue|close }

    2. SPEAKER.generate(context) → turn text
         context = persona + move + intent + fact_focus TEXT + last N turns ONLY

    3. GROUNDER.verify(turn) →
         supported?         → pass
         unsupported?       → REPAIR this turn (regen w/ correct fact), silent
         question/reaction? → pass (no claim)

    append turn; update coverage + budgets; advance cursor
    if segment_status == close OR turn budget hit:
        DIRECTOR.review_segment(turns) → flat? repetitive? tension under-used? → targeted regen
        break
```

### 7.1 Context windowing
**Decision.** Each speaker sees **only**: its persona, the Director's move+intent for *this*
turn, the *text* of the `fact_focus` facts, and the **last N turns** (not the whole
transcript). The Director sees a *compressed* running summary + segment goals.
**Why.** Small models drift with long context and lose persona crispness. Short windows keep
voice sharp and force continuity to live in the Director/state — where we can control it.

### 7.2 The move repertoire
**Decision.** Moves = `{ ask, explain, illustrate, react, challenge, connect-to-stakes,
advance, transition }`; the Director enforces a good **mix** and the **arc**.
**Why.** "Always challenge" is exhausting; "always explain" is a lecture. Good podcasting is
*variety*: curiosity opens a beat, clarity answers it, friction only where earned. Optimizing
the mix — not any single move — is what makes it feel alive.

## 8. Degeneration guards (failure modes → owner → fix)

**Decision.** Explicit guards, each owned by a specific agent/code path.
**Why.** Small models fail in predictable ways over a long exchange; each needs a named catch.

| Failure | Caught by | Fix |
|---|---|---|
| Hallucinated / unsupported claim | Grounder | silent regen with correct fact |
| Drift into agreement / flatness | Director (`review_segment`) | inject earned challenge or advance |
| Repetition / circling / fact overuse | orchestrator `coverage` + Director | force new fact / transition |
| Manufactured fake conflict | design (challenge fires only on flags) | cannot arise |
| Persona bleed (Host sounds like Expert) | Director editor pass | regen turn |
| Oscillation / deadlock on a point | turn budget + Director `close` | force segment transition |
| Turn too long for later TTS | orchestrator (deterministic length cap) | cap in speaker prompt |

## 9. Performance / texture layer (structure decided here, realized downstream)

**Decision.** Conversational texture splits in two:
- **Structure** (who interrupts, where a backchannel lands) — **language-agnostic → decided
  here** by the Director as `beat_type ∈ {turn, interrupt, backchannel}` plus a per-turn
  `cutoff` flag and `pace`.
- **Realization** (the exact filler/backchannel words, audio overlap) — **language-specific →
  done in the render pipeline**, because fillers don't translate ("um" → Hindi
  "matlab/achha/haan").

**Why the split.** Grounding must see clean semantic content, so texture is layered on
*after* verification and kept separate from claims. And filler realization is per-language, so
baking English "um" into the canonical script would be wrong for 10 of 11 languages.

**Three fidelity tiers** (Bulbul has no SSML/timestamps, so this is what's actually feasible):
1. **In-text disfluency** — fillers/reactions/false-starts written into the line; Bulbul's v3
   text-analysis layer speaks them. Density-capped so a small model can't over-stuff "um".
2. **Scripted interruptions** — `cutoff:true` ends a turn mid-phrase ("So the real issue is—");
   the render mixer butts the next clip tight with a short crossfade. No word timestamps needed.
3. **True overlap backchannel** — `{type:"backchannel", cue, anchor_frac}` mixed onto the
   timeline at an approximate offset with ducked gain. Advanced polish tier.

**Guardrail.** The performance layer may add **only** fillers/cutoffs/cues — a diff check
ensures **no new claims** are introduced (texture can't smuggle in ungrounded content).

**Nuance — no 5th agent.** Director owns texture *structure*, speakers own inline disfluency,
render owns realization. Stays within the four agents.

## 10. Decoding params, budgets, termination

- **Per-agent temperature** (§1): low for Grounder/Director (determinism, judgment), higher
  for Host/Expert (natural voice). *Why:* extraction/verification must be stable; dialogue
  needs variation.
- **Budgets:** per-run caps on turns, tokens, and tension moves; hard stops. *Why:* bound cost
  and prevent runaway loops with a cheap model.
- **Termination / opening / closing:** episode ends when all segments are covered or the
  global budget caps. The Director owns the **opening hook** (concrete way in) and the
  **closing** (synthesis + honest "what's still unsettled"). *Why:* these are arc-level
  decisions, not emergent.

## 11. Output artifact

```jsonc
VerifiedScript {
  run_id, language: "en-IN",     // canonical English seam for the render pipeline
  turns: [
    { idx, speaker: "host|expert", text,
      move, cited_fact_ids: ["F7"], verified: true,
      cutoff: false, pace: 1.0,
      events: [ { type:"interrupt|backchannel", speaker, cue?, anchor_frac? } ] }
  ],
  segments: [ { id, turn_range } ]
}
```

## 12. Traceability to the eval criteria

- **"How to build a harness?"** → §1 (agent decomposition), §3 (state/views), §7 (turn loop +
  gates + repair), §8 (named guards), §10 (budgets). The harness owns structure, grounding,
  continuity, and repair.
- **"How to work with small models?"** → §0 (constraints), §4 (grounding + map-reduce),
  §5 (external verification, two axes), §7.1 (short context windows), §7 (short generation
  units, 3-call decomposition), §9 (density caps).

## 13. Deferred / out of scope (built later)

- **Render pipeline** — translate (spoken/colloquial) → meaning-check → TTS → timeline mixer.
- **"Join the conversation"** — **deferred to the very end of the project.** It reuses these
  four agents + FactSheet in a low-latency live runtime plus Sarvam STT; not built until the
  batch system is finished.

## 14. Open questions

- N (context window size in turns) and per-segment turn budget — tune empirically in M1.
- Disfluency density defaults per persona/language — tune with real Bulbul output.
- Whether `review_segment` regen is turn-targeted or segment-wide when tension is under-used.
