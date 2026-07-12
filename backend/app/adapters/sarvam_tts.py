"""Bulbul TTS adapter + WAV combination (stdlib wave, no ffmpeg)."""
from __future__ import annotations

import base64
import io
import time
import wave

from app import config
from app.adapters.sarvam_llm import with_transient_retry


def synth(client, text: str, speaker: str, run, pace: float | None = None,
          lang: str | None = None, stage: str = "render") -> list[str]:
    """Returns list of base64-encoded WAV strings (usually one for short text)."""
    pace = config.TTS_PACE if pace is None else pace
    lang = lang or config.LANGUAGE
    t0 = time.time()
    resp = with_transient_retry(lambda: client.text_to_speech.convert(
        text=text,
        target_language_code=lang,
        speaker=speaker,
        model=config.TTS_MODEL,
        pace=pace,
        output_audio_codec="wav",
    ))
    dt = round(time.time() - t0, 2)
    audios = list(resp.audios or [])
    run.log(stage=stage, kind="tts", speaker=speaker, lang=lang, chars=len(text),
            n_audios=len(audios), latency_s=dt)
    return audios


def _read_wav(b64: str):
    raw = base64.b64decode(b64)
    with wave.open(io.BytesIO(raw), "rb") as w:
        params = w.getparams()
        frames = w.readframes(w.getnframes())
    return params, frames


def combine_to_wav(segments_b64: list[list[str]], out_path: str, gap_s: float | None = None) -> str:
    """Concatenate per-turn base64 WAVs into one file, with a silence gap between turns."""
    gap_s = config.TTS_GAP_SECONDS if gap_s is None else gap_s
    params = None
    chunks: list[bytes] = []
    for turn_audios in segments_b64:
        for b64 in turn_audios:
            p, frames = _read_wav(b64)
            if params is None:
                params = p
            chunks.append(frames)
        if params is not None and gap_s > 0:
            silence = b"\x00" * int(params.framerate * gap_s) * params.sampwidth * params.nchannels
            chunks.append(silence)

    if params is None:
        raise ValueError("No audio to combine")

    with wave.open(out_path, "wb") as w:
        w.setparams(params)
        w.writeframes(b"".join(chunks))
    return out_path
