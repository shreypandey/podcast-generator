"""Delivery planning: split final spoken text into phrase-level TTS chunks.

This stage owns how the audio breathes. It must not change the canonical script text or invent
new wording; it only breaks the already-final spoken delivery into chunks and assigns pace/pause
controls to each chunk.
"""
from __future__ import annotations

import re

from app import config
from app.artifacts import DeliveryPhrase, Turn, TurnDelivery

_ABBREVIATIONS = (
    "Dr.", "Mr.", "Mrs.", "Ms.", "Prof.", "Sr.", "Jr.", "vs.", "e.g.", "i.e.",
    "U.S.", "U.K.", "U.N.", "No.", "Fig.",
)
_DOT_TOKEN = "<<<DOT>>>"

_DEFINITION_CUES = (
    "simple version", "plain language", "what that means", "means", "mean by",
    "is basically", "is just", "think of", "imagine", "in everyday terms",
)
_RECAP_CUES = (
    "remember", "takeaway", "three things", "big picture", "so if you remember",
    "to wrap", "as we wrap", "recap",
)
_CONTRAST_CUES = (
    "but", "however", "the catch", "tradeoff", "risk", "caveat", "on the other hand",
)
_TECH_CUES = (
    "matrix", "matrices", "algorithm", "model", "token", "embedding", "probability",
    "clinical", "statistical", "regulation", "mechanism", "causal", "evidence",
)


def split_spoken_phrases(text: str, max_chars: int | None = None) -> list[str]:
    """Split spoken text into stable phrase chunks without changing the words."""
    text = _normalize(text)
    if not text:
        return []
    max_chars = max_chars or config.PHRASE_MAX_CHARS
    phrases: list[str] = []
    for sentence in _sentence_chunks(text):
        colon_split = _split_setup_colon(sentence)
        if len(colon_split) > 1:
            phrases.extend(colon_split)
        elif len(sentence) <= max_chars:
            phrases.append(sentence)
        else:
            phrases.extend(_split_long_sentence(sentence, max_chars))
    return [p for p in phrases if p.strip()]


def plan_turn_delivery(turn: Turn, delivery_text: str, base_pace: float | None = None) -> TurnDelivery:
    """Build a phrase-level delivery plan for one already-final turn."""
    delivery_text = _normalize(delivery_text or turn.spoken or turn.text)
    base = _clamp_pace(base_pace if base_pace is not None else turn.pace)
    raw_phrases = split_spoken_phrases(delivery_text)
    if not raw_phrases and delivery_text:
        raw_phrases = [delivery_text]

    phrases: list[DeliveryPhrase] = []
    last_index = max(0, len(raw_phrases) - 1)
    for i, phrase in enumerate(raw_phrases):
        phrases.append(DeliveryPhrase(
            text=phrase,
            pace=_phrase_pace(turn, phrase, base),
            pause_after_ms=_phrase_pause_ms(turn, phrase, is_last=i == last_index),
        ))
    return TurnDelivery(
        turn_idx=turn.idx,
        speaker=turn.speaker,
        delivery_text=delivery_text,
        phrases=phrases,
    )


def _normalize(text: str) -> str:
    return " ".join(str(text or "").replace("\n", " ").split()).strip()


def _sentence_chunks(text: str) -> list[str]:
    protected, mapping = _protect_abbreviations(text)
    chunks = re.findall(r".+?(?:[.!?]+(?=\s|$)|$)", protected)
    restored = [_restore_abbreviations(chunk.strip(), mapping) for chunk in chunks]
    return [chunk for chunk in restored if chunk]


def _split_long_sentence(sentence: str, max_chars: int) -> list[str]:
    clause_parts = re.split(r"(?<=[,;:])\s+", sentence)
    chunks: list[str] = []
    current = ""
    for part in clause_parts:
        part = part.strip()
        if not part:
            continue
        candidate = f"{current} {part}".strip()
        if current and len(candidate) > max_chars:
            chunks.extend(_word_wrap(current, max_chars))
            current = part
        else:
            current = candidate
    if current:
        chunks.extend(_word_wrap(current, max_chars))
    return chunks


def _split_setup_colon(sentence: str) -> list[str]:
    if ":" not in sentence:
        return [sentence]
    before, after = sentence.split(":", 1)
    if not after.strip() or len(before) > 70:
        return [sentence]
    return [f"{before.strip()}:", after.strip()]


def _word_wrap(text: str, max_chars: int) -> list[str]:
    if len(text) <= max_chars:
        return [text]
    chunks: list[str] = []
    current: list[str] = []
    for word in text.split():
        candidate = " ".join([*current, word])
        if current and len(candidate) > max_chars:
            chunks.append(" ".join(current))
            current = [word]
        else:
            current.append(word)
    if current:
        chunks.append(" ".join(current))
    return chunks


def _protect_abbreviations(text: str) -> tuple[str, dict[str, str]]:
    mapping: dict[str, str] = {}
    protected = text
    for abbreviation in _ABBREVIATIONS:
        if abbreviation not in protected:
            continue
        protected = protected.replace(abbreviation, abbreviation.replace(".", _DOT_TOKEN))
    return protected, mapping


def _restore_abbreviations(text: str, mapping: dict[str, str]) -> str:
    restored = text.replace(_DOT_TOKEN, ".")
    for token, abbreviation in mapping.items():
        restored = restored.replace(token, abbreviation)
    return restored


def _phrase_pace(turn: Turn, phrase: str, base: float) -> float:
    lowered = phrase.lower()
    pace = base
    if _contains_any(lowered, _RECAP_CUES):
        pace -= 0.07
    if _contains_any(lowered, _DEFINITION_CUES):
        pace -= 0.06
    if turn.speaker == "expert" and (_is_dense(phrase) or _contains_any(lowered, _TECH_CUES)):
        pace -= 0.04
    if _contains_any(lowered, _CONTRAST_CUES):
        pace -= 0.03
    if turn.speaker == "host" and phrase.endswith("?"):
        pace += 0.03
    if turn.speaker == "host" and len(phrase) <= 34:
        pace += 0.04
    if _is_outro(turn):
        pace -= 0.04
    return _clamp_pace(pace)


def _phrase_pause_ms(turn: Turn, phrase: str, *, is_last: bool) -> int:
    lowered = phrase.lower()
    if is_last:
        return config.OUTRO_TURN_GAP_MS if _is_outro(turn) else _turn_gap_ms(turn)
    if phrase.endswith("?"):
        return config.PHRASE_PAUSE_MEDIUM_MS
    if phrase.endswith(":") or _contains_any(lowered, _DEFINITION_CUES):
        return config.PHRASE_PAUSE_LONG_MS
    if _contains_any(lowered, _RECAP_CUES) or _contains_any(lowered, _CONTRAST_CUES):
        return config.PHRASE_PAUSE_MEDIUM_MS + 80
    if len(phrase) <= 36:
        return config.PHRASE_PAUSE_SHORT_MS
    return config.PHRASE_PAUSE_MEDIUM_MS


def _turn_gap_ms(turn: Turn) -> int:
    return config.EXPERT_TURN_GAP_MS if turn.speaker == "expert" else config.HOST_TURN_GAP_MS


def _is_outro(turn: Turn) -> bool:
    move = (turn.move or "").lower()
    return "outro" in move or "closing" in move or "recap" in move


def _is_dense(phrase: str) -> bool:
    return len(phrase) >= 115 or phrase.count(",") >= 2


def _contains_any(text: str, cues: tuple[str, ...]) -> bool:
    return any(cue in text for cue in cues)


def _clamp_pace(pace: float | None) -> float:
    try:
        value = float(pace if pace is not None else config.TTS_PACE)
    except (TypeError, ValueError):
        value = config.TTS_PACE
    return round(max(0.9, min(1.15, value)), 2)
