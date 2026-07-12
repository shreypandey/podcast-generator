"""SQLite metadata store for API/job runs.

The pipeline artifacts remain file-based under RUNS_DIR. SQLite only tracks run state and a
frontend-safe event stream.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sqlite3
from typing import Any

from app import config

TERMINAL_STATUSES = {"succeeded", "failed", "canceled"}


def now_iso() -> str:
    return dt.datetime.now(dt.UTC).isoformat(timespec="seconds")


def _path(path: str | None = None) -> str:
    return path or config.DATABASE_PATH


def _connect(path: str | None = None) -> sqlite3.Connection:
    db_path = _path(path)
    parent = os.path.dirname(db_path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(path: str | None = None) -> None:
    with _connect(path) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS runs (
                run_id TEXT PRIMARY KEY,
                topic TEXT NOT NULL,
                length TEXT NOT NULL,
                depth INTEGER NOT NULL,
                languages_json TEXT NOT NULL,
                steering_json TEXT NOT NULL DEFAULT '{}',
                status TEXT NOT NULL,
                stage TEXT NOT NULL,
                progress_current INTEGER NOT NULL DEFAULT 0,
                progress_total INTEGER NOT NULL DEFAULT 1,
                progress_label TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                started_at TEXT,
                finished_at TEXT,
                error TEXT,
                cancel_requested INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS run_events (
                event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                ts TEXT NOT NULL,
                stage TEXT NOT NULL,
                kind TEXT NOT NULL,
                status TEXT NOT NULL,
                message TEXT NOT NULL DEFAULT '',
                payload_json TEXT NOT NULL DEFAULT '{}',
                FOREIGN KEY(run_id) REFERENCES runs(run_id)
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_run_events_run_id ON run_events(run_id, event_id)")
        _ensure_column(conn, "runs", "steering_json", "TEXT NOT NULL DEFAULT '{}'")


def insert_run(run_id: str, topic: str, length: str, depth: int, languages: list[str],
               steering: dict[str, Any] | None = None, path: str | None = None) -> None:
    init_db(path)
    with _connect(path) as conn:
        conn.execute(
            """
            INSERT INTO runs (
                run_id, topic, length, depth, languages_json, steering_json, status, stage,
                progress_current, progress_total, progress_label, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, 'queued', 'created', 0, 1, 'Queued', ?)
            """,
            (run_id, topic, length, depth, json.dumps(languages),
             json.dumps(steering or {}, ensure_ascii=False), now_iso()),
        )


def get_run(run_id: str, path: str | None = None) -> dict[str, Any] | None:
    init_db(path)
    with _connect(path) as conn:
        row = conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
    return _row_to_run(row) if row else None


def list_runs(limit: int = 20, path: str | None = None) -> list[dict[str, Any]]:
    init_db(path)
    limit = max(1, min(100, int(limit or 20)))
    with _connect(path) as conn:
        rows = conn.execute(
            "SELECT * FROM runs ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [_row_to_run(row) for row in rows]


def update_run(run_id: str, *, status: str | None = None, stage: str | None = None,
               progress_current: int | None = None, progress_total: int | None = None,
               progress_label: str | None = None, started_at: str | None = None,
               finished_at: str | None = None, error: str | None = None,
               path: str | None = None) -> None:
    init_db(path)
    updates: list[str] = []
    params: list[Any] = []
    values = {
        "status": status,
        "stage": stage,
        "progress_current": progress_current,
        "progress_total": progress_total,
        "progress_label": progress_label,
        "started_at": started_at,
        "finished_at": finished_at,
        "error": error,
    }
    for key, value in values.items():
        if value is not None:
            updates.append(f"{key} = ?")
            params.append(value)
    if not updates:
        return
    params.append(run_id)
    with _connect(path) as conn:
        conn.execute(f"UPDATE runs SET {', '.join(updates)} WHERE run_id = ?", params)


def append_run_languages(run_id: str, languages: list[str], path: str | None = None) -> list[str]:
    init_db(path)
    with _connect(path) as conn:
        row = conn.execute("SELECT languages_json FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        if row is None:
            raise KeyError(run_id)
        requested = json.loads(row["languages_json"] or "[]")
        for lang in languages:
            if lang not in requested:
                requested.append(lang)
        conn.execute(
            "UPDATE runs SET languages_json = ? WHERE run_id = ?",
            (json.dumps(requested, ensure_ascii=False), run_id),
        )
        return requested


def request_cancel(run_id: str, path: str | None = None) -> bool:
    init_db(path)
    with _connect(path) as conn:
        cur = conn.execute(
            "UPDATE runs SET cancel_requested = 1 WHERE run_id = ? AND status NOT IN ('succeeded', 'failed', 'canceled')",
            (run_id,),
        )
        return cur.rowcount > 0


def cancel_requested(run_id: str, path: str | None = None) -> bool:
    run = get_run(run_id, path)
    return bool(run and run["cancel_requested"])


def append_event(run_id: str, *, stage: str, kind: str, status: str,
                 message: str = "", payload: dict[str, Any] | None = None,
                 ts: str | None = None, path: str | None = None) -> int:
    init_db(path)
    with _connect(path) as conn:
        cur = conn.execute(
            """
            INSERT INTO run_events (run_id, ts, stage, kind, status, message, payload_json)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                ts or now_iso(),
                stage,
                kind,
                status,
                message,
                json.dumps(payload or {}, ensure_ascii=False),
            ),
        )
        return int(cur.lastrowid)


def list_events(run_id: str, after_id: int = 0, path: str | None = None) -> list[dict[str, Any]]:
    init_db(path)
    with _connect(path) as conn:
        rows = conn.execute(
            """
            SELECT * FROM run_events
            WHERE run_id = ? AND event_id > ?
            ORDER BY event_id ASC
            """,
            (run_id, after_id),
        ).fetchall()
    return [_row_to_event(row) for row in rows]


def _row_to_run(row: sqlite3.Row) -> dict[str, Any]:
    data = dict(row)
    data["languages"] = json.loads(data.pop("languages_json") or "[]")
    data["steering"] = json.loads(data.pop("steering_json") or "{}")
    data["cancel_requested"] = bool(data["cancel_requested"])
    return data


def _row_to_event(row: sqlite3.Row) -> dict[str, Any]:
    data = dict(row)
    data["payload"] = json.loads(data.pop("payload_json") or "{}")
    return data


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    cols = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
