# API Contract Review — from the Frontend

**Author:** Frontend
**Reviewing:** `API_REQUIREMENTS.md`
**Purpose:** What the frontend needs from the API to deliver the best user experience, expressed
as concrete additions / changes / confirmations for the backend team. Ordered by priority.

The contract is a solid base. The gaps below are almost all about **surfacing the product's own
differentiators** (multilingual output, verifiable grounding, real debate) that the pipeline
*already produces* but the current contract *hides*.

---

## P0 — Blocking. The frontend cannot ship a correct UX without these.

### 1. The whole API is missing the **language dimension**
The pipeline renders **one Episode per language** (`episode_<lang>.wav`, `transcript_<lang>.md`,
`Episode.language`) — this is a headline differentiator (11 Bulbul languages). But the contract's
`/audio` and `/transcript` assume a single `episode.wav`, and `POST /api/runs` has **no way to
request languages**. Without this, the frontend can only ever expose English.

**Requested changes:**

- **`POST /api/runs`** — add `languages: string[]` (BCP-47 codes, subset of the 11 Bulbul langs;
  default `["en-IN"]`). Maps directly to the existing `Brief.languages` / CLI `--langs`.
- **`GET /api/runs/{id}`** — add the set of languages and per-language readiness:
  ```json
  "languages": {
    "requested": ["en-IN", "hi-IN", "ta-IN"],
    "ready":     ["en-IN"],
    "primary":   "en-IN"
  }
  ```
- **`GET /api/runs/{id}/audio?lang=hi-IN`** — `lang` query param (default = primary).
  `404` unknown run · `409` that language not rendered yet · `200 audio/wav`.
- **`GET /api/runs/{id}/transcript?lang=hi-IN`** — same `lang` param. Each language has its own
  translated/spoken delivery text **and its own citation list**, which the pipeline already writes
  (`transcript_<lang>.md`, `Episode.deliveries`).

### 2. Transcript response should carry both `text` and `spoken`, and honestly expose unverified turns
The contract's transcript shape is close (it has `text`, `spoken`, `verified`, `citation_numbers`) —
please keep all four. Two clarifications the UI depends on:

- `verified: false` must be sent through **unchanged** (not filtered). Honest grounding-flagging is a
  selling point — the UI renders these as a subtle "unverified" marker (the pipeline already prints
  `_(unverified)_` in `transcript_*.md`). Do **not** drop or "fix up" these turns server-side.
- For non-English languages, `text` = canonical English (citation anchor), `spoken` = the
  translated/humanized delivery actually spoken. The UI shows `spoken` and can reveal the English
  `text` on demand. Please populate `spoken` from `Episode.deliveries[idx]` per language.

---

## P1 — High value. Directly powers a differentiator; UX is notably worse without it.

### 3. Per-citation **source quote** (verifiable grounding, made tangible)
Right now a citation only links turn → source URL. The pipeline stores the exact supporting excerpt
(`Fact.source_quotes`). Exposing it lets the UI do the thing NotebookLM doesn't: **hover a `[1]` →
see the exact sentence from the source that backs the claim.** Please enrich the transcript `sources`
(or add a `citations` array) with the quote and the fact it came from:
```json
"citations": [
  { "number": 1, "fact_id": "F3", "source_id": "S1",
    "source_title": "COVID-19 Vaccine Basics | CDC",
    "source_url": "https://www.cdc.gov/...",
    "quote": "mRNA teaches cells to make a harmless piece of the spike protein." }
]
```

### 4. **Cast** (the two debaters) in the run/transcript response
The UI wants to show "who's debating" — Host vs Expert, names, one-line backgrounds, and which
voice. Already in `cast.json`. Please include on `GET /api/runs/{id}` (and/or the transcript):
```json
"cast": {
  "host":   { "name": "Alex",            "background": "curious generalist host", "gender": "…", "voice": "priya"  },
  "expert": { "name": "Dr. Lena Petrova","background": "immunologist",            "gender": "…", "voice": "aditya" }
}
```
`transcript.turns[].speaker_name` (already in the contract) stays — this just adds the richer card.

### 5. **Cancel a run** — `POST /api/runs/{id}/cancel`
Runs take minutes. The status model already defines `canceled`, but there's no endpoint to reach it.
Without this, a user who starts a wrong run is stuck watching it burn API budget. Returns `202`,
transitions status → `canceled`.

### 6. Richer, more useful **progress** during the minutes-long run
The `stage` enum + SSE envelope are good. To make the wait feel alive (and show off the harness),
please emit **counted sub-progress** in event `payload` and mirror it in `GET /api/runs/{id}`:
- `research`: `sources_found`
- `ground`: `sources_done / sources_total`, `facts_so_far`
- `dialogue`: `turns_done / turns_total`, and ideally the just-generated turn's `speaker`+`move`
- `render`: `languages_done / languages_total`, current `lang`

`GET /api/runs/{id}.progress` already has `{current, total, label}` — keeping that filled per stage is
enough for a good progress bar; the richer `payload` is what makes the live event feed compelling.

---

## P2 — Nice to have. Improves polish; safe to defer past first release.

### 7. Metrics worth surfacing
`grounding_rate`, `source_count`, `turn_count` are great. Please also include when available:
- `duration_sec` per language (so the history list and player can show length without fetching audio),
- `challenge_count` / debate-tension signal (showcases "real debate"),
- `unverified_count` (pairs with grounding_rate).

### 8. Sources panel enrichment
`GET /sources` is good. Optional adds for a real "source explorer": `search_rank`, a short
`snippet`/highlight, `quality_score`, and `fact_ids` (which facts came from this source) so the UI can
link sources ⇆ transcript claims both ways.

### 9. Steering echo-back
If the create form grows (see §10), echo the chosen steering (`languages`, `tone`, `focus_questions`)
back on `GET /api/runs/{id}` so a shared run link is self-describing.

### 10. Optional richer steering inputs on `POST /api/runs`
`REQUIREMENTS.md §5.1` describes more knobs than `topic/length/depth`. When the backend is ready,
the frontend can send (all optional, backward-compatible):
`focus_questions: string[]`, `tone: string`, `user_sources: string[]` (hybrid input is in scope).
The UI will hide these behind an "Advanced" disclosure until supported.

---

## Deletions / no-ops

- Nothing needs to be **removed**. The debug endpoints (`/episode`, `/manifest`,
  `/artifacts/{name}`) aren't consumed by the first frontend — fine to keep as debug-only/unlisted.
- `GET /api/runs/{id}/episode` in particular is not needed by the UI (we use `/transcript` +
  `/sources` + `/audio`). Keep it if cheap; don't invest in it for us.

## Things that are already right (please keep as-is)

- The `queued/running/succeeded/failed/canceled` status model and the `stage` enum.
- The SSE envelope (`event_id`, `ts`, `stage`, `kind`, `status`, `message`, `payload`) — and the
  documented **polling fallback** on `GET /api/runs/{id}`. The frontend implements polling first and
  upgrades to SSE transparently, so shipping SSE later is fine.
- The `{ "error": { code, message, details } }` error shape and the HTTP codes
  (`404` missing vs `409` not-ready) — the UI relies on that distinction.
- Same-origin relative URLs + API-routes-before-SPA-catch-all. The Vite build targets
  `frontend/dist` and uses relative `/api/...` fetches exactly as specified.

---

## One-paragraph summary for the standup

The contract is a good skeleton but **single-language**, which contradicts the product's multilingual
core: the top ask is a `lang` dimension on `POST /runs`, `GET /runs/{id}`, `/audio`, and `/transcript`
(P0). After that, the high-leverage adds are all about making the differentiators visible — **source
quotes per citation** and **cast** (P1), plus a **cancel** endpoint since runs are long. Everything
else (richer metrics, source-explorer fields, extra steering knobs) is polish the frontend will
progressively enhance behind feature checks, so it won't block either team.
