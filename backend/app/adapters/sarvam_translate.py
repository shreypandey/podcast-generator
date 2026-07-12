"""Sarvam-Translate adapter (Mayura): English VerifiedScript turn -> a target language.

`mayura:v1` covers exactly the 11 Bulbul-speakable languages with modern-colloquial +
spoken-form output (1000-char/request limit; sarvam-translate:v1 is formal-only). English is an
identity bypass so the per-language render loop is uniform."""
from __future__ import annotations

import re
import time

from app import config
from app.adapters.sarvam_llm import with_transient_retry

_LIMIT = 1000  # mayura:v1 per-request char limit


def _chunks(text: str, size: int = _LIMIT) -> list[str]:
    if len(text) <= size:
        return [text]
    parts, cur = [], ""
    for sent in re.split(r"(?<=[.!?।]) ", text):  # English + Devanagari danda boundaries
        if cur and len(cur) + len(sent) + 1 > size:
            parts.append(cur.strip())
            cur = sent
        else:
            cur = (cur + " " + sent).strip()
    if cur:
        parts.append(cur.strip())
    return parts or [text[:size]]


def translate(client, text: str, target_lang: str, run, source_lang: str = "en-IN") -> str:
    text = (text or "").strip()
    if not text or target_lang == source_lang:
        return text  # English bypass / identity — keeps the render loop uniform

    t0 = time.time()
    out: list[str] = []
    for chunk in _chunks(text):
        resp = with_transient_retry(lambda ch=chunk: client.text.translate(
            input=ch,
            source_language_code=source_lang,
            target_language_code=target_lang,
            mode=config.TRANSLATE_MODE,
            model=config.TRANSLATE_MODEL,
            output_script=config.TRANSLATE_SCRIPT,
        ))
        out.append(getattr(resp, "translated_text", "") or "")
    run.log(stage="render", kind="translate", target=target_lang, chars=len(text),
            latency_s=round(time.time() - t0, 2))
    return " ".join(p for p in out if p).strip()
