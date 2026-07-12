# API Requirements for Frontend and Railway POC

This document is the frontend/backend contract for the deployable POC. It is intentionally
smaller than the full product requirements in `REQUIREMENTS.md`.

## Deployment Assumption

- One Railway service.
- One Docker container.
- FastAPI serves both `/api/*` routes and the compiled Vite frontend.
- Frontend calls the backend with same-origin relative URLs such as `fetch("/api/runs")`.
- SQLite stores run/job metadata.
- Generated artifacts live on the Railway volume.

Runtime paths:

```text
DATABASE_PATH=/app/data/app.db
RUNS_DIR=/app/data/runs
FRONTEND_DIST_DIR=/app/frontend/dist
```

Local defaults may use:

```text
DATABASE_PATH=./data/app.db
RUNS_DIR=./runs
FRONTEND_DIST_DIR=../frontend/dist
```

## Minimum Change Plan

Make one small, mergeable change at a time:

1. Add configuration only: `DATABASE_PATH`, `RUNS_DIR`, `FRONTEND_DIST_DIR`.
2. Add SQLite metadata tables without changing the pipeline behavior.
3. Add FastAPI `/api/health`.
4. Add `POST /api/runs` with topic/length/depth/languages and a fake or no-op background job.
5. Wire `POST /api/runs` to the existing orchestrator.
6. Add read endpoints for status, events, transcript, sources, audio, and cancel.
7. Add Vite frontend that only consumes the documented endpoints.
8. Add Dockerfile that builds frontend first, then runs FastAPI.

Agents should avoid broad refactors while these steps are in progress. Prefer adding new files
over changing existing pipeline code until the API boundary is stable.

## Run Status Model

Run status values:

```text
queued
running
succeeded
failed
canceled
```

Recommended stage values:

```text
created
query_plan
research
ground
annotate
cast
plan
dialogue
verify
review
humanize
render
citations
complete
failed
```

All timestamps are ISO 8601 strings.

## Language Model

The API is language-aware from the first frontend contract.

- `POST /api/runs` accepts `languages`.
- `GET /api/runs/{run_id}` reports requested, ready, and primary languages.
- Audio and transcript endpoints accept `?lang=...`.
- Default language is `en-IN`.

Language codes should be BCP-47 strings supported by the render pipeline. The POC must support
`en-IN`; additional supported Bulbul languages should be accepted as the render pipeline enables
them.

Language readiness shape:

```json
{
  "requested": ["en-IN", "hi-IN", "ta-IN"],
  "ready": ["en-IN"],
  "primary": "en-IN"
}
```

## Error Shape

All non-2xx JSON errors should use:

```json
{
  "error": {
    "code": "not_found",
    "message": "Run not found",
    "details": {}
  }
}
```

## Endpoints

### `GET /api/health`

Health check for Railway and local development.

Response `200`:

```json
{
  "status": "healthy"
}
```

### `POST /api/runs`

Create a podcast generation run. The request should return quickly and start generation in the
background.

Request:

```json
{
  "topic": "the economics of desalination",
  "length": "medium",
  "depth": 3,
  "languages": ["en-IN"]
}
```

Validation:

- `topic`: required non-empty string.
- `length`: `short`, `medium`, or `long`; default `medium`.
- `depth`: integer `1` through `5`; default `3`.
- `languages`: non-empty array of supported language codes; default `["en-IN"]`.

Optional future steering fields may be accepted when backend support exists:

```json
{
  "focus_questions": ["What tradeoffs matter most?"],
  "tone": "curious and direct",
  "user_sources": ["https://example.com/source"]
}
```

Response `202`:

```json
{
  "run_id": "20260712-153441",
  "status": "queued",
  "status_url": "/api/runs/20260712-153441",
  "events_url": "/api/runs/20260712-153441/events"
}
```

### `GET /api/runs`

List recent runs for the dashboard/history view.

Query params:

- `limit`: optional integer, default `20`, max `100`.

Response `200`:

```json
{
  "runs": [
    {
      "run_id": "20260712-153441",
      "topic": "the economics of desalination",
      "length": "medium",
      "depth": 3,
      "status": "succeeded",
      "stage": "complete",
      "languages": {
        "requested": ["en-IN"],
        "ready": ["en-IN"],
        "primary": "en-IN"
      },
      "created_at": "2026-07-12T15:34:41+05:30",
      "started_at": "2026-07-12T15:34:42+05:30",
      "finished_at": "2026-07-12T15:38:10+05:30",
      "error": null,
      "artifacts": {
        "audio_url": "/api/runs/20260712-153441/audio",
        "transcript_url": "/api/runs/20260712-153441/transcript",
        "sources_url": "/api/runs/20260712-153441/sources"
      }
    }
  ]
}
```

### `GET /api/runs/{run_id}`

Return run status and artifact links.

Response `200`:

```json
{
  "run_id": "20260712-153441",
  "topic": "the economics of desalination",
  "length": "medium",
  "depth": 3,
  "status": "running",
  "stage": "dialogue",
  "languages": {
    "requested": ["en-IN", "hi-IN", "ta-IN"],
    "ready": ["en-IN"],
    "primary": "en-IN"
  },
  "progress": {
    "current": 6,
    "total": 12,
    "label": "Generating dialogue"
  },
  "cast": {
    "host": {
      "name": "Ananya",
      "background": "sharp generalist host",
      "gender": "female",
      "voice": "priya"
    },
    "expert": {
      "name": "Dr. Mehta",
      "background": "water policy economist",
      "gender": "male",
      "voice": "aditya"
    }
  },
  "created_at": "2026-07-12T15:34:41+05:30",
  "started_at": "2026-07-12T15:34:42+05:30",
  "finished_at": null,
  "error": null,
  "metrics": {
    "grounding_rate": null,
    "source_count": 6,
    "turn_count": null,
    "unverified_count": null,
    "challenge_count": null,
    "duration_sec": {
      "en-IN": null
    }
  },
  "artifacts": {
    "audio_url": null,
    "transcript_url": null,
    "sources_url": "/api/runs/20260712-153441/sources",
    "episode_url": null
  }
}
```

Return `404` if the run does not exist.

### `POST /api/runs/{run_id}/cancel`

Cancel a queued or running podcast generation run.

Response `202`:

```json
{
  "run_id": "20260712-153441",
  "status": "canceled"
}
```

Return `404` if the run does not exist. Return `409` if the run is already terminal
(`succeeded`, `failed`, or `canceled`).

### `GET /api/runs/{run_id}/events`

Stream run progress using Server-Sent Events. The frontend may also poll
`GET /api/runs/{run_id}` if SSE is not implemented yet.

Response content type:

```text
text/event-stream
```

Each event data payload is JSON:

```json
{
  "event_id": 17,
  "ts": "2026-07-12T15:35:12+05:30",
  "stage": "ground",
  "kind": "source_done",
  "status": "running",
  "message": "Grounded source S3",
  "payload": {
    "source_id": "S3",
    "n_facts": 4,
    "progress": {
      "current": 3,
      "total": 6,
      "label": "Grounding source 3 of 6"
    }
  }
}
```

Minimum event names:

```text
run.created
run.updated
run.succeeded
run.failed
```

Recommended stage-specific payload fields:

- `research`: `sources_found`.
- `ground`: `sources_done`, `sources_total`, `facts_so_far`.
- `dialogue`: `turns_done`, `turns_total`, `speaker`, `move`.
- `render`: `languages_done`, `languages_total`, `lang`.

### `GET /api/runs/{run_id}/audio?lang=en-IN`

Return generated audio for one language. `lang` defaults to the run's primary language.

Response:

- `200 audio/wav` when the language audio exists.
- `404` if the run does not exist.
- `409` if the run exists but that language is not ready.

### `GET /api/runs/{run_id}/transcript?lang=en-IN`

Return frontend-ready transcript data with citation links for one language. `lang` defaults to the
run's primary language.

For non-English languages:

- `turns[].text` is the canonical English turn used as the citation anchor.
- `turns[].spoken` is the translated/humanized delivery actually spoken.
- `turns[].verified` must be returned unchanged, including `false` for unsupported turns.

Response `200`:

```json
{
  "run_id": "20260712-153441",
  "topic": "the economics of desalination",
  "language": "en-IN",
  "cast": {
    "host": {
      "name": "Ananya",
      "background": "sharp generalist host",
      "gender": "female",
      "voice": "priya"
    },
    "expert": {
      "name": "Dr. Mehta",
      "background": "water policy economist",
      "gender": "male",
      "voice": "aditya"
    }
  },
  "turns": [
    {
      "idx": 0,
      "speaker": "host",
      "speaker_name": "Ananya",
      "text": "Welcome back...",
      "spoken": "So, welcome back...",
      "move": "intro",
      "verified": true,
      "citation_numbers": []
    },
    {
      "idx": 3,
      "speaker": "expert",
      "speaker_name": "Dr. Mehta",
      "text": "Reverse osmosis...",
      "spoken": "Reverse osmosis...",
      "move": "explain",
      "verified": true,
      "citation_numbers": [1]
    }
  ],
  "sources": [
    {
      "number": 1,
      "id": "S1",
      "title": "Desalination overview",
      "url": "https://example.com/desalination"
    }
  ],
  "citations": [
    {
      "number": 1,
      "fact_id": "F3",
      "source_id": "S1",
      "source_title": "Desalination overview",
      "source_url": "https://example.com/desalination",
      "quote": "Reverse osmosis is the most widely used desalination process."
    }
  ]
}
```

Return `409` if that language transcript is not ready.

### `GET /api/runs/{run_id}/sources`

Return sources discovered for the run. This can become available before audio is ready.

Response `200`:

```json
{
  "run_id": "20260712-153441",
  "sources": [
    {
      "id": "S1",
      "title": "Desalination overview",
      "url": "https://example.com/desalination",
      "origin": "exa",
      "query_ids": ["Q1"],
      "query_intents": ["core_explainer"],
      "search_rank": 1,
      "snippet": "Reverse osmosis is the most widely used desalination process.",
      "fact_ids": ["F3", "F4"]
    }
  ]
}
```

Return `409` if sources are not ready.

### `GET /api/runs/{run_id}/episode?lang=en-IN`

Return the raw episode artifact for one language. This is mainly for debugging.

Response `200`:

```json
{
  "audio_path": "/app/data/runs/20260712-153441/episode.wav",
  "transcript": [],
  "sources": []
}
```

This endpoint is mainly for debugging. Frontend should prefer `/transcript`, `/sources`, and
`/audio`.

## Optional Debug Endpoints

These are useful for internal inspection but not required for the first frontend:

```text
GET /api/runs/{run_id}/manifest
GET /api/runs/{run_id}/artifacts/{name}
```

Allowed artifact names:

```text
brief
query_plan
source
factsheet
cast
outline
script
episode
manifest
```

## Frontend Requirements

The first frontend should support:

- Create run form: topic, length, depth, languages.
- Progress state from polling or SSE.
- Cancel button while a run is queued or running.
- Cast display once `cast` is available.
- Language selector using `languages.requested` and `languages.ready`.
- Audio player once `/audio?lang=...` is ready.
- Transcript view once `/transcript?lang=...` is ready.
- Citation hover/details using `citations[].quote`.
- Sources panel once `/sources` is ready.
- Error view when run status is `failed`.

Frontend should not need any environment variable for the backend URL in the Railway POC.

## FastAPI Static Serving Requirement

All API routes must be registered before the SPA catch-all route.

Required route layout:

```text
/api/*
/assets/*
/{path:path}
```

The catch-all must return `index.html` for frontend routes and must not intercept `/api/*`.
