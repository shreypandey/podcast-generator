# Deepcast — frontend

React + Vite + TypeScript UI for the podcast generator. Single-page app served same-origin by
the FastAPI backend in production (per `../API_REQUIREMENTS.md`); talks to `/api/*` with relative
fetches. Ships with a full **in-browser mock backend** so the whole UX runs with no server.

## Quick start (mock — no backend needed)

```bash
cd frontend
npm install
VITE_USE_MOCK=1 npm run dev      # http://localhost:5173
```

Try topic **"how mRNA vaccines work"** for the full multilingual (English/Hindi/Tamil) demo
episode with real citations and honestly-flagged unverified turns. Any other topic generates a
plausible synthetic episode. The dashboard is pre-seeded with a few finished runs (incl. a failed
one, to show the error path).

## Against the real backend

```bash
npm run dev                       # proxies /api -> VITE_API_TARGET (default :8000)
# or point elsewhere:
VITE_API_TARGET=http://localhost:8000 npm run dev
```

## Build

```bash
npm run build                     # tsc typecheck + vite build -> dist/
npm run preview
```

The backend serves `dist/` as the SPA. Keep API routes registered before the catch-all so
`/api/*` is never intercepted (see `../API_REQUIREMENTS.md`).

## What it covers (contract → UI)

| Contract | UI |
|---|---|
| `POST /api/runs` (topic/length/depth/**languages**, optional tone/focus) | Create form on the home page |
| `GET /api/runs` | Recent-episodes dashboard |
| `GET /api/runs/{id}` + `/events` (poll or SSE) | Live pipeline timeline + activity feed |
| `POST /api/runs/{id}/cancel` | Cancel button while running |
| `languages.{requested,ready,primary}` | Language switcher (renders as each language finishes) |
| `cast` | Host-vs-Expert card |
| `GET /audio?lang=` | Multilingual audio player |
| `GET /transcript?lang=` + `citations[].quote` | Transcript with inline citations → source-quote popovers, unverified flags, "show original English" |
| `GET /sources` | Source explorer |
| `metrics` (grounding_rate, unverified/challenge counts, per-lang duration) | Metric tiles + grounding meter |

## Layout

```
src/
  api/        types, backend interface, real client, mock backend, language + demo data
  components/ create form, run progress, player, transcript, sources, language switcher, common
  pages/      HomePage, RunPage
  hooks/      useRunWatch (live status + events)
  lib/        formatting helpers
```

The backend selection lives in `src/api/index.ts` (`VITE_USE_MOCK`). Every component depends only
on the `Backend` interface, so real/mock are interchangeable.

See `API_CONTRACT_REVIEW.md` for the frontend's requested changes to the API contract (all now
reflected in `../API_REQUIREMENTS.md`).
