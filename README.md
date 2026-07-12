# Podcast Generator

Grounded, multilingual podcast generation with a real backend job runner and a React UI.
The system researches a topic, grounds claims, writes a Host-vs-Expert script, renders audio,
and serves the results through a FastAPI API.

## Current shape

- One repository.
- One FastAPI backend.
- One Vite frontend.
- One Docker image for local and Railway deploys.
- SQLite for run metadata.
- File artifacts for generated audio, transcripts, and manifests.
- Configurable job concurrency through `MAX_CONCURRENT_JOBS`.

## What it does

- Builds a grounded two-host episode from a topic.
- Supports multiple Bulbul languages per run.
- Exposes live run status, transcripts, sources, and audio through `/api/*`.
- Lets the UI start runs, cancel runs, and switch languages.
- Keeps the direct CLI for local testing.

## Layout

| Path | Purpose |
|---|---|
| [`backend/`](backend/) | FastAPI API, job runner, orchestrator, adapters, and pipeline stages |
| [`frontend/`](frontend/) | React + Vite UI |
| Root docs | [`REQUIREMENTS.md`](REQUIREMENTS.md), [`ARCHITECTURE.md`](ARCHITECTURE.md), [`SCRIPT_GENERATION.md`](SCRIPT_GENERATION.md), [`API_REQUIREMENTS.md`](API_REQUIREMENTS.md), [`progress.md`](progress.md) |

## Run locally

### Backend/API

```bash
cd backend
cp .env.example .env
uv sync
uv run uvicorn app.main:app --reload
```

### Pipeline CLI

```bash
cd backend
uv run python -m app.run "the economics of desalination" --langs en-IN,hi-IN
```

### Job runner CLI

```bash
cd backend
uv run python -m app.jobs run "the economics of desalination" --langs en-IN,hi-IN --wait
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

For mock-only UI testing:

```bash
cd frontend
VITE_USE_MOCK=1 npm run dev
```

The frontend proxies `/api/*` to the backend in development. In production, the backend serves
the compiled `frontend/dist/` bundle same-origin.

## Docker

The root `Dockerfile` builds the frontend and backend into one container. Use it for local
verification and Railway deploys.
Set `MAX_CONCURRENT_JOBS` in the environment to allow multiple runs to execute in parallel.

```bash
docker build -t podcast-generator .
docker run --rm -p 8001:8000 --env-file backend/.env podcast-generator
```

## Languages

Supported Bulbul languages are the 11 codes exposed in the UI and API. The default primary
language is `en-IN`.
