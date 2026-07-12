# Backend

FastAPI backend, job runner, and podcast pipeline orchestrator.

## What lives here

- `app/main.py` exposes the HTTP API and serves the compiled frontend in production.
- `app/jobs.py` owns queueing, SQLite run metadata, cancellation, and the CLI job path.
- `app/orchestrator.py` remains the pipeline entrypoint.
- `app/stages/` and `app/agents/` contain the generation/render pipeline.
- `app/adapters/` contains the external service clients.

## Setup

```bash
cp .env.example .env
uv sync
```

Required env vars:

- `EXA_API_KEY`
- `SARVAM_API_KEY`

Runtime env vars:

- `DATABASE_PATH` defaults to `./data/app.db`
- `MAX_CONCURRENT_JOBS` defaults to `1`
- `RUNS_DIR` defaults to `./runs`
- `FRONTEND_DIST_DIR` defaults to `../frontend/dist`

## Run

### API server

```bash
uv run uvicorn app.main:app --reload
```

### Direct pipeline CLI

```bash
uv run python -m app.run "the economics of desalination" --langs en-IN,hi-IN
```

### Job runner CLI

```bash
uv run python -m app.jobs run "the economics of desalination" --langs en-IN,hi-IN --wait
```

## Outputs

Pipeline runs write artifacts under `RUNS_DIR/<run_id>/`, including:

- `brief.json`
- `query_plan.json`
- `source.json`
- `factsheet.json`
- `cast.json`
- `outline.json`
- `script.json`
- `episode_<lang>.json`
- `episode_<lang>.wav`
- `transcript_<lang>.md`
- `manifest.json`

## Tests

```bash
uv run python -m unittest discover -s tests
```

## Notes

- Cancellation is cooperative.
- SQLite stores run state only; audio and transcripts remain file-based.
- Increase `MAX_CONCURRENT_JOBS` if you want multiple runs to execute in parallel.
- The API and UI should talk through `/api/*` only.
