"""Podcast quality eval harness.

Runs a fixed topic suite through the live pipeline, then scores the persisted artifacts with
deterministic checks. The harness is intentionally resumable because a 10-topic live suite is
slow and API failures should not discard finished runs.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import os
import re
import statistics
import wave
from collections import Counter
from pathlib import Path
from typing import Any

from app import config
from app.artifacts import Brief, Cast, FactSheet, Script, SourceCorpus
from app.orchestrator import Run, run_pipeline
from app.stages import citations, render

DEFAULT_SUITE = Path(config.APP_DIR) / "evals" / "podcast_quality_10.json"
RESULTS_DIR = Path(config.APP_DIR) / "evals" / "results"
SCRIPT_RANGES = {
    "hi-IN": [(0x0900, 0x097F)],
    "mr-IN": [(0x0900, 0x097F)],
    "bn-IN": [(0x0980, 0x09FF)],
    "ta-IN": [(0x0B80, 0x0BFF)],
    "te-IN": [(0x0C00, 0x0C7F)],
    "kn-IN": [(0x0C80, 0x0CFF)],
    "ml-IN": [(0x0D00, 0x0D7F)],
    "gu-IN": [(0x0A80, 0x0AFF)],
    "pa-IN": [(0x0A00, 0x0A7F)],
    "od-IN": [(0x0B00, 0x0B7F)],
}


def load_suite(path: Path = DEFAULT_SUITE) -> dict[str, Any]:
    with path.open(encoding="utf-8") as f:
        suite = json.load(f)
    if not suite.get("topics"):
        raise SystemExit(f"No topics found in suite: {path}")
    suite.setdefault("suite_id", path.stem)
    suite.setdefault("length", "medium")
    suite.setdefault("depth", 4)
    suite.setdefault("languages", ["en-IN"])
    suite.setdefault("translation_languages", ["hi-IN", "ta-IN"])
    return suite


def run_english_suite(suite: dict[str, Any], *, force: bool = False) -> dict[str, Any]:
    manifest = load_eval_manifest(suite)
    length = str(suite.get("length") or "medium")
    depth = int(suite.get("depth") or 4)

    for item in manifest["runs"]:
        topic = item["topic"]
        run_id = item["run_id"]
        if not force and _english_complete(run_id):
            item["english_status"] = "succeeded"
            item["run_dir"] = str(_run_dir(run_id))
            save_eval_manifest(suite, manifest)
            print(f"[skip] {run_id} already has English outputs")
            continue

        print(f"\n=== English eval {item['idx']}/10: {topic} ===")
        item["english_started_at"] = _now()
        item["english_status"] = "running"
        save_eval_manifest(suite, manifest)
        try:
            run_pipeline(
                topic,
                length=length,
                depth=depth,
                languages=["en-IN"],
                angle=item.get("angle", "balanced"),
                focus_questions=item.get("focus_questions", []),
                custom_angle=item.get("custom_angle", ""),
                tone=item.get("tone", "conversational"),
                style=item.get("style", "curious_expert"),
                custom_style=item.get("custom_style", ""),
                run_id=run_id,
                runs_dir=config.RUNS_DIR,
            )
        except Exception as e:  # noqa: BLE001 - keep suite resumable
            item["english_status"] = "failed"
            item["english_error"] = str(e)[:1000]
            item["english_finished_at"] = _now()
            save_eval_manifest(suite, manifest)
            print(f"[failed] {run_id}: {e}")
            continue

        item["english_status"] = "succeeded"
        item["run_dir"] = str(_run_dir(run_id))
        item["english_finished_at"] = _now()
        save_eval_manifest(suite, manifest)
    return manifest


def analyze_english_suite(suite: dict[str, Any]) -> dict[str, Any]:
    manifest = load_eval_manifest(suite)
    runs = [analyze_english_run(item) for item in manifest["runs"]]
    report = {
        "suite_id": suite["suite_id"],
        "generated_at": _now(),
        "phase": "english",
        "summary": _summary(runs),
        "runs": runs,
    }
    out = _result_dir(suite)
    out.mkdir(parents=True, exist_ok=True)
    _write_json(out / "english_report.json", report)
    _write_markdown(out / "english_report.md", _english_markdown(report))
    print(f"English report: {out / 'english_report.md'}")
    return report


def render_translations_suite(suite: dict[str, Any], *, languages: list[str],
                              force: bool = False) -> dict[str, Any]:
    config.require_keys()
    client = config.sarvam_client()
    manifest = load_eval_manifest(suite)

    for item in manifest["runs"]:
        run_id = item["run_id"]
        if not _english_complete(run_id):
            item["translation_status"] = "skipped_no_english"
            save_eval_manifest(suite, manifest)
            print(f"[skip] {run_id} has no complete English output")
            continue
        missing = [lang for lang in languages if force or not _language_complete(run_id, lang)]
        if not missing:
            item["translation_status"] = "succeeded"
            save_eval_manifest(suite, manifest)
            print(f"[skip] {run_id} already has translations: {', '.join(languages)}")
            continue

        print(f"\n=== Translation eval {item['idx']}/10: {run_id} -> {', '.join(missing)} ===")
        item["translation_started_at"] = _now()
        item["translation_status"] = "running"
        save_eval_manifest(suite, manifest)
        try:
            _render_existing_run(client, run_id, missing)
        except Exception as e:  # noqa: BLE001 - keep suite resumable
            item["translation_status"] = "failed"
            item["translation_error"] = str(e)[:1000]
            item["translation_finished_at"] = _now()
            save_eval_manifest(suite, manifest)
            print(f"[failed] {run_id}: {e}")
            continue
        item["translation_status"] = "succeeded"
        item["translated_languages"] = sorted(set(item.get("translated_languages", []) + missing))
        item["translation_finished_at"] = _now()
        save_eval_manifest(suite, manifest)
    return manifest


def analyze_translations_suite(suite: dict[str, Any], *, languages: list[str]) -> dict[str, Any]:
    manifest = load_eval_manifest(suite)
    runs = [analyze_translation_run(item, languages) for item in manifest["runs"]]
    flattened = [lang for run in runs for lang in run["languages"]]
    report = {
        "suite_id": suite["suite_id"],
        "generated_at": _now(),
        "phase": "translations",
        "languages": languages,
        "summary": _summary(flattened),
        "runs": runs,
    }
    out = _result_dir(suite)
    out.mkdir(parents=True, exist_ok=True)
    _write_json(out / "translation_report.json", report)
    _write_markdown(out / "translation_report.md", _translation_markdown(report))
    print(f"Translation report: {out / 'translation_report.md'}")
    return report


def analyze_english_run(item: dict[str, Any]) -> dict[str, Any]:
    run_id = item["run_id"]
    run_dir = _run_dir(run_id)
    brief = _read_json(run_dir / "brief.json", {})
    query_plan = _read_json(run_dir / "query_plan.json", {"queries": []})
    source = _read_json(run_dir / "source.json", {"sources": []})
    factsheet = _read_json(run_dir / "factsheet.json", {"facts": []})
    script = _read_json(run_dir / "script.json", {"turns": []})
    episode = _read_json(run_dir / "episode_en-IN.json", {})
    manifest = _read_json(run_dir / "manifest.json", {"events": []})

    turns = script.get("turns", [])
    facts = factsheet.get("facts", [])
    sources = source.get("sources", [])
    fact_by_id = {f.get("id"): f for f in facts}
    used_fact_ids = _used_fact_ids(turns)
    cited_source_ids = _source_ids_for_facts(used_fact_ids, fact_by_id)
    expert_body = [t for t in turns if t.get("speaker") == "expert" and t.get("move") not in {"intro", "outro"}]
    verified_expert = [t for t in expert_body if t.get("verified", True)]
    grounding_rate = round(len(verified_expert) / len(expert_body) * 100, 1) if expert_body else None
    duration = _wav_duration(run_dir / "episode_en-IN.wav")
    missing = _missing_files(run_dir, [
        "brief.json", "query_plan.json", "source.json", "factsheet.json",
        "cast.json", "outline.json", "script.json", "episode_en-IN.json",
        "episode_en-IN.wav", "transcript_en-IN.md", "manifest.json",
    ])

    host_cited = [t.get("idx") for t in turns if t.get("speaker") == "host" and t.get("cited_fact_ids")]
    expert_missing_cites = [
        t.get("idx") for t in expert_body
        if not t.get("cited_fact_ids") and len(str(t.get("text", "")).split()) > 8
    ]
    expert_questions = [
        t.get("idx") for t in expert_body
        if "?" in str(t.get("text", ""))
    ]
    unverified = [t.get("idx") for t in turns if not t.get("verified", True)]
    type_counts = Counter(str(f.get("fact_type", "background")) for f in facts)
    role_counts = Counter(str(f.get("story_role", "explain")) for f in facts)
    intent_counts = Counter(
        intent for s in sources for intent in s.get("query_intents", [])
    )
    warnings = _english_warnings(
        missing=missing,
        source_count=len(sources),
        fact_count=len(facts),
        used_fact_count=len(used_fact_ids),
        source_coverage=_pct(len(cited_source_ids), len(sources)),
        grounding_rate=grounding_rate,
        unverified=unverified,
        host_cited=host_cited,
        expert_missing_cites=expert_missing_cites,
        expert_questions=expert_questions,
        challenge_count=len([t for t in turns if t.get("move") == "challenge"]),
        duration=duration,
        angle=item.get("angle") or brief.get("angle"),
        type_counts=type_counts,
    )
    score = _score_english(warnings, grounding_rate, missing)

    return {
        "topic_id": item["topic_id"],
        "topic": item["topic"],
        "run_id": run_id,
        "status": item.get("english_status"),
        "score": score,
        "missing_files": missing,
        "query_count": len(query_plan.get("queries", [])),
        "source_count": len(sources),
        "source_intents": dict(intent_counts),
        "fact_count": len(facts),
        "fact_types": dict(type_counts),
        "story_roles": dict(role_counts),
        "used_fact_count": len(used_fact_ids),
        "used_source_count": len(cited_source_ids),
        "source_coverage_pct": _pct(len(cited_source_ids), len(sources)),
        "turn_count": len(turns),
        "speaker_turns": dict(Counter(t.get("speaker", "unknown") for t in turns)),
        "avg_words_per_turn": _avg([len(str(t.get("text", "")).split()) for t in turns]),
        "expert_body_turns": len(expert_body),
        "verified_expert_turns": len(verified_expert),
        "grounding_rate": grounding_rate,
        "unverified_turns": unverified,
        "host_cited_turns": host_cited,
        "expert_missing_citation_turns": expert_missing_cites,
        "expert_question_turns": expert_questions,
        "challenge_count": len([t for t in turns if t.get("move") == "challenge"]),
        "duration_sec": duration,
        "episode_deliveries": len(episode.get("deliveries", [])),
        "manifest_event_count": len(manifest.get("events", [])),
        "warnings": warnings,
    }


def analyze_translation_run(item: dict[str, Any], languages: list[str]) -> dict[str, Any]:
    run_id = item["run_id"]
    run_dir = _run_dir(run_id)
    script = _read_json(run_dir / "script.json", {"turns": []})
    english_duration = _wav_duration(run_dir / "episode_en-IN.wav")
    english_markers = _citation_marker_count(run_dir / "transcript_en-IN.md")
    results = []

    for lang in languages:
        episode = _read_json(run_dir / f"episode_{lang}.json", {})
        deliveries = episode.get("deliveries", [])
        duration = _wav_duration(run_dir / f"episode_{lang}.wav")
        script_stats = _native_script_stats(" ".join(deliveries), lang)
        marker_count = _citation_marker_count(run_dir / f"transcript_{lang}.md")
        warnings = _translation_warnings(
            lang=lang,
            run_dir=run_dir,
            turn_count=len(script.get("turns", [])),
            deliveries=deliveries,
            duration=duration,
            english_duration=english_duration,
            native_ratio=script_stats["native_ratio"],
            latin_ratio=script_stats["latin_ratio"],
            marker_count=marker_count,
            english_markers=english_markers,
        )
        results.append({
            "language": lang,
            "score": _score_translation(warnings),
            "duration_sec": duration,
            "duration_ratio_vs_english": _ratio(duration, english_duration),
            "deliveries": len(deliveries),
            "empty_deliveries": len([d for d in deliveries if not str(d).strip()]),
            "native_ratio": script_stats["native_ratio"],
            "latin_ratio": script_stats["latin_ratio"],
            "citation_markers": marker_count,
            "warnings": warnings,
        })

    return {
        "topic_id": item["topic_id"],
        "topic": item["topic"],
        "run_id": run_id,
        "languages": results,
    }


def _render_existing_run(client, run_id: str, languages: list[str]) -> None:
    run_dir = _run_dir(run_id)
    brief = Brief(**_read_json(run_dir / "brief.json", {}))
    script = Script(**_read_json(run_dir / "script.json", {}))
    cast = Cast(**_read_json(run_dir / "cast.json", {}))
    factsheet = FactSheet(**_read_json(run_dir / "factsheet.json", {}))
    corpus = SourceCorpus(**_read_json(run_dir / "source.json", {}))
    settings = config.resolve_settings(brief)
    existing_manifest = _read_json(run_dir / "manifest.json", {"events": []})
    run = Run(id=run_id, dir=str(run_dir), events=existing_manifest.get("events", []))

    episodes = render.run(client, script, cast, run, languages, settings)
    fact_by_id = {f.id: f for f in factsheet.facts}
    source_by_id = {s.id: s for s in corpus.sources}
    cited = citations.cited_sources(script, fact_by_id, source_by_id)
    for ep in episodes:
        ep.sources = cited
        run.save_artifact(f"episode_{ep.language}", ep)
        citations.write_transcript_md(
            str(run_dir / f"transcript_{ep.language}.md"),
            brief.topic, cast, script, fact_by_id, source_by_id,
            display_texts=ep.deliveries,
        )
    run.save_manifest()


def load_eval_manifest(suite: dict[str, Any]) -> dict[str, Any]:
    path = _eval_manifest_path(suite)
    base = {
        "suite_id": suite["suite_id"],
        "created_at": _now(),
        "length": suite.get("length", "medium"),
        "depth": suite.get("depth", 4),
        "runs": [_topic_run_item(suite, i, topic) for i, topic in enumerate(suite["topics"], start=1)],
    }
    if not path.is_file():
        return base
    existing = _read_json(path, {})
    by_topic = {item.get("topic_id"): item for item in existing.get("runs", [])}
    for item in base["runs"]:
        item.update(by_topic.get(item["topic_id"], {}))
    base["created_at"] = existing.get("created_at", base["created_at"])
    base["updated_at"] = existing.get("updated_at")
    return base


def save_eval_manifest(suite: dict[str, Any], manifest: dict[str, Any]) -> None:
    manifest["updated_at"] = _now()
    path = _eval_manifest_path(suite)
    path.parent.mkdir(parents=True, exist_ok=True)
    _write_json(path, manifest)


def _topic_run_item(suite: dict[str, Any], idx: int, topic: dict[str, Any]) -> dict[str, Any]:
    topic_id = topic["id"]
    return {
        "idx": idx,
        "topic_id": topic_id,
        "topic": topic["topic"],
        "run_id": f"eval-{suite['suite_id']}-{idx:02d}-{_slug(topic_id)}",
        "angle": topic.get("angle", "balanced"),
        "focus_questions": topic.get("focus_questions", []),
        "custom_angle": topic.get("custom_angle", ""),
        "tone": topic.get("tone", "conversational"),
        "style": topic.get("style", "curious_expert"),
        "custom_style": topic.get("custom_style", ""),
    }


def _english_complete(run_id: str) -> bool:
    run_dir = _run_dir(run_id)
    return (
        (run_dir / "script.json").is_file()
        and (run_dir / "episode_en-IN.json").is_file()
        and (run_dir / "episode_en-IN.wav").is_file()
    )


def _language_complete(run_id: str, lang: str) -> bool:
    run_dir = _run_dir(run_id)
    return (run_dir / f"episode_{lang}.json").is_file() and (run_dir / f"episode_{lang}.wav").is_file()


def _english_warnings(**kw) -> list[str]:
    warnings = []
    missing = kw["missing"]
    if missing:
        warnings.append(f"missing files: {', '.join(missing)}")
    if kw["source_count"] < 4:
        warnings.append("low source count")
    if kw["fact_count"] < 8:
        warnings.append("low final fact count")
    if kw["used_fact_count"] < max(3, math.ceil(max(kw["fact_count"], 1) * 0.3)):
        warnings.append("low fact utilization")
    if kw["source_coverage"] is not None and kw["source_coverage"] < 50:
        warnings.append("low cited-source coverage")
    if kw["grounding_rate"] is not None and kw["grounding_rate"] < 90:
        warnings.append("grounding below 90%")
    if kw["unverified"]:
        warnings.append("unverified turns present")
    if kw["host_cited"]:
        warnings.append("host has cited facts")
    if kw["expert_missing_cites"]:
        warnings.append("expert turns missing citations")
    if kw["expert_questions"]:
        warnings.append("expert asks questions")
    if kw["duration"] is None:
        warnings.append("missing English audio")
    elif kw["duration"] < 180:
        warnings.append("episode may be too short for medium length")
    elif kw["duration"] > 900:
        warnings.append("episode may be too long for medium length")
    if kw["angle"] == "mythbusting" and kw["type_counts"].get("misconception", 0) == 0:
        warnings.append("myth-busting angle has no misconception facts")
    if kw["angle"] == "controversy" and not (
        kw["type_counts"].get("caveat", 0) or kw["type_counts"].get("counterclaim", 0)
    ):
        warnings.append("controversy angle has no caveat/counterclaim facts")
    return warnings


def _translation_warnings(**kw) -> list[str]:
    warnings = []
    lang = kw["lang"]
    run_dir = kw["run_dir"]
    if not (run_dir / f"episode_{lang}.json").is_file():
        warnings.append("missing episode artifact")
    if not (run_dir / f"episode_{lang}.wav").is_file():
        warnings.append("missing audio")
    if not (run_dir / f"transcript_{lang}.md").is_file():
        warnings.append("missing transcript")
    if len(kw["deliveries"]) != kw["turn_count"]:
        warnings.append("delivery count does not match turn count")
    if any(not str(d).strip() for d in kw["deliveries"]):
        warnings.append("empty translated deliveries")
    if lang in SCRIPT_RANGES and kw["native_ratio"] < 0.35 and kw["latin_ratio"] > 0.35:
        warnings.append("possible romanization or wrong script")
    ratio = _ratio(kw["duration"], kw["english_duration"])
    if ratio is not None and (ratio < 0.55 or ratio > 1.9):
        warnings.append("translated duration ratio looks abnormal")
    if kw["english_markers"] and kw["marker_count"] < kw["english_markers"]:
        warnings.append("translated transcript has fewer citation markers")
    return warnings


def _score_english(warnings: list[str], grounding_rate: float | None, missing: list[str]) -> int:
    score = 100
    score -= min(30, len(missing) * 8)
    if grounding_rate is None:
        score -= 15
    elif grounding_rate < 100:
        score -= min(25, int((100 - grounding_rate) * 0.7))
    heavy = {
        "host has cited facts": 12,
        "unverified turns present": 12,
        "expert turns missing citations": 8,
        "low cited-source coverage": 8,
        "low fact utilization": 6,
        "expert asks questions": 5,
    }
    for warning in warnings:
        score -= heavy.get(warning, 3)
    return max(0, min(100, score))


def _score_translation(warnings: list[str]) -> int:
    score = 100
    heavy = {
        "missing episode artifact": 25,
        "missing audio": 25,
        "missing transcript": 15,
        "delivery count does not match turn count": 15,
        "possible romanization or wrong script": 18,
        "translated transcript has fewer citation markers": 10,
    }
    for warning in warnings:
        score -= heavy.get(warning, 5)
    return max(0, min(100, score))


def _summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    scores = [r.get("score") for r in rows if isinstance(r.get("score"), int)]
    warning_counts = Counter(w for r in rows for w in r.get("warnings", []))
    return {
        "count": len(rows),
        "score_avg": round(statistics.mean(scores), 1) if scores else None,
        "score_min": min(scores) if scores else None,
        "score_max": max(scores) if scores else None,
        "warning_counts": dict(warning_counts),
    }


def _english_markdown(report: dict[str, Any]) -> str:
    lines = [
        f"# English Eval Report — {report['suite_id']}",
        "",
        f"Generated: {report['generated_at']}",
        "",
        "## Summary",
        "",
        f"- Runs: {report['summary']['count']}",
        f"- Average score: {report['summary']['score_avg']}",
        f"- Score range: {report['summary']['score_min']}–{report['summary']['score_max']}",
        "",
        "## Runs",
        "",
        "| Topic | Score | Grounding | Sources | Facts | Used Facts | Challenges | Duration | Warnings |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for row in report["runs"]:
        warnings = "; ".join(row["warnings"]) or "none"
        lines.append(
            f"| {row['topic_id']} | {row['score']} | {_fmt(row['grounding_rate'])}% | "
            f"{row['source_count']} | {row['fact_count']} | {row['used_fact_count']} | "
            f"{row['challenge_count']} | {_fmt(row['duration_sec'])}s | {warnings} |"
        )
    lines += ["", "## Warning Counts", ""]
    for warning, count in sorted(report["summary"]["warning_counts"].items(), key=lambda kv: (-kv[1], kv[0])):
        lines.append(f"- {warning}: {count}")
    return "\n".join(lines) + "\n"


def _translation_markdown(report: dict[str, Any]) -> str:
    lines = [
        f"# Translation Eval Report — {report['suite_id']}",
        "",
        f"Generated: {report['generated_at']}",
        f"Languages: {', '.join(report['languages'])}",
        "",
        "## Summary",
        "",
        f"- Language renders: {report['summary']['count']}",
        f"- Average score: {report['summary']['score_avg']}",
        "",
        "## Runs",
        "",
        "| Topic | Lang | Score | Duration Ratio | Native Ratio | Latin Ratio | Citations | Warnings |",
        "|---|---|---:|---:|---:|---:|---:|---|",
    ]
    for run in report["runs"]:
        for row in run["languages"]:
            warnings = "; ".join(row["warnings"]) or "none"
            lines.append(
                f"| {run['topic_id']} | {row['language']} | {row['score']} | "
                f"{_fmt(row['duration_ratio_vs_english'])} | {_fmt(row['native_ratio'])} | "
                f"{_fmt(row['latin_ratio'])} | {row['citation_markers']} | {warnings} |"
            )
    lines += ["", "## Warning Counts", ""]
    for warning, count in sorted(report["summary"]["warning_counts"].items(), key=lambda kv: (-kv[1], kv[0])):
        lines.append(f"- {warning}: {count}")
    return "\n".join(lines) + "\n"


def _native_script_stats(text: str, lang: str) -> dict[str, float]:
    letters = [ch for ch in text if ch.isalpha()]
    if not letters:
        return {"native_ratio": 0.0, "latin_ratio": 0.0}
    ranges = SCRIPT_RANGES.get(lang, [])
    native = sum(1 for ch in letters if any(lo <= ord(ch) <= hi for lo, hi in ranges))
    latin = sum(1 for ch in letters if ("A" <= ch <= "Z") or ("a" <= ch <= "z"))
    return {
        "native_ratio": round(native / len(letters), 3),
        "latin_ratio": round(latin / len(letters), 3),
    }


def _used_fact_ids(turns: list[dict[str, Any]]) -> list[str]:
    seen: list[str] = []
    for turn in turns:
        for fid in turn.get("cited_fact_ids", []):
            if fid and fid not in seen:
                seen.append(fid)
    return seen


def _source_ids_for_facts(fact_ids: list[str], fact_by_id: dict[str, dict[str, Any]]) -> list[str]:
    seen: list[str] = []
    for fid in fact_ids:
        for sid in fact_by_id.get(fid, {}).get("source_ids", []):
            if sid and sid not in seen:
                seen.append(sid)
    return seen


def _missing_files(run_dir: Path, names: list[str]) -> list[str]:
    return [name for name in names if not (run_dir / name).is_file()]


def _citation_marker_count(path: Path) -> int:
    if not path.is_file():
        return 0
    return len(re.findall(r"\[\d+\]", path.read_text(encoding="utf-8", errors="ignore")))


def _wav_duration(path: Path) -> float | None:
    if not path.is_file():
        return None
    with wave.open(str(path), "rb") as wav:
        rate = wav.getframerate()
        frames = wav.getnframes()
    return round(frames / rate, 2) if rate else None


def _read_json(path: Path, default):
    if not path.is_file():
        return default
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _write_markdown(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")


def _result_dir(suite: dict[str, Any]) -> Path:
    return RESULTS_DIR / suite["suite_id"]


def _eval_manifest_path(suite: dict[str, Any]) -> Path:
    return _result_dir(suite) / "eval_manifest.json"


def _run_dir(run_id: str) -> Path:
    return Path(config.RUNS_DIR) / run_id


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower()).strip("-")
    return slug[:50] or "topic"


def _now() -> str:
    return dt.datetime.now(dt.UTC).isoformat(timespec="seconds")


def _avg(values: list[int]) -> float | None:
    return round(statistics.mean(values), 1) if values else None


def _pct(part: int, total: int) -> float | None:
    return round(part / total * 100, 1) if total else None


def _ratio(value: float | None, base: float | None) -> float | None:
    return round(value / base, 3) if value is not None and base else None


def _fmt(value) -> str:
    return "n/a" if value is None else str(value)


def _parse_langs(value: str | None, suite: dict[str, Any]) -> list[str]:
    raw = value or ",".join(suite.get("translation_languages") or ["hi-IN", "ta-IN"])
    langs = [lang.strip() for lang in raw.split(",") if lang.strip()]
    bad = [lang for lang in langs if lang not in config.SUPPORTED_LANGUAGES or lang == "en-IN"]
    if bad:
        raise SystemExit(f"Unsupported translation language(s): {', '.join(bad)}")
    return langs


def main() -> None:
    parser = argparse.ArgumentParser(prog="app.evals", description="Run podcast quality eval suites.")
    parser.add_argument("--suite", default=str(DEFAULT_SUITE), help="path to eval suite JSON")
    sub = parser.add_subparsers(dest="cmd", required=True)

    run_en = sub.add_parser("run-english", help="run English-only generation for every topic")
    run_en.add_argument("--force", action="store_true")

    sub.add_parser("analyze-english", help="analyze English artifacts")

    render_p = sub.add_parser("render-translations", help="render translations from existing English scripts")
    render_p.add_argument("--langs", default=None, help="comma-separated target languages, default from suite")
    render_p.add_argument("--force", action="store_true")

    analyze_t = sub.add_parser("analyze-translations", help="analyze translated artifacts")
    analyze_t.add_argument("--langs", default=None, help="comma-separated target languages, default from suite")

    all_p = sub.add_parser("run-all", help="run English, analyze, render translations, analyze")
    all_p.add_argument("--langs", default=None, help="comma-separated target languages, default from suite")
    all_p.add_argument("--force-english", action="store_true")
    all_p.add_argument("--force-translations", action="store_true")

    args = parser.parse_args()
    suite = load_suite(Path(args.suite))

    if args.cmd == "run-english":
        run_english_suite(suite, force=args.force)
    elif args.cmd == "analyze-english":
        analyze_english_suite(suite)
    elif args.cmd == "render-translations":
        render_translations_suite(suite, languages=_parse_langs(args.langs, suite), force=args.force)
    elif args.cmd == "analyze-translations":
        analyze_translations_suite(suite, languages=_parse_langs(args.langs, suite))
    elif args.cmd == "run-all":
        langs = _parse_langs(args.langs, suite)
        run_english_suite(suite, force=args.force_english)
        analyze_english_suite(suite)
        render_translations_suite(suite, languages=langs, force=args.force_translations)
        analyze_translations_suite(suite, languages=langs)


if __name__ == "__main__":
    main()
