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
from app.artifacts import Cast, Episode, Script


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
            audios = sarvam_tts.synth(client, delivery, _voice(cast, turn.speaker), run,
                                      pace=pace, lang=lang)
            return i, delivery, audios

        results: list = [None] * n
        if n:
            with concurrent.futures.ThreadPoolExecutor(
                    max_workers=min(config.RENDER_MAX_WORKERS, n)) as ex:
                for fut in concurrent.futures.as_completed([ex.submit(work, i) for i in range(n)]):
                    i, delivery, audios = fut.result()
                    results[i] = (delivery, audios)

        deliveries = [r[0] for r in results]
        segments = [r[1] for r in results]
        out_path = os.path.join(run.dir, f"episode_{lang}.wav")
        sarvam_tts.combine_to_wav(segments, out_path)
        episodes.append(Episode(language=lang, audio_path=out_path,
                                transcript=script.turns, deliveries=deliveries))
    return episodes
