# Project State — Podcast Generator

Single consolidated reference for **everything explored, decided, learned, deferred, and
pending**. Companion detail docs: `REQUIREMENTS.md`, `ARCHITECTURE.md`, `SCRIPT_GENERATION.md`,
`progress.md` (raw dated decision log + API learnings). This file is the narrative overview.

Last updated: 2026-07-12.

---

## 1. What this is

A grounded, multilingual, two-host podcast generator (NotebookLM-beating). Topic (± user
sources) → live research → grounded facts → a two-host **debate** script → audio, with every
spoken claim traceable to a source. Fixed stack: **Exa** (research), **Sarvam-105B** (reasoning),
**Sarvam-Translate** (localization, not yet used), **Sarvam Bulbul** (TTS), **Sarvam STT** (for
"Join", last). Delivered as `backend/` (Python/uv, built) + `frontend/` (not started).

## 2. Milestone status

| Milestone | Status | Summary |
|---|---|---|
| M0 walking skeleton | ✅ | topic → 1 source → 1 fact → 2-line script → TTS → wav |
| M1 full English pipeline | ✅ | 4-agent loop; multi-fact grounding; personas; outline; per-turn debate. **+ polish** (move variety, host figure-discipline, back-ref guardrail; intro/outro; gender voices; host bears no facts) |
| M2a verify + citations | ✅ | per-Expert-turn grounding gate + bounded repair; `transcript.md` + `Episode.sources`; grounding-rate metric |
| M2b tension + challenge | ✅ | `annotate_tension`; evidence-driven `challenge` (budget-rationed) |
| M3 steering + editor | ✅ | `--length`/`--depth`, **angle/focus**, and **tone/style** per-run `Settings`; query-planner angle hints; **parallel reviewer-panel editor** (continuity/consistency/liveliness) + `next_beat` coherence/bridge nudge |
| M4 render pipeline | 🔨 | **v1 + M4.1 ✅ (confirmed en/hi/ta)** Mayura translate (English bypass) → **per-language humanizer** (native fillers + native-script guard) → parallel per-turn TTS → `episode_<lang>.wav` + `transcript_<lang>.md` (citations). `--langs`. **Pending:** meaning-check subagent, timeline mixer (Lever D) |
| M5 frontend | ⬜ | UI, live progress, player, source explorer |
| M6 "Join" (interactive) | ⬜ | **deferred to the very end**; live STT loop |

## 3. The pipeline as built (English content side)

```
Brief(topic,length,depth,languages,angle/focus,tone/style) → resolve_settings
 → research   query planner → Exa overfetch → dedupe/rank             → SourceCorpus (S1..Sn)
 → ground     parallel source-level map → source-balanced reduce
              → classify + quote facts → annotate tension             → FactSheet (F1..Fm)
 → plan       Director.cast (topic personas + gender voices)          → Cast
              Director.plan_outline (segments + fact coverage)        → Outline
 → dialogue   intro → per-turn (Director.next_beat → Speaker.generate → verify gate → repair)
              → per-segment REVIEWER PANEL (parallel) → revise flagged turns → outro
 → humanize   parallel per-turn (3-turn window) → adds turn.spoken + turn.pace (delivery-only)
 → render     TTS speaks turn.spoken at turn.pace (concat + 0.2s gap) + transcript.md → Episode
```

**Agents (role-conditioned Sarvam calls):** Grounder (extract/annotate/verify), Director
(cast/outline/next_beat/**reviewer panel**), Host (smart generalist, **no facts**), Expert (sole
fact-bearer). Orchestrator = code (context assembly, budgets, retries, persistence, manifest).
Every run writes typed artifacts + `manifest.json` (all prompts/responses/latency/usage).

## 4. Key decisions (with rationale)

- **11 Bulbul languages, hybrid input, all 4 differentiators** (debate, verifiable grounding,
  deep steering, interactive Q&A).
- **Pivot-and-translate** for multilingual: reason/debate in English (model's strongest), then
  translate per language (M4). Never make the small model argue in a low-resource language.
- **Four agents**, each a narrow job — the way to get quality from a ~10B-active model.
- **Only the Expert bears facts.** The Host is a *smart peer* (reasons, asks, pushes back) but
  introduces no specific stats — may *echo* what the Expert said. (This **revised** an earlier
  "host bears facts" call.) Shrinks verification to Expert turns; fixes the host reciting stats.
- **Per-turn Director** (not a pre-planned beat sheet): ~2 LLM calls/turn, maximally adaptive.
- **Two axes:** correctness = Grounder silent fix (never dramatized); challenge = Director,
  **evidence-driven only** (fires on tension-flagged facts) — debate density scales with the
  evidence, never manufactured.
- **Accept-and-flag** grounding (see §6 trade-off).
- **Deep steering = presets + custom steering.** Length/depth control budgets/detail;
  angle/focus steers research, outline, fact priority, and dialogue emphasis; tone/style steers
  speaker wording and humanized delivery. Grounding and role boundaries override all steering.
- **Editor = a parallel reviewer panel** (user idea) replacing a single omnibus check.
- **Voices gender-matched** to persona; distinct even for same-gender casts; **`rahul` banned**.
- **Humanizer** — post-generation, parallel per-turn subagent turns each verified turn into
  natural *spoken* delivery (`turn.spoken` + `turn.pace`); **delivery-only**, clean `turn.text`
  stays canonical. Acronyms **placeholder-protected** (the model mangles them if left free).
- **Expert never poses the Host's driving questions** — it explains/answers (a rare genuine
  clarifier is fine); enforced in the Expert prompt AND the consistency reviewer.
- **M2c evidence richness** — research now overfetches with planned query intents, grounds a
  larger diverse source set, classifies facts (`fact_type`/`story_role`), stores source quotes,
  assigns calibrated deterministic `quality_score`/`quality_notes`, repairs Director coverage
  toward high-value facts, and uses source quotes in the verification prompt.
- **Angle-aware research** — query planning now sees angle/focus steering. Myth-busting pushes
  misconception/FAQ/fact-check/consensus searches; controversy pushes critique/limitation/safety
  review searches; current pushes recent/current-status searches.

## 5. API / model learnings (Sarvam · Exa · Bulbul)

- **Sarvam-105B is a reasoning model.** Even at `reasoning_effort="low"` it spends tokens on
  hidden CoT (`message.reasoning_content`) that counts against `max_tokens` → budget generously.
- **Starter tier caps `max_tokens` at 4096** (400 error above). Clamped (`TIER_MAX_TOKENS`).
- **Gateway 403s oversized request bodies** (a full Exa page can be >100K chars; ~27K worked).
  Fixed with **chunked map-reduce grounding** (`GROUND_CHUNK_CHARS=8000`, ≤3 chunks/source).
- **Robustness:** `with_transient_retry` retries 429/5xx, **403** (mid-run auth hiccups under
  load — a truly bad key fails on the first call), **and** `httpx.RequestError` (network/read-
  timeout); client `timeout=120`. `complete_json(fallback_text=True)` tolerates a bare-sentence
  speaker output. **Don't run pipelines concurrently** (concurrent load triggered a 403).
- **Bulbul v3:** 22050 Hz; single `.audios` element for short text; ~3s/turn; **no SSML, no
  non-verbal tags, no word timestamps**; pace 0.5–2.0; spells out ACRONYMS (e.g. "COVID"); has
  `enable_preprocessing` + custom-dictionary options (untried).
- **Exa** `search_and_contents` is fast (~0.5s); `.text` can be huge.
- **No prompt caching on Sarvam** (confirmed). And reasoning tokens dominate, so caching would
  save little anyway — prompts structured caching-ready regardless.
- **The small model mangles acronyms** when free-rewriting (e.g. `mRNA`→"em-en-ary"). Handle
  acronyms **deterministically** (placeholder-protect → restore); don't trust the prompt alone.
- **`ThreadPoolExecutor` parallelism** works against the shared Sarvam client (httpx is
  thread-safe) — used for source-level grounding, the reviewer panel, and the humanizer to hide
  latency of N calls. Do not run multiple full pipelines concurrently.

## 6. User feedback → disposition (every item)

| Feedback | Disposition |
|---|---|
| Starts mid-topic, no intro/build-up | ✅ added intro/outro phases + outline "build up, don't lead with stats" |
| "Alex" with a female voice | ✅ casting picks gender → gender-matched voice pools |
| Host recites exact stats ("42 of 71") | ✅ Host bears no facts; paraphrases significance |
| Fabricated back-reference ("you mentioned membranes") | ✅ prompt guardrail → then editor panel (continuity reviewer) |
| Expert ungrounded specifics ("nuclear envelope") | ✅ M2a verify gate + bounded repair |
| Is the verifier over-flagging? | ✅ hand-checked — precise (real overreach); **accept-and-flag** |
| Q&A ping-pong monotony | ✅ move-variety Director prompt + bounded anti-ping-pong re-ask |
| COVID appears as if established (continuity error) | ✅ **reviewer panel** (context-aware continuity check) + **`next_beat` bridge nudge** |
| Robotic audio (#1) | ✅ humanizer (spoken delivery + per-turn pace) + tighter 0.2s gaps; interruptions (D) deferred |
| "COVID" spelled out (#2) | ✅ deterministic acronym backstop (COVID→"Covid"; mRNA/DNA preserved) |
| FactSheet compresses; RAG? (#3) | ⏸ explored, parked (§8) |
| No umm/ahh/interruptions (#5) | ✅ disfluencies (humanizer); interruptions/overlap (D) deferred |
| Humanizer mangled `mRNA`→"em-en-ary" | ✅ acronym placeholder-protection (self-caught during pass 1) |
| Expert posed the Host's driving question | ✅ Expert prompt forbids it + consistency reviewer broadened |
| Never use `rahul` voice | ✅ removed from pool + saved to memory |
| Don't inspect truncated data | ✅ saved to memory (my working rule) |

## 7. Quality levers (what moves output quality, and status)

- **Grounding gate** (verify per Expert turn) — ✅ built; rate 50–80% (accept-and-flag).
- **Fact quality — grounding richness (M2c)** — ✅ core evidence upgrades shipped: query planner,
  source-diverse grounding, source-balanced fact reduce, fact classification, source quotes,
  calibrated quality scoring, Director coverage pressure, quote-aware verification, and parallel
  grounding.
- **Source diversity** — ✅ research overfetches 2-5 planned query intents, dedupes/ranks, and
  grounds up to depth-scaled source budgets (depth 3 = 6 grounding sources).
- **Steering** — ✅ length/depth + angle/focus + tone/style. Angle affects query planning,
  fallback searches, Director fact priority, outline repair, and dialogue view; tone/style affects
  speaker prompts and the humanizer/render delivery pass.
- **Reviewer-panel editor** — ✅ built (continuity/consistency/liveliness, parallel, hard/soft).
- **Director coherence/bridge nudge** — ✅ built (defense-in-depth with the panel).
- **Debate/tension** — ✅ evidence-driven challenge, budget-rationed.
- **Spoken naturalness** — ✅ **A+B+C** via the humanizer (spoken numbers/acronyms, disfluencies,
  per-turn pace, tighter gaps). **D (interruptions/overlap/mixer/crossfade) deferred** (§9).
- **TTS realism** — bounded by Bulbul; disfluencies/pace help, won't reach ElevenLabs level.

## 8. Explorations & open questions

- **FactSheet vs RAG.** *Why a FactSheet exists:* context economy (can't feed 4 full articles
  into ~30 per-turn calls) + discrete grounded units that verification, `[n]` citations, tension
  detection, and coverage all rely on. *RAG trade-off:* no lossy cap and full source access, but
  needs an embedding index, per-turn retrieval latency, verification-against-passages, and loses
  easy *global* conflict detection. *Verdict:* a legitimate evolution but a big change, and **not**
  the current bottleneck (naturalness is) → **parked** as a deliberate exploration. Cheaper middle
  ground already exists: fact cap is steerable (`--depth 5` = 20 facts); could attach a source
  quote per fact.
- **Prompt caching** — not available on Sarvam; reasoning dominates so limited upside; prompts
  kept caching-ready (stable prefix + swapped objective) in case it lands.
- **Native-language generation** (e.g. argue directly in Hindi) — deferred; pivot-translate for
  all 11 for now.
- **Grounding strictness ↔ natural speech** — decided **accept-and-flag** (flag overreach, don't
  hide or over-constrain). Revisit if needed.

## 9. Pending work — "what we'll touch later"

1. **Naturalness — pass 1 = A+B+C ✅ DONE; D deferred** (`SCRIPT_GENERATION.md §9`):
   - **A+B+C ✅** — **humanizer subagent** (`agents/humanizer.py`, `stages/humanize.py`):
     post-generation, parallel per-turn over a 3-turn window; writes `turn.spoken` + `turn.pace`
     (clean `turn.text` canonical). Spoken numbers/units, disfluencies, spoken punctuation, pace
     0.9–1.15; **deterministic acronym backstop** (placeholder-protect: mRNA/DNA preserved,
     COVID-19→"Covid nineteen"). Inter-turn gap 0.4→0.2s. *Number normalization is model-driven —
     a `num2words` backstop is a fast-follow if it proves unreliable.*
   - **D (interruptions & overlap) — DEFERRED, come back later.** Needs a cross-turn "delivery"
     pass + a real **timeline mixer** (pydub vs numpy). D1 scripted cut-ins (feasible, no
     timestamps) → D2 ducked backchannels (approximate) → D3 true word-aligned overlap (NOT
     feasible — Bulbul has no timestamps). **Crossfade at joins rides with this.**
2. **M2c backend evidence loop** — ✅ closed: quality scoring calibrated, Director coverage
   pressure added, and verification sees source quotes. Transcript/source explorer polish moves
   to M5.
3. **Steering knobs** — ✅ shipped: angle/focus, tone/style, custom angle/style; M5 still needs
   the UI controls.
4. **M4 render pipeline** — uniform per-language flow: **translate → meaning-check → humanize →
   TTS → timeline mixer**. Translate has an **English bypass** (target `en-IN` → return input
   unchanged), so English is just the identity case and needs no special path. The **humanizer
   always sits after translate** (fillers/spoken-form are language-specific). Bulbul TTS per
   language (11 langs, per-language voice pools **excluding `rahul`**). Turns the canonical
   English `VerifiedScript` into many-language episodes.
   - **Humanizer** = post-generation, parallel per-turn over a **3-turn window (humanize only
     the last, backward context)**, writes `turn.spoken` (clean `turn.text` stays canonical for
     citations). Subsumes Lever A (spoken numbers/acronyms/punctuation) + Lever B (disfluencies)
     + emits per-turn `pace` (Lever C). Optional deterministic number/acronym backstop.
     *(Per-language humanizer with native-script guard is BUILT — M4.1.)*
   - **Meaning-preservation check — DEFERRED, come back later.** Ensure a translation didn't
     drop/distort/negate a grounded claim, so citations hold in non-English episodes. **Design
     (ready to build):** runs in render between translate and humanize, **scoped to fact-bearing
     Expert turns only** (`cited_fact_ids`); **method A = focused bilingual judge** (1 call: EN
     source vs translation → are numbers/entities/claim/negation preserved?); **method B =
     back-translation + English compare** (more robust, 2 calls) as the fallback if A is
     unreliable per-language; on drift → 1 stricter re-translate → re-check → **keep-and-flag**
     with a per-language translation-fidelity metric (accept-and-flag). New `agents/meaning_checker.py`.
5. **M5 frontend** — steering form, live pipeline progress, transcript-with-citations, player.
6. **M6 "Join"** — Sarvam STT streaming + low-latency live runtime; **built last**.
7. **RAG** — optional exploration (§8).

### Remaining SCRIPT work — two buckets

Split by "how it's said" vs "what it says" (angle sits with *content*, not naturalness):

| Bucket | Contains | About |
|---|---|---|
| **1. Delivery / naturalness** | spoken disfluencies (um/right), interruptions, **tone/style** ✅ | register + how it reads/sounds as speech; no content change |
| **2. Content & data** | **angle/focus** ✅, source diversity, **M2c** (findings-not-methodology), **RAG** | what facts feed the script and what it emphasizes |

Caveats: (a) **naturalness straddles script and render** — the *script half* is the text
(fillers, interruption markup, tone in wording); the *audio half* (realizing them + the
"COVID"-spelled TTS fix) is **render/M4**. (b) Everything else on the script — grounding,
verification, citations, debate/challenge, editor panel, coherence nudge — is **built**;
grounding rate 50–80% is a decided limitation, not pending work.

## 10. Known limitations (honest)

- Grounding rate **50–80%** at higher depth — the small model embellishes beyond facts; the gate
  catches + flags but one repair doesn't always fix it (accept-and-flag).
- **Bulbul naturalness ceiling** — audio will improve with the naturalness pass but stays
  short of top-tier TTS.
- **Editor is a small-model safety net**, not a guarantee — the panel raises recall but won't
  catch everything (hence the generation-side nudge too).
- **Director fact use is still model-mediated.** M2c.8 adds deterministic outline/focus repair
  around high-value facts, but final wording still depends on the speaker model and verifier.
- **Source credibility is still heuristic.** Fact scoring gives small domain credibility boosts,
  but source selection itself still needs explicit credibility/recency policy before production.
- **Cost:** the reviewer panel + per-turn Director = many reasoning calls; no caching to amortize.

## 11. Current config knobs (`backend/app/config.py`)

- Models: `LLM_MODEL="sarvam-105b"`, `TTS_MODEL="bulbul:v3"`, `LANGUAGE="en-IN"`.
- Voices: `FEMALE_VOICES=["priya","ritu","neha"]`, `MALE_VOICES=["aditya","shubh"]` (rahul banned).
- Grounding: `GROUND_CHUNK_CHARS=8000`, `MAX_CHUNKS_PER_SOURCE=3`, `GROUND_MAX_WORKERS=3`.
- Loop: `CONTEXT_WINDOW_TURNS=4`, `VERIFY_MAX_REPAIRS=1`, `MAX_CHALLENGES=2`,
  `MAX_SEGMENT_REVISIONS=2`.
- TTS/naturalness: `TTS_PACE=1.0` default, `TTS_GAP_SECONDS=0.2` (inter-turn); humanizer emits a
  per-turn `pace` in 0.9–1.15; acronym map in `humanizer._ACRONYMS`.
- Steering (`resolve_settings`): length {short:6, medium:10, long:16} turns; depth 1–5 →
  queries {2,3,4,5,5}, grounding sources {3,4,6,7,8}, facts {6,9,12,16,20};
  segments 2/3/4; turns/segment = ceil(total/segs). Presets: angle
  `{balanced,mechanism,current,controversy,practical,mythbusting,beginner}`, tone
  `{conversational,serious,energetic,calm,investigative}`, style
  `{curious_expert,debate,storytelling,classroom,news_analysis}`; plus ≤5 focus questions and
  short custom angle/style text.
- LLM adapter: `TIER_MAX_TOKENS=4096`, transient retry (429/5xx + transport), client `timeout=120`.

## 12. Subtle nuances worth remembering

- Reasoning tokens count against `max_tokens`; empty `content` on truncation → retry at ceiling.
- Only the Expert sees facts; Host echoing a stated figure is allowed (references, not sources).
- `challenge` fires only on tension-flagged facts (Expert cites conflicting facts and stays
  verified); a Host challenge is reasoning-based skepticism with no facts.
- Editor runs **per segment**, panel **parallel** (`ThreadPoolExecutor`), flags aggregated
  **hard-first, one per turn**; revised Expert turns **re-verified** (editor can't smuggle
  ungrounded claims); ≤`MAX_SEGMENT_REVISIONS` applied.
- Facts carry `fact_type`, `story_role`, up to 2 bounded `source_quotes`, plus calibrated
  deterministic `quality_score`/`quality_notes`; the Director sees score + first quote in its
  view, while speakers still receive claim text only.
- M2c.7 live smoke (`20260712-164708`) proved scoring executed end-to-end but saturated at `1.0`;
  M2c.8 recalibrated the score curve and added deterministic coverage/verification use of quotes.
- Citations = the turn's *assigned* facts → source URLs (an approximation, not per-claim quote
  spans yet).
- Intro/outro are separate framing turns (no fact constraint); persona names injected so no
  hallucinated co-host names.
- `brief.json` records the chosen length/depth; the manifest records grounding rate + every call.
- **Humanizer is delivery-only, post-verify:** TTS speaks `turn.spoken`; `turn.text` stays the
  canonical, verified, cited version → spoken drift can't break grounding. `transcript.md` shows
  clean `text`.
- **Acronyms are placeholder-protected** in the humanizer (the model mangles them if left free):
  word-acronyms → spoken form ("COVID"→"Covid"), letter-acronyms preserved ("mRNA","DNA").
  **Numbers→words is still model-driven** — a `num2words` backstop is a noted fast-follow.
- **The Expert never poses the Host's driving questions** ("so how does X work?") — it
  explains/answers; enforced in the Expert prompt AND caught by the consistency reviewer.
- Three stages use bounded parallelism against the shared client: source-level grounding
  (`GROUND_MAX_WORKERS=3`), reviewer panel, and per-turn humanizer.
