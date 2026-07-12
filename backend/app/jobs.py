"""Job runner adapter for API and CLI.

This module owns queueing/state. It deliberately keeps FastAPI and SQLite details out of the
pipeline orchestrator.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable

from app import config, db
from app.artifacts import Brief, Cast, FactSheet, Script, SourceCorpus
from app.orchestrator import PipelineCanceled, Run, run_pipeline
from app.stages import citations, render

VALID_LENGTHS = {"short", "medium", "long"}
STAGE_ORDER = [
    "created", "query_plan", "research", "ground", "annotate", "cast", "plan",
    "dialogue", "verify", "review", "humanize", "render", "citations", "complete",
]
STAGE_LABELS = {
    "created": "Queued",
    "query_plan": "Planning searches",
    "research": "Researching sources",
    "ground": "Grounding sources",
    "annotate": "Annotating evidence",
    "cast": "Casting hosts",
    "plan": "Planning episode",
    "dialogue": "Generating dialogue",
    "verify": "Verifying claims",
    "review": "Reviewing dialogue",
    "humanize": "Humanizing delivery",
    "render": "Rendering audio",
    "citations": "Writing citations",
    "complete": "Complete",
    "failed": "Failed",
}
UNSAFE_EVENT_KEYS = {"user", "response", "usage"}

_executor = ThreadPoolExecutor(max_workers=config.MAX_CONCURRENT_JOBS)
_futures: dict[str, Future] = {}
_language_futures: dict[tuple[str, str], Future] = {}


class RenderArtifactsNotReady(ValueError):
    """Raised when an existing run cannot render a new language yet."""


def normalize_length(length: str) -> str:
    value = (length or "medium").strip().lower()
    if value not in VALID_LENGTHS:
        raise ValueError(f"length must be one of: {', '.join(sorted(VALID_LENGTHS))}")
    return value


def normalize_depth(depth: int) -> int:
    value = int(depth or 3)
    if value < 1 or value > 5:
        raise ValueError("depth must be between 1 and 5")
    return value


def normalize_languages(languages: list[str] | None) -> list[str]:
    raw = languages or ["en-IN"]
    normalized: list[str] = []
    for code in raw:
        value = str(code or "").strip()
        if not value:
            continue
        if value not in config.SUPPORTED_LANGUAGES:
            raise ValueError(f"unsupported language: {value}")
        if value not in normalized:
            normalized.append(value)
    return normalized or ["en-IN"]


def normalize_steering(*, angle: str = "balanced", focus_questions: list[str] | None = None,
                       custom_angle: str = "", tone: str = "conversational",
                       style: str = "curious_expert", custom_style: str = "") -> dict[str, Any]:
    return config.normalize_steering(
        angle=angle,
        focus_questions=focus_questions,
        custom_angle=custom_angle,
        tone=tone,
        style=style,
        custom_style=custom_style,
    )


def new_run_id() -> str:
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    return f"{stamp}-{uuid.uuid4().hex[:6]}"


def create_run(topic: str, length: str = "medium", depth: int = 3,
               languages: list[str] | None = None, *, angle: str = "balanced",
               focus_questions: list[str] | None = None, custom_angle: str = "",
               tone: str = "conversational", style: str = "curious_expert",
               custom_style: str = "", enqueue: bool = True) -> dict[str, Any]:
    topic = " ".join(str(topic or "").split())
    if not topic:
        raise ValueError("topic is required")
    length = normalize_length(length)
    depth = normalize_depth(depth)
    languages = normalize_languages(languages)
    steering = normalize_steering(angle=angle, focus_questions=focus_questions,
                                  custom_angle=custom_angle, tone=tone, style=style,
                                  custom_style=custom_style)
    run_id = new_run_id()
    db.insert_run(run_id, topic, length, depth, languages, steering=steering)
    _append_event(run_id, stage="created", kind="run.created", status="queued",
                  message="Run queued", payload={"languages": languages})
    created = db.get_run(run_id) or {}
    if enqueue:
        enqueue_run(run_id)
    return created


def enqueue_run(run_id: str) -> None:
    if run_id in _futures and not _futures[run_id].done():
        return
    _futures[run_id] = _executor.submit(run_job, run_id)


def request_language_render(run_id: str, languages: list[str], *,
                            enqueue: bool = True,
                            client_factory: Callable[[], Any] = config.sarvam_client,
                            renderer: Callable[..., list[Any]] = render.run,
                            stream: bool = False) -> dict[str, Any]:
    run = db.get_run(run_id)
    if not run:
        raise KeyError(run_id)
    languages = _normalize_extra_languages(languages)
    _require_render_artifacts(run_id)
    db.append_run_languages(run_id, languages)

    queued = [
        lang for lang in languages
        if not is_language_ready(run_id, lang) and not _language_render_pending(run_id, lang)
    ]
    if queued:
        _append_event(run_id, stage="render", kind="language_render.queued", status="running",
                      message="Language render queued", payload={"languages": queued})
        if enqueue:
            future = _executor.submit(
                render_languages_job,
                run_id,
                queued,
                client_factory=client_factory,
                renderer=renderer,
            )
            for lang in queued:
                _language_futures[(run_id, lang)] = future
        else:
            render_languages_job(run_id, queued, client_factory=client_factory,
                                 renderer=renderer, stream=stream)

    return {
        "run": db.get_run(run_id) or run,
        "requested": languages,
        "queued": queued,
    }


def render_languages_job(run_id: str, languages: list[str], *,
                         client_factory: Callable[[], Any] = config.sarvam_client,
                         renderer: Callable[..., list[Any]] = render.run,
                         stream: bool = False) -> dict[str, Any]:
    run_row = db.get_run(run_id)
    if not run_row:
        raise KeyError(run_id)
    languages = _normalize_extra_languages(languages)
    _append_event(run_id, stage="render", kind="language_render.started", status="running",
                  message="Language render started", payload={"languages": languages},
                  stream=stream)
    try:
        rendered = _render_existing_run_languages(
            run_id,
            languages,
            client=client_factory(),
            renderer=renderer,
            stream=stream,
        )
    except Exception as e:  # noqa: BLE001 - preserve failure event for UI/API observers
        _append_event(run_id, stage="render", kind="language_render.failed", status="failed",
                      message="Language render failed", payload={
                          "languages": languages,
                          "error": str(e)[:1000],
                      }, stream=stream)
        raise
    _append_event(run_id, stage="render", kind="language_render.succeeded", status="succeeded",
                  message="Language render complete", payload={"languages": rendered},
                  stream=stream)
    return db.get_run(run_id) or run_row


def is_language_ready(run_id: str, language: str) -> bool:
    run_dir = _run_dir(run_id)
    return (
        (run_dir / f"episode_{language}.json").is_file()
        and (run_dir / f"episode_{language}.wav").is_file()
    )


def request_cancel(run_id: str) -> bool:
    run = db.get_run(run_id)
    if not run:
        raise KeyError(run_id)
    if run["status"] in db.TERMINAL_STATUSES:
        return False
    changed = db.request_cancel(run_id)
    if changed and run["status"] == "queued":
        db.update_run(run_id, status="canceled", stage="failed", finished_at=db.now_iso(),
                      progress_current=1, progress_total=1, progress_label="Canceled")
    _append_event(run_id, stage=run["stage"], kind="run.canceled", status="canceled",
                  message="Cancellation requested", payload={})
    return changed


def run_job(run_id: str, *, pipeline: Callable[..., str] = run_pipeline,
            stream: bool = False) -> dict[str, Any]:
    run = db.get_run(run_id)
    if not run:
        raise KeyError(run_id)
    if run["status"] in db.TERMINAL_STATUSES:
        return run
    if db.cancel_requested(run_id):
        db.update_run(run_id, status="canceled", stage="failed", finished_at=db.now_iso(),
                      progress_current=1, progress_total=1, progress_label="Canceled")
        return db.get_run(run_id) or run

    db.update_run(run_id, status="running", stage="created", started_at=db.now_iso(),
                  progress_current=0, progress_total=len(STAGE_ORDER), progress_label="Starting")
    _append_event(run_id, stage="created", kind="run.started", status="running",
                  message="Run started", payload={}, stream=stream)

    def event_sink(event: dict[str, Any]) -> None:
        stage = str(event.get("stage") or "running")
        kind = str(event.get("kind") or "event")
        payload = _safe_payload(event)
        progress = _progress_for_stage(stage)
        db.update_run(run_id, stage=stage, progress_current=progress["current"],
                      progress_total=progress["total"], progress_label=progress["label"])
        _append_event(run_id, stage=stage, kind=kind, status="running",
                      message=_message_for(event), payload=payload, ts=event.get("ts"),
                      stream=stream)

    try:
        pipeline(
            run["topic"],
            length=run["length"],
            depth=run["depth"],
            languages=run["languages"],
            **run["steering"],
            run_id=run_id,
            runs_dir=config.RUNS_DIR,
            event_sink=event_sink,
            cancel_check=lambda: db.cancel_requested(run_id),
        )
    except PipelineCanceled:
        db.update_run(run_id, status="canceled", stage="failed", finished_at=db.now_iso(),
                      progress_current=1, progress_total=1, progress_label="Canceled")
        _append_event(run_id, stage="failed", kind="run.canceled", status="canceled",
                      message="Run canceled", payload={}, stream=stream)
    except SystemExit as e:
        _fail_run(run_id, str(e), stream=stream)
    except Exception as e:  # noqa: BLE001 - persist failure for API clients
        _fail_run(run_id, str(e), stream=stream)
    else:
        if db.cancel_requested(run_id):
            db.update_run(run_id, status="canceled", stage="failed", finished_at=db.now_iso(),
                          progress_current=1, progress_total=1, progress_label="Canceled")
            _append_event(run_id, stage="failed", kind="run.canceled", status="canceled",
                          message="Run canceled", payload={}, stream=stream)
        else:
            db.update_run(run_id, status="succeeded", stage="complete", finished_at=db.now_iso(),
                          progress_current=len(STAGE_ORDER), progress_total=len(STAGE_ORDER),
                          progress_label="Complete")
            _append_event(run_id, stage="complete", kind="run.succeeded", status="succeeded",
                          message="Run complete", payload={}, stream=stream)
    return db.get_run(run_id) or run


def _render_existing_run_languages(run_id: str, languages: list[str], *, client: Any,
                                   renderer: Callable[..., list[Any]],
                                   stream: bool = False) -> list[str]:
    context = _load_render_context(run_id, stream=stream)
    run = context["run"]
    script = context["script"]
    cast = context["cast"]
    factsheet = context["factsheet"]
    corpus = context["corpus"]
    brief = context["brief"]
    settings = config.resolve_settings(brief)

    missing = [lang for lang in languages if not is_language_ready(run_id, lang)]
    if not missing:
        return []

    episodes = renderer(client, script, cast, run, missing, settings)
    fact_by_id = {f.id: f for f in factsheet.facts}
    source_by_id = {s.id: s for s in corpus.sources}
    cited = citations.cited_sources(script, fact_by_id, source_by_id)
    for ep in episodes:
        ep.sources = cited
        run.save_artifact(f"episode_{ep.language}", ep)
        citations.write_transcript_md(
            os.path.join(run.dir, f"transcript_{ep.language}.md"),
            brief.topic, cast, script, fact_by_id, source_by_id,
            display_texts=ep.deliveries,
            include_citations=False,
            include_sources=False,
            include_verification_flags=False,
        )
        citations.write_transcript_md(
            os.path.join(run.dir, f"transcript_evidence_{ep.language}.md"),
            brief.topic, cast, script, fact_by_id, source_by_id,
            display_texts=ep.deliveries,
            include_citations=True,
            include_sources=True,
            include_verification_flags=True,
        )
    run.save_manifest()
    return [ep.language for ep in episodes]


def _load_render_context(run_id: str, *, stream: bool = False) -> dict[str, Any]:
    run_dir = _run_dir(run_id)
    brief = Brief(**_read_required_artifact(run_id, "brief"))
    script = Script(**_read_required_artifact(run_id, "script"))
    cast = Cast(**_read_required_artifact(run_id, "cast"))
    factsheet = FactSheet(**_read_required_artifact(run_id, "factsheet"))
    corpus = SourceCorpus(**_read_required_artifact(run_id, "source"))
    manifest = _read_json(run_dir / "manifest.json", {"events": []})

    def event_sink(event: dict[str, Any]) -> None:
        stage = str(event.get("stage") or "render")
        kind = str(event.get("kind") or "event")
        _append_event(run_id, stage=stage, kind=kind, status="running",
                      message=_message_for(event), payload=_safe_payload(event),
                      ts=event.get("ts"), stream=stream)

    return {
        "brief": brief,
        "script": script,
        "cast": cast,
        "factsheet": factsheet,
        "corpus": corpus,
        "run": Run(id=run_id, dir=str(run_dir), event_sink=event_sink,
                   events=manifest.get("events", [])),
    }


def _normalize_extra_languages(languages: list[str]) -> list[str]:
    raw = [str(code or "").strip() for code in (languages or []) if str(code or "").strip()]
    if not raw:
        raise ValueError("languages are required")
    return normalize_languages(raw)


def _language_render_pending(run_id: str, language: str) -> bool:
    future = _language_futures.get((run_id, language))
    return bool(future and not future.done())


def _require_render_artifacts(run_id: str) -> None:
    missing = [
        name for name in ["brief", "script", "cast", "factsheet", "source"]
        if not (_run_dir(run_id) / f"{name}.json").is_file()
    ]
    if missing:
        raise RenderArtifactsNotReady(
            "Run artifacts are not ready for language rendering: " + ", ".join(missing)
        )


def _read_required_artifact(run_id: str, name: str) -> dict[str, Any]:
    path = _run_dir(run_id) / f"{name}.json"
    if not path.is_file():
        raise RenderArtifactsNotReady(f"Run artifact is not ready: {name}")
    return _read_json(path, {})


def _read_json(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    if not path.is_file():
        return default
    with path.open() as f:
        return json.load(f)


def _run_dir(run_id: str) -> Path:
    return Path(config.RUNS_DIR) / run_id


def _fail_run(run_id: str, error: str, *, stream: bool = False) -> None:
    db.update_run(run_id, status="failed", stage="failed", finished_at=db.now_iso(),
                  error=error[:1000], progress_current=1, progress_total=1,
                  progress_label="Failed")
    _append_event(run_id, stage="failed", kind="run.failed", status="failed",
                  message="Run failed", payload={"error": error[:1000]}, stream=stream)


def _progress_for_stage(stage: str) -> dict[str, Any]:
    total = len(STAGE_ORDER)
    try:
        current = STAGE_ORDER.index(stage) + 1
    except ValueError:
        current = 1
    return {"current": current, "total": total, "label": STAGE_LABELS.get(stage, stage.title())}


def _safe_payload(event: dict[str, Any]) -> dict[str, Any]:
    payload = {
        key: value for key, value in event.items()
        if key not in {"ts", "stage", "kind"} and key not in UNSAFE_EVENT_KEYS
    }
    return payload


def _message_for(event: dict[str, Any]) -> str:
    stage = str(event.get("stage") or "run")
    kind = str(event.get("kind") or "event")
    speaker = event.get("speaker")
    title = event.get("title")
    suffix = f" {speaker or title}" if (speaker or title) else ""
    return f"{stage}.{kind}{suffix}"


def _append_event(run_id: str, *, stage: str, kind: str, status: str,
                  message: str, payload: dict[str, Any], ts: str | None = None,
                  stream: bool = False) -> None:
    event_id = db.append_event(run_id, stage=stage, kind=kind, status=status,
                               message=message, payload=payload, ts=ts)
    if stream:
        print(json.dumps({
            "event_id": event_id,
            "stage": stage,
            "kind": kind,
            "status": status,
            "message": message,
            "payload": payload,
        }, ensure_ascii=False))


def main() -> None:
    parser = argparse.ArgumentParser(prog="app.jobs", description="Run podcast jobs through the API job runner.")
    sub = parser.add_subparsers(dest="cmd", required=True)
    run_p = sub.add_parser("run", help="create and execute a podcast run")
    run_p.add_argument("topic", nargs="+")
    run_p.add_argument("--length", choices=sorted(VALID_LENGTHS), default="medium")
    run_p.add_argument("--depth", type=int, choices=[1, 2, 3, 4, 5], default=3)
    run_p.add_argument("--langs", default="en-IN",
                       help="comma-separated Bulbul language codes, e.g. en-IN,hi-IN,ta-IN")
    run_p.add_argument("--angle", default="balanced", choices=sorted(config.ANGLE_PRESETS))
    run_p.add_argument("--focus", action="append", default=[],
                       help="focus question; repeat or comma-separate multiple questions")
    run_p.add_argument("--custom-angle", default="")
    run_p.add_argument("--tone", default="conversational", choices=sorted(config.TONE_PRESETS))
    run_p.add_argument("--style", default="curious_expert", choices=sorted(config.STYLE_PRESETS))
    run_p.add_argument("--custom-style", default="")
    run_p.add_argument("--wait", action="store_true", help="stream job events while running")
    lang_p = sub.add_parser("render-language", help="render more languages for an existing run")
    lang_p.add_argument("run_id")
    lang_p.add_argument("--langs", required=True,
                        help="comma-separated Bulbul language codes, e.g. hi-IN,ta-IN")
    lang_p.add_argument("--wait", action="store_true", help="stream language render events")
    args = parser.parse_args()

    if args.cmd == "run":
        languages = [c.strip() for c in args.langs.split(",") if c.strip()]
        focus_questions = [
            item.strip()
            for value in args.focus
            for item in str(value).split(",")
            if item.strip()
        ]
        run = create_run(" ".join(args.topic), length=args.length, depth=args.depth,
                         languages=languages, angle=args.angle, focus_questions=focus_questions,
                         custom_angle=args.custom_angle, tone=args.tone, style=args.style,
                         custom_style=args.custom_style, enqueue=False)
        print(f"Run {run['run_id']} queued")
        final = run_job(run["run_id"], stream=args.wait)
        print(f"Run {final['run_id']} {final['status']}")
        if final["status"] != "succeeded":
            raise SystemExit(1)
    elif args.cmd == "render-language":
        languages = [c.strip() for c in args.langs.split(",") if c.strip()]
        try:
            normalized = _normalize_extra_languages(languages)
            _require_render_artifacts(args.run_id)
            db.append_run_languages(args.run_id, normalized)
            final = render_languages_job(args.run_id, normalized, stream=args.wait)
        except KeyError as e:
            raise SystemExit(f"Run not found: {e.args[0]}") from e
        except ValueError as e:
            raise SystemExit(str(e)) from e
        print(f"Run {final['run_id']} language render complete: {', '.join(normalized)}")


if __name__ == "__main__":
    main()
