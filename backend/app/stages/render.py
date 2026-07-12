"""Render stage: VerifiedScript -> one Episode per language (translate → TTS → assemble).

Per language, each turn's (translate + TTS) work is independent, so it runs in PARALLEL;
audio segments are assembled in order. English (en-IN) speaks the humanized `turn.spoken`;
other languages translate the canonical `turn.text` (English fillers/acronym-casing must NOT
be translated — Sarvam-Translate's spoken form naturalizes the target). Voices are reused
across languages (Bulbul speakers are cross-language); only the TTS language code changes.
Per-language transcripts (with citations) are written by the orchestrator from `Episode.deliveries`."""
from __future__ import annotations

import concurrent.futures
import os
from collections.abc import Callable

from app import config
from app.adapters import sarvam_translate, sarvam_tts
from app.agents import humanizer
from app.artifacts import Cast, DeliveryPlan, Episode, Script
from app.stages import delivery as delivery_stage


def _voice(cast: Cast, speaker: str) -> str:
    return cast.expert.voice if speaker == "expert" else cast.host.voice


def run(client, script: Script, cast: Cast, run, languages: list[str], settings=None,
        cancel_check: Callable[[str], None] | None = None) -> list[Episode]:
    n = len(script.turns)
    episodes: list[Episode] = []

    for lang in languages:
        if cancel_check:
            cancel_check("render")

        def work(i: int, lang=lang):
            turn = script.turns[i]
            if lang == "en-IN":
                delivery, pace = (turn.spoken or turn.text), turn.pace  # precomputed English
            else:
                translated = sarvam_translate.translate(client, turn.text, lang, run)
                delivery, pace = humanizer.humanize_lang(client, translated, lang, run, settings)  # native fillers
            turn_delivery = delivery_stage.plan_turn_delivery(turn, delivery, pace)
            rendered_phrases = []
            for phrase in turn_delivery.phrases:
                audios = sarvam_tts.synth(client, phrase.text, _voice(cast, turn.speaker), run,
                                          pace=phrase.pace, lang=lang)
                rendered_phrases.append((audios, phrase.pause_after_ms))
            return i, delivery, rendered_phrases, turn_delivery

        results: list = [None] * n
        if n:
            with concurrent.futures.ThreadPoolExecutor(
                    max_workers=min(config.PHRASE_RENDER_MAX_WORKERS, n)) as ex:
                for fut in concurrent.futures.as_completed([ex.submit(work, i) for i in range(n)]):
                    i, delivery, audios, turn_delivery = fut.result()
                    results[i] = (delivery, audios, turn_delivery)

        deliveries = [r[0] for r in results]
        segments = [r[1] for r in results]
        delivery_plan = [r[2] for r in results]
        out_path = os.path.join(run.dir, f"episode_{lang}.wav")
        sarvam_tts.combine_phrase_timeline_to_wav(segments, out_path)
        plan = DeliveryPlan(language=lang, turns=delivery_plan)
        run.save_artifact(f"delivery_plan_{lang}", plan)
        run.log(stage="render", kind="delivery_plan", lang=lang, turns=n,
                phrases=sum(len(t.phrases) for t in delivery_plan))
        episodes.append(Episode(language=lang, audio_path=out_path,
                                transcript=script.turns, deliveries=deliveries,
                                delivery_plan=delivery_plan))
    return episodes
