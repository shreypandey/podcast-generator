# podcast-backend

M0 walking skeleton for the podcast generator. Proves the toolchain end-to-end:

```
topic → Exa (1 source) → Sarvam-105B (1 fact) → Sarvam-105B (2-turn Host/Expert)
      → Bulbul TTS (2 voices) → combined episode.wav
```

See `../REQUIREMENTS.md`, `../ARCHITECTURE.md`, `../SCRIPT_GENERATION.md`, `../progress.md`.

## Setup

```bash
cp .env.example .env      # then fill in EXA_API_KEY and SARVAM_API_KEY
uv sync
```

## Run

```bash
uv run python -m app.run "the economics of desalination"
```

Outputs a timestamped `runs/<id>/` with `brief.json`, `source.json`, `factsheet.json`,
`script.json`, `episode.json`, `episode.wav`, and `manifest.json` (prompts, responses,
latencies).

## Layout

| Path | Role |
|---|---|
| `app/config.py` | env, model ids, voice mapping, client factories |
| `app/artifacts.py` | typed artifacts (pydantic) |
| `app/adapters/` | one adapter per service: `exa`, `sarvam_llm`, `sarvam_tts` |
| `app/stages/` | `research → ground → script → render` |
| `app/orchestrator.py` | linear runner + artifact persistence + run manifest |
| `app/run.py` | CLI entrypoint |

## Scope (M0)

English-only, one source, one fact, two turns, no Director/verification/translate/frontend —
all deliberately deferred to later milestones.
