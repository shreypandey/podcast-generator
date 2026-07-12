"""FastAPI adapter for the podcast job runner and compiled Vite frontend."""
from __future__ import annotations

import asyncio
import json
import os
import wave
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Query, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app import config, db, jobs

app = FastAPI(title="Podcast Generator")


class ApiError(Exception):
    def __init__(self, status_code: int, code: str, message: str, details: Any | None = None):
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details or {}


class CreateRunRequest(BaseModel):
    topic: str
    length: str = "medium"
    depth: int = 3
    languages: list[str] | None = None
    angle: str = "balanced"
    focus_questions: list[str] | None = None
    custom_angle: str = ""
    tone: str | None = None
    style: str = "curious_expert"
    custom_style: str = ""


class AddLanguagesRequest(BaseModel):
    languages: list[str]


@app.exception_handler(ApiError)
async def api_error_handler(_request: Request, exc: ApiError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": exc.code, "message": exc.message, "details": exc.details}},
    )


@app.on_event("startup")
def startup() -> None:
    db.init_db()


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "healthy"}


@app.post("/api/runs", status_code=202)
def create_run(req: CreateRunRequest) -> dict[str, str]:
    try:
        run = jobs.create_run(
            req.topic,
            length=req.length,
            depth=req.depth,
            languages=req.languages,
            angle=req.angle,
            focus_questions=req.focus_questions,
            custom_angle=req.custom_angle,
            tone=req.tone or "conversational",
            style=req.style,
            custom_style=req.custom_style,
        )
    except ValueError as e:
        raise ApiError(400, "validation_error", str(e)) from e
    run_id = run["run_id"]
    return {
        "run_id": run_id,
        "status": run["status"],
        "status_url": f"/api/runs/{run_id}",
        "events_url": f"/api/runs/{run_id}/events",
    }


@app.get("/api/runs")
def list_runs(limit: int = Query(default=20, ge=1, le=100)) -> dict[str, list[dict[str, Any]]]:
    return {"runs": [_run_summary(row) for row in db.list_runs(limit)]}


@app.get("/api/runs/{run_id}")
def get_run(run_id: str) -> dict[str, Any]:
    row = _require_run(run_id)
    return _run_detail(row)


@app.post("/api/runs/{run_id}/cancel", status_code=202)
def cancel_run(run_id: str) -> dict[str, str]:
    _require_run(run_id)
    changed = jobs.request_cancel(run_id)
    if not changed:
        raise ApiError(409, "terminal_run", "Run is already terminal")
    row = db.get_run(run_id) or {"status": "canceled"}
    return {"run_id": run_id, "status": row["status"]}


@app.post("/api/runs/{run_id}/languages", status_code=202)
def add_languages(run_id: str, req: AddLanguagesRequest) -> dict[str, Any]:
    try:
        result = jobs.request_language_render(run_id, req.languages)
    except KeyError as e:
        raise ApiError(404, "not_found", "Run not found") from e
    except jobs.RenderArtifactsNotReady as e:
        raise ApiError(409, "language_render_not_ready", str(e)) from e
    except ValueError as e:
        raise ApiError(400, "validation_error", str(e)) from e
    row = result["run"]
    return {
        "run_id": run_id,
        "status": "queued" if result["queued"] else row["status"],
        "languages": _language_state(row),
        "queued_languages": result["queued"],
    }


@app.get("/api/runs/{run_id}/events")
async def run_events(run_id: str) -> StreamingResponse:
    _require_run(run_id)

    async def stream():
        last_id = 0
        while True:
            events = db.list_events(run_id, after_id=last_id)
            for event in events:
                last_id = event["event_id"]
                yield f"data: {json.dumps(_event_response(event), ensure_ascii=False)}\n\n"
            row = db.get_run(run_id)
            if row and row["status"] in db.TERMINAL_STATUSES and not events:
                break
            await asyncio.sleep(1)

    return StreamingResponse(stream(), media_type="text/event-stream")


@app.get("/api/runs/{run_id}/audio")
def get_audio(run_id: str, lang: str | None = None) -> FileResponse:
    row = _require_run(run_id)
    lang = lang or _primary_language(row)
    path = _run_dir(run_id) / f"episode_{lang}.wav"
    if not path.is_file():
        raise ApiError(409, "audio_not_ready", f"Audio is not ready for {lang}")
    return FileResponse(path, media_type="audio/wav", filename=f"{run_id}-{lang}.wav")


@app.get("/api/runs/{run_id}/transcript")
def get_transcript(run_id: str, lang: str | None = None) -> dict[str, Any]:
    row = _require_run(run_id)
    lang = lang or _primary_language(row)
    episode = _read_artifact(run_id, f"episode_{lang}")
    if not episode:
        raise ApiError(409, "transcript_not_ready", f"Transcript is not ready for {lang}")
    script = _read_artifact(run_id, "script")
    cast = _read_artifact(run_id, "cast")
    source = _read_artifact(run_id, "source")
    factsheet = _read_artifact(run_id, "factsheet")
    if not script or not cast or not source or not factsheet:
        raise ApiError(409, "transcript_not_ready", "Transcript artifacts are not ready")

    turns = script.get("turns", [])
    deliveries = episode.get("deliveries") or []
    fact_by_id = {f["id"]: f for f in factsheet.get("facts", [])}
    source_by_id = {s["id"]: s for s in source.get("sources", [])}
    source_numbers, ordered_sources = _source_numbers(turns, fact_by_id, source_by_id)
    names = {
        "host": cast.get("host", {}).get("name", "Host"),
        "expert": cast.get("expert", {}).get("name", "Expert"),
    }

    return {
        "run_id": run_id,
        "topic": row["topic"],
        "language": lang,
        "cast": cast,
        "turns": [
            {
                "idx": turn.get("idx", i),
                "speaker": turn.get("speaker"),
                "speaker_name": names.get(turn.get("speaker"), str(turn.get("speaker", "")).title()),
                "text": turn.get("text", ""),
                "spoken": deliveries[i] if i < len(deliveries) and deliveries[i] else turn.get("spoken") or turn.get("text", ""),
                "move": turn.get("move", ""),
                "verified": bool(turn.get("verified", True)),
                "citation_numbers": _turn_citation_numbers(turn, fact_by_id, source_numbers),
            }
            for i, turn in enumerate(turns)
        ],
        "sources": [
            {
                "number": source_numbers[source_item["id"]],
                "id": source_item["id"],
                "title": source_item.get("title") or source_item.get("url", ""),
                "url": source_item.get("url", ""),
            }
            for source_item in ordered_sources
        ],
        "citations": _citation_details(turns, fact_by_id, source_by_id, source_numbers),
    }


@app.get("/api/runs/{run_id}/sources")
def get_sources(run_id: str) -> dict[str, Any]:
    _require_run(run_id)
    source = _read_artifact(run_id, "source")
    if not source:
        raise ApiError(409, "sources_not_ready", "Sources are not ready")
    factsheet = _read_artifact(run_id, "factsheet") or {"facts": []}
    fact_ids_by_source: dict[str, list[str]] = {}
    for fact in factsheet.get("facts", []):
        for sid in fact.get("source_ids", []):
            fact_ids_by_source.setdefault(sid, []).append(fact.get("id", ""))
    return {
        "run_id": run_id,
        "sources": [
            {
                "id": src.get("id", ""),
                "title": src.get("title", ""),
                "url": src.get("url", ""),
                "origin": src.get("origin", "exa"),
                "query_ids": src.get("query_ids", []),
                "query_intents": src.get("query_intents", []),
                "search_rank": src.get("search_rank"),
                "snippet": _snippet(src),
                "fact_ids": [fid for fid in fact_ids_by_source.get(src.get("id", ""), []) if fid],
            }
            for src in source.get("sources", [])
        ],
    }


@app.get("/api/runs/{run_id}/episode")
def get_episode(run_id: str, lang: str | None = None) -> dict[str, Any]:
    row = _require_run(run_id)
    lang = lang or _primary_language(row)
    episode = _read_artifact(run_id, f"episode_{lang}")
    if not episode:
        raise ApiError(409, "episode_not_ready", f"Episode is not ready for {lang}")
    return episode


@app.get("/api/runs/{run_id}/manifest")
def get_manifest(run_id: str) -> dict[str, Any]:
    _require_run(run_id)
    manifest = _read_artifact(run_id, "manifest")
    if not manifest:
        raise ApiError(409, "manifest_not_ready", "Manifest is not ready")
    return manifest


@app.get("/api/runs/{run_id}/artifacts/{name}")
def get_artifact(run_id: str, name: str) -> dict[str, Any]:
    _require_run(run_id)
    if name not in {"brief", "query_plan", "source", "factsheet", "cast", "outline", "script", "manifest"}:
        raise ApiError(404, "artifact_not_found", "Artifact not found")
    artifact = _read_artifact(run_id, name)
    if not artifact:
        raise ApiError(409, "artifact_not_ready", "Artifact is not ready")
    return artifact


def _require_run(run_id: str) -> dict[str, Any]:
    row = db.get_run(run_id)
    if not row:
        raise ApiError(404, "not_found", "Run not found")
    return row


def _run_summary(row: dict[str, Any]) -> dict[str, Any]:
    detail = _run_detail(row)
    return {key: detail[key] for key in (
        "run_id", "topic", "length", "depth", "status", "stage", "languages",
        "created_at", "started_at", "finished_at", "error", "metrics"
    )}


def _run_detail(row: dict[str, Any]) -> dict[str, Any]:
    ready = _ready_languages(row["run_id"], row["languages"])
    primary = _primary_language(row)
    primary_ready = primary in ready
    return {
        "run_id": row["run_id"],
        "topic": row["topic"],
        "length": row["length"],
        "depth": row["depth"],
        "status": row["status"],
        "stage": row["stage"],
        "languages": _language_state(row),
        "steering": row["steering"],
        "progress": {
            "current": row["progress_current"],
            "total": row["progress_total"],
            "label": row["progress_label"],
        },
        "cast": _read_artifact(row["run_id"], "cast"),
        "created_at": row["created_at"],
        "started_at": row["started_at"],
        "finished_at": row["finished_at"],
        "error": row["error"],
        "metrics": _metrics(row["run_id"], row["languages"]),
        "artifacts": {
            "audio_url": f"/api/runs/{row['run_id']}/audio?lang={primary}" if primary_ready else None,
            "transcript_url": f"/api/runs/{row['run_id']}/transcript?lang={primary}" if primary_ready else None,
            "sources_url": f"/api/runs/{row['run_id']}/sources" if _artifact_path(row["run_id"], "source").is_file() else None,
            "episode_url": f"/api/runs/{row['run_id']}/episode?lang={primary}" if primary_ready else None,
        },
    }


def _language_state(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "requested": row["languages"],
        "ready": _ready_languages(row["run_id"], row["languages"]),
        "primary": _primary_language(row),
    }


def _event_response(event: dict[str, Any]) -> dict[str, Any]:
    return {
        "event_id": event["event_id"],
        "ts": event["ts"],
        "stage": event["stage"],
        "kind": event["kind"],
        "status": event["status"],
        "message": event["message"],
        "payload": event["payload"],
    }


def _run_dir(run_id: str) -> Path:
    return Path(config.RUNS_DIR) / run_id


def _artifact_path(run_id: str, name: str) -> Path:
    return _run_dir(run_id) / f"{name}.json"


def _read_artifact(run_id: str, name: str) -> dict[str, Any] | None:
    path = _artifact_path(run_id, name)
    if not path.is_file():
        return None
    with path.open() as f:
        return json.load(f)


def _primary_language(row: dict[str, Any]) -> str:
    return "en-IN" if "en-IN" in row["languages"] else row["languages"][0]


def _ready_languages(run_id: str, requested: list[str]) -> list[str]:
    ready = []
    for lang in requested:
        if jobs.is_language_ready(run_id, lang):
            ready.append(lang)
    return ready


def _metrics(run_id: str, languages: list[str]) -> dict[str, Any]:
    source = _read_artifact(run_id, "source") or {"sources": []}
    script = _read_artifact(run_id, "script") or {"turns": []}
    turns = script.get("turns", [])
    expert_body = [t for t in turns if t.get("speaker") == "expert" and t.get("move") not in {"intro", "outro"}]
    verified = [t for t in expert_body if t.get("verified", True)]
    grounding_rate = round(len(verified) / len(expert_body) * 100, 1) if expert_body else None
    return {
        "grounding_rate": grounding_rate,
        "source_count": len(source.get("sources", [])) if source else None,
        "turn_count": len(turns) if turns else None,
        "unverified_count": len([t for t in turns if not t.get("verified", True)]),
        "challenge_count": len([t for t in turns if t.get("move") == "challenge"]),
        "duration_sec": {lang: _wav_duration(_run_dir(run_id) / f"episode_{lang}.wav") for lang in languages},
    }


def _wav_duration(path: Path) -> float | None:
    if not path.is_file():
        return None
    with wave.open(str(path), "rb") as wav:
        frames = wav.getnframes()
        rate = wav.getframerate()
    return round(frames / rate, 2) if rate else None


def _source_numbers(turns: list[dict[str, Any]], fact_by_id: dict[str, Any],
                    source_by_id: dict[str, Any]) -> tuple[dict[str, int], list[dict[str, Any]]]:
    numbers: dict[str, int] = {}
    ordered: list[dict[str, Any]] = []
    for turn in turns:
        for fid in turn.get("cited_fact_ids", []):
            fact = fact_by_id.get(fid)
            if not fact:
                continue
            for sid in fact.get("source_ids", []):
                if sid in source_by_id and sid not in numbers:
                    numbers[sid] = len(ordered) + 1
                    ordered.append(source_by_id[sid])
    return numbers, ordered


def _turn_citation_numbers(turn: dict[str, Any], fact_by_id: dict[str, Any],
                           source_numbers: dict[str, int]) -> list[int]:
    numbers: list[int] = []
    for fid in turn.get("cited_fact_ids", []):
        fact = fact_by_id.get(fid)
        if not fact:
            continue
        for sid in fact.get("source_ids", []):
            number = source_numbers.get(sid)
            if number and number not in numbers:
                numbers.append(number)
    return sorted(numbers)


def _citation_details(turns: list[dict[str, Any]], fact_by_id: dict[str, Any],
                      source_by_id: dict[str, Any], source_numbers: dict[str, int]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str]] = set()
    details: list[dict[str, Any]] = []
    for turn in turns:
        for fid in turn.get("cited_fact_ids", []):
            fact = fact_by_id.get(fid)
            if not fact:
                continue
            for sid in fact.get("source_ids", []):
                key = (fid, sid)
                source = source_by_id.get(sid)
                if key in seen or not source or sid not in source_numbers:
                    continue
                seen.add(key)
                quotes = fact.get("source_quotes") or []
                details.append({
                    "number": source_numbers[sid],
                    "fact_id": fid,
                    "source_id": sid,
                    "source_title": source.get("title") or source.get("url", ""),
                    "source_url": source.get("url", ""),
                    "quote": quotes[0] if quotes else fact.get("claim", ""),
                })
    return details


def _snippet(source: dict[str, Any]) -> str:
    highlights = source.get("highlights") or []
    if highlights:
        return str(highlights[0])[:240]
    text = " ".join(str(source.get("text", "")).split())
    return text[:240]


frontend_directory = Path(config.FRONTEND_DIST_DIR)
assets_directory = frontend_directory / "assets"
if assets_directory.exists():
    app.mount("/assets", StaticFiles(directory=assets_directory), name="assets")


@app.get("/{path:path}")
def serve_frontend(path: str) -> FileResponse:
    if path.startswith("api/"):
        raise ApiError(404, "not_found", "API route not found")
    requested_file = frontend_directory / path
    if requested_file.is_file():
        return FileResponse(requested_file)
    index = frontend_directory / "index.html"
    if not index.is_file():
        raise ApiError(404, "frontend_not_built", "Frontend build not found")
    return FileResponse(index)
