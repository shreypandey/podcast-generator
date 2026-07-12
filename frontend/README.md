# Frontend

React + Vite + TypeScript UI for the podcast generator.

## What it does

- Starts podcast runs through `POST /api/runs`.
- Watches run state through polling/SSE.
- Shows the cast, language selector, audio player, transcript, and sources.
- Supports the in-browser mock backend for offline UI work.
- Renders against the FastAPI backend in production through same-origin `/api/*` calls.

## Setup

```bash
npm install
```

## Run

### Mock mode

```bash
VITE_USE_MOCK=1 npm run dev
```

### Real backend

```bash
npm run dev
```

The Vite dev server proxies `/api/*` to the backend on `http://localhost:8000` by default.
Override with `VITE_API_TARGET` if needed.

## Build

```bash
npm run build
npm run preview
```

The production backend serves the compiled `dist/` bundle same-origin.

## UI surface

- Home page: create run form, recent runs.
- Run page: pipeline timeline, cancel button, cast card, language switcher, audio player,
  transcript, and sources.
- The activity pane was removed; the run page now focuses on the pipeline timeline and the
  content outputs.

## Files

| Path | Purpose |
|---|---|
| `src/api/` | backend interface, mock backend, real client, types, language metadata |
| `src/components/` | form, timeline, player, transcript, sources, shared UI |
| `src/pages/` | home and run pages |
| `src/hooks/` | live run watcher |

See `../API_REQUIREMENTS.md` for the current API contract.
