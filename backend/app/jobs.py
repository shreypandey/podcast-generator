"""Job runner adapter for API and CLI.

This module owns queueing/state. It deliberately keeps FastAPI and SQLite details out of the
pipeline orchestrator.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any, Callable

from app import config, db
from app.orchestrator import PipelineCanceled, run_pipeline

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


if __name__ == "__main__":
    main()
