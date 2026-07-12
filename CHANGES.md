# Changes

A record of everything added in the frontend + docs work. Grouped by area; file-level
inventory at the end.

Scope note: the **frontend is built by one owner; the `backend/` FastAPI + pipeline is a
separate team's**. Nothing under `backend/` was modified — the only backend-adjacent change was
a proposed API contract review handed off as a document (see below).

---

## 1. API contract review (handoff to the backend team)

**`frontend/API_CONTRACT_REVIEW.md`** — a prioritized, forwardable review of the draft API from
the frontend/user perspective. No backend code was touched; this is a request document. It was
adopted into `API_REQUIREMENTS.md` by the backend team.

- **P0 — language dimension made first-class.** `languages` in the `POST /api/runs` body;
  `languages.{requested, ready, primary}` on run status so the UI can unlock each language as it
  finishes rendering; `?lang=` on `/audio` and `/transcript`. Plus keeping `verified:false`
  turns honest (surface, don't hide, unverified claims).
- **P1** — per-citation **source quotes** (`citations[].quote`) so a citation chip can show the
  exact supporting excerpt; the **cast** (who's Host / who's Expert) on the run + transcript; a
  **`POST /api/runs/{id}/cancel`** endpoint; richer live progress events.
- **P2** — additional `metrics` (grounding rate, unverified/challenge counts, per-language
  duration), source-explorer enrichment (`search_rank`, `snippet`, `fact_ids`), and optional
  steering echo.
- **Deletions** — none; the draft had nothing to remove. Fields already correct were confirmed.

---

## 2. Frontend application (new — `frontend/`)

A complete **Vite + React + TypeScript** single-page app, built strictly against the finalized
contract. Every component depends only on a `Backend` interface, so the real HTTP client and an
in-browser mock are interchangeable. Served same-origin by the backend in production.

### Scaffold & tooling
- **`package.json`** — react / react-dom / react-router-dom; dev deps for Vite + TS. Scripts:
  `dev`, `build` (`tsc --noEmit && vite build`), `typecheck`, `preview`.
- **`tsconfig.json`** — strict mode, `noUnusedLocals` / `noUnusedParameters`.
- **`vite.config.ts`** — React plugin; dev proxy `/api` → `VITE_API_TARGET` (default `:8000`);
  build to `dist/`.
- **`index.html`**, **`src/main.tsx`**, **`src/vite-env.d.ts`** — app entry + env typing.
- **`.env.example`** (`VITE_USE_MOCK=1`), **`README.md`** (frontend-specific run/build guide,
  contract→UI mapping table), **`.gitignore`**.

### API layer (`src/api/`)
- **`types.ts`** — TypeScript mirror of the finalized contract (RunDetail, RunLanguages,
  CreateRunRequest, TranscriptTurn/Response, CitationDetail, SourceItem, Metrics, RunEvent).
- **`backend.ts`** — the `Backend` interface (health, listRuns, getRun, createRun, cancelRun,
  getTranscript, getSources, audioUrl, watchRun), plus `ApiErr` and the `USE_MOCK` switch.
- **`real.ts`** — HTTP client. Parses the `{error:{code,message}}` shape into `ApiErr`; `watchRun`
  polls status every 1.5s with a best-effort SSE stream for live events; stops on terminal state.
- **`mock.ts`** — a full in-browser simulation of the 14-stage pipeline. Derives run state
  deterministically from elapsed time, emits live progress events, seeds a few finished runs
  (including a failed one for the error path), and synthesizes plausible episodes for arbitrary
  topics.
- **`mockData.ts`** — authentic demo data from a real mRNA-vaccine run (cast, citations with
  source quotes, English/Hindi/Tamil transcript turns incl. unverified + challenge turns), so the
  demo showcases the multilingual + grounding differentiators with real content.
- **`languages.ts`** — the 11 Bulbul languages (code, label, native name, flag).
- **`wav.ts`** — generates a soft-tone WAV data URI to back the mock audio player.
- **`index.ts`** — selects real vs. mock from `VITE_USE_MOCK` and re-exports.

### UI (`src/components/`, `src/pages/`, `src/hooks/`, `src/lib/`, `src/index.css`)
- **`index.css`** — a custom design system (CSS variables, light/dark theme via
  `prefers-color-scheme` + an authoritative `data-theme` toggle). No CSS framework. Component
  classes for the topbar, cards, buttons, timeline, feed, player, transcript, popovers, etc.
- **`App.tsx`** — top bar (brand, mock badge, light/dark/system theme toggle) + routes.
- **`pages/HomePage.tsx`** — hero, the steering create-form, four feature cards, recent-runs list.
- **`pages/RunPage.tsx`** — the run view: live progress while running, cancel button, cast card,
  grounding meter + metric tiles, language switcher, audio player, and transcript/sources tabs;
  handles failed / canceled / not-found states.
- **`components/CreateRunForm.tsx`** — topic, length control, depth slider (1–5), multi-select
  language chips (min 1), and an advanced disclosure for tone + focus questions.
- **`components/RunProgress.tsx`** — the 14-stage pipeline grouped into display stages, with
  done/active/pending states, progress bars, and a live activity feed.
- **`components/TranscriptView.tsx`** — inline citation chips that open source-quote popovers,
  honest `unverified` flags (with an explanatory tooltip), move badges, and a "show original
  English" toggle for translated episodes.
- **`components/AudioPlayer.tsx`** — per-language audio player with cast/topic context.
- **`components/LanguageSwitcher.tsx`** — switches language, unlocking each as it becomes ready.
- **`components/SourcesPanel.tsx`** — the source explorer (rank, snippet, quality, linked facts).
- **`components/RunList.tsx`** — the recent-episodes dashboard list.
- **`components/common.tsx`** — shared bits: StatusBadge, Avatar, CastRow, GroundingStat,
  MetricStats.
- **`hooks/useRunWatch.ts`** — subscribes to live status + events for a run.
- **`lib/format.ts`** — small formatting helpers (relative time, etc.).

### Verification performed
- `npm run build` — clean typecheck + production bundle.
- Dev server serves in mock mode (HTTP 200).
- Two Node smoke tests over the mock layer: **25/25** assertions (seeded runs, Devanagari/Tamil
  transcripts, citations-with-quotes, unverified flags, per-language metrics, 404/409 error
  paths) and a time-based run that progressed through all 14 stages → 23 live events → both
  languages ready → `succeeded`.
- No headless browser was available, so the rendered pages were not click-tested; verification
  was at the build, serving, and mock/data-layer level.

---

## 3. Root project README (new)

**`README.md`** (repo root) — a whole-project overview written from the actual code and docs:
what the product is and the four axes it targets vs. NotebookLM; the harness rationale and the
two-pipeline diagram; the monorepo layout with a linked docs index; quick-start for both the
backend (CLI + `uvicorn app.main:app`) and the frontend (mock + real modes); a milestone status
table; and the 11 supported languages.

---

## 4. Repo housekeeping (non-git file changes)

- **`.gitignore`** (repo root, new) — monorepo-wide ignores: secrets (`.env*`, keys), Node
  (`node_modules/`, `dist/`), Python (`__pycache__/`, `.venv/`), generated outputs (`runs/`,
  `*.db*`, `backend/data/`), logs, and editor/OS junk. Complements the per-package
  `backend/.gitignore` and `frontend/.gitignore`.
- **`frontend/.gitignore`** (updated) — expanded to a complete Vite/React/TS ignore set
  (build output, local env files while keeping `.env.example`, logs, coverage, `*.tsbuildinfo`,
  editor/OS files).

---

## File inventory

**New — docs**
```
README.md
CHANGES.md
frontend/API_CONTRACT_REVIEW.md
frontend/README.md
```

**New — root config**
```
.gitignore
```

**Updated**
```
frontend/.gitignore
```

**New — frontend app**
```
frontend/.env.example
frontend/index.html
frontend/package.json
frontend/tsconfig.json
frontend/vite.config.ts
frontend/src/main.tsx
frontend/src/App.tsx
frontend/src/index.css
frontend/src/vite-env.d.ts
frontend/src/api/{types,backend,real,mock,mockData,languages,wav,index}.ts
frontend/src/components/{CreateRunForm,RunProgress,TranscriptView,AudioPlayer,LanguageSwitcher,SourcesPanel,RunList,common}.tsx
frontend/src/pages/{HomePage,RunPage}.tsx
frontend/src/hooks/useRunWatch.ts
frontend/src/lib/format.ts
```
