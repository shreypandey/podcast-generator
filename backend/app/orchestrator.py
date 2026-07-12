"""Minimal linear orchestrator: runs the stages, persists every artifact + a run
manifest (prompts/responses/latency). The 'walking skeleton' of the harness."""
from __future__ import annotations

import datetime as dt
import json
import os
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel

from app import config
from app.artifacts import Brief
from app.stages import citations, dialogue, ground, humanize, plan, render, research


class PipelineCanceled(Exception):
    """Raised when the API/job runner requests cooperative cancellation."""


@dataclass
class Run:
    id: str
    dir: str
    event_sink: Callable[[dict[str, Any]], None] | None = None
    events: list[dict] = field(default_factory=list)

    def log(self, **kw) -> None:
        kw["ts"] = dt.datetime.now().isoformat(timespec="seconds")
        self.events.append(kw)
        if self.event_sink:
            try:
                self.event_sink(dict(kw))
            except Exception as e:  # noqa: BLE001 - observability must not kill a run
                print(f"  · event_sink error: {e}")
        print(f"  · {kw.get('stage','?'):8} {kw.get('kind','')} "
              f"{kw.get('latency_s','')}s {kw.get('title') or kw.get('speaker') or ''}")

    def save_artifact(self, name: str, model: BaseModel) -> None:
        with open(os.path.join(self.dir, f"{name}.json"), "w") as f:
            json.dump(model.model_dump(), f, indent=2, ensure_ascii=False)

    def save_manifest(self) -> None:
        with open(os.path.join(self.dir, "manifest.json"), "w") as f:
            json.dump({"run_id": self.id, "events": self.events}, f, indent=2, ensure_ascii=False)


def _new_run(run_id: str | None = None, runs_dir: str | None = None,
             event_sink: Callable[[dict[str, Any]], None] | None = None) -> Run:
    rid = run_id or dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    rdir = os.path.join(runs_dir or config.RUNS_DIR, rid)
    os.makedirs(rdir, exist_ok=True)
    return Run(id=rid, dir=rdir, event_sink=event_sink)


def run_pipeline(topic: str, length: str = "medium", depth: int = 3,
                 languages: list[str] | None = None,
                 angle: str = "balanced",
                 focus_questions: list[str] | None = None,
                 custom_angle: str = "",
                 tone: str = "conversational",
                 style: str = "curious_expert",
                 custom_style: str = "",
                 run_id: str | None = None,
                 runs_dir: str | None = None,
                 event_sink: Callable[[dict[str, Any]], None] | None = None,
                 cancel_check: Callable[[], bool] | None = None) -> str:
    config.require_keys()
    sarvam = config.sarvam_client()
    exa = config.exa_client()

    run = _new_run(run_id=run_id, runs_dir=runs_dir, event_sink=event_sink)

    def checkpoint(stage: str) -> None:
        if cancel_check and cancel_check():
            run.log(stage=stage, kind="canceled")
            raise PipelineCanceled(f"Run {run.id} canceled")

    brief = Brief(topic=topic, length=length, depth=depth, languages=languages or ["en-IN"],
                  angle=angle, focus_questions=focus_questions or [],
                  custom_angle=custom_angle, tone=tone, style=style,
                  custom_style=custom_style)
    settings = config.resolve_settings(brief)
    brief.angle = settings.angle
    brief.focus_questions = settings.focus_questions
    brief.custom_angle = settings.custom_angle
    brief.tone = settings.tone
    brief.style = settings.style
    brief.custom_style = settings.custom_style
    print(f"Run {run.id} — topic: {topic!r} (length={length}, depth={depth} → "
          f"{settings.num_queries} queries, ≤{settings.max_grounding_sources} grounding sources, "
          f"≤{settings.max_facts} facts, {settings.min_total_turns}-"
          f"{settings.max_total_turns} body turns target ~{settings.target_total_turns}; "
          f"angle={settings.angle}, tone={settings.tone}, style={settings.style})")

    run.save_artifact("brief", brief)

    checkpoint("query_plan")
    query_plan, corpus = research.run(exa, sarvam, brief, settings, run)
    run.save_artifact("query_plan", query_plan)
    run.save_artifact("source", corpus)

    checkpoint("ground")
    factsheet = ground.run(sarvam, corpus, settings, run)
    run.save_artifact("factsheet", factsheet)
    print(f"  {len(factsheet.facts)} facts from {len(corpus.sources)} sources")

    checkpoint("plan")
    cast, outline = plan.run(sarvam, brief.topic, factsheet, settings, run)
    run.save_artifact("cast", cast)
    run.save_artifact("outline", outline)
    print(f"  HOST = {cast.host.name} ({cast.host.gender}/{cast.host.voice}); "
          f"EXPERT = {cast.expert.name} ({cast.expert.gender}/{cast.expert.voice}); "
          f"{len(outline.segments)} segments")

    checkpoint("dialogue")
    scr = dialogue.run(sarvam, brief.topic, factsheet, cast, outline, settings, run)
    run.save_artifact("script", scr)
    for t in scr.turns:
        flag = "" if t.verified else " [UNVERIFIED]"
        print(f"  {t.speaker.upper():6} [{t.move}]: {t.text}{flag}")

    # grounding rate (expert body turns only)
    exp = [t for t in scr.turns if t.speaker == "expert" and t.move not in ("intro", "outro")]
    ok = [t for t in exp if t.verified]
    rate = (len(ok) / len(exp) * 100) if exp else 100.0
    run.log(stage="verify", kind="metric", grounding_rate=round(rate, 1),
            expert_turns=len(exp), verified=len(ok))
    print(f"  grounding: {len(ok)}/{len(exp)} expert turns verified ({rate:.0f}%)")

    # naturalness pass 1: humanize each turn (spoken delivery + pace), then persist
    checkpoint("humanize")
    scr = humanize.run(sarvam, scr, run, settings)
    run.save_artifact("script", scr)

    checkpoint("render")
    episodes = render.run(sarvam, scr, cast, run, brief.languages, settings, cancel_check=checkpoint)
    fact_by_id = {f.id: f for f in factsheet.facts}
    source_by_id = {s.id: s for s in corpus.sources}
    cited = citations.cited_sources(scr, fact_by_id, source_by_id)
    for ep in episodes:
        ep.sources = cited
        run.save_artifact(f"episode_{ep.language}", ep)
        citations.write_transcript_md(
            os.path.join(run.dir, f"transcript_{ep.language}.md"),
            brief.topic, cast, scr, fact_by_id, source_by_id, display_texts=ep.deliveries,
            include_citations=False, include_sources=False, include_verification_flags=False)
        citations.write_transcript_md(
            os.path.join(run.dir, f"transcript_evidence_{ep.language}.md"),
            brief.topic, cast, scr, fact_by_id, source_by_id, display_texts=ep.deliveries,
            include_citations=True, include_sources=True, include_verification_flags=True)

    run.save_manifest()
    print("\n✅ Episodes:")
    for ep in episodes:
        print(f"   [{ep.language}] {ep.audio_path}")
    print(f"   Artifacts + manifest in: {run.dir}")
    primary = next((e for e in episodes if e.language == "en-IN"), episodes[0])
    return primary.audio_path
