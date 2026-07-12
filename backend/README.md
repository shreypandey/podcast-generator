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
- `GROUND_MAX_WORKERS` defaults to `5`
- `HUMANIZE_MAX_WORKERS` defaults to `10`
- `REVIEW_MAX_WORKERS` defaults to `3`
- `RENDER_MAX_WORKERS` defaults to `4`
- `LOCALIZATION_MODE` defaults to `translate`; set to `llm` to use Sarvam-105B native podcast localization for non-English turns
- `PHRASE_RENDER_MAX_WORKERS` defaults to `2`
- `TTS_RETRY_TRIES` defaults to `5`
- `PHRASE_MAX_CHARS` defaults to `155`
- `PHRASE_PAUSE_SHORT_MS` defaults to `120`
- `PHRASE_PAUSE_MEDIUM_MS` defaults to `240`
- `PHRASE_PAUSE_LONG_MS` defaults to `420`
- `HOST_TURN_GAP_MS` defaults to `180`
- `EXPERT_TURN_GAP_MS` defaults to `260`
- `OUTRO_TURN_GAP_MS` defaults to `520`
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
- `delivery_plan_<lang>.json`
- `episode_<lang>.json`
- `episode_<lang>.wav`
- `transcript_<lang>.md`
- `manifest.json`

## Audio Delivery

Render uses phrase-level delivery planning. The canonical script remains unchanged; after
translation/humanization each turn is split into short spoken phrases, each with its own TTS pace
and pause-after timing. The plan is saved as `delivery_plan_<lang>.json` and copied into
`episode_<lang>.json` for inspection.

Sarvam Bulbul exposes pace per TTS request, not per word. Phrase pacing therefore sends multiple
small TTS requests per turn and assembles a phrase timeline. `PHRASE_RENDER_MAX_WORKERS` and
`TTS_RETRY_TRIES` are intentionally separate from the general render worker count because phrase
rendering increases request volume and can hit rate limits.

## Localization Modes

Non-English rendering has two paths:

- `LOCALIZATION_MODE=translate`: Mayura translates the canonical English turn, then the
  per-language humanizer adds spoken delivery. This is the compatibility/default path.
- `LOCALIZATION_MODE=llm`: Sarvam-105B localizes the canonical English turn directly into native
  podcast speech, preserving facts while avoiding literal English idioms and code-mixed filler.
  Mayura+humanizer remains the fallback if the LLM output is empty or not mostly native script.
  Each turn is localized independently, with recent English turns supplied as context, so render
  can keep per-turn localization and phrase-level TTS work parallel.

## Tests

```bash
uv run python -m unittest discover -s tests
```

## Notes

- Cancellation is cooperative.
- SQLite stores run state only; audio and transcripts remain file-based.
- Increase `MAX_CONCURRENT_JOBS` if you want multiple runs to execute in parallel.
- Raise `HUMANIZE_MAX_WORKERS` if you want more parallel LLM calls inside one run.
- The API and UI should talk through `/api/*` only.
