"""Humanizer agent: rewrite a verified turn as natural SPOKEN delivery (Levers A + B) and pick a
delivery pace (Lever C). Delivery-only — never changes facts/numbers/names. Runs AFTER verify +
editor, so the canonical Turn.text (which citations reference) is untouched (SCRIPT_GENERATION.md
§9). For M4 it moves into the per-language render, after translate.

Acronyms are protected deterministically (the small model mangles them, e.g. mRNA -> 'em-en-ary'):
we swap them for opaque placeholders before the call and restore the correct spoken form after."""
from __future__ import annotations

import re

from app import config
from app.adapters import sarvam_llm

# acronym (as written) -> how it should be SPOKEN. Letter-acronyms keep their letters (Bulbul
# spells them acceptably); word-acronyms are re-cased so they're said as a word.
_ACRONYMS = {
    "COVID-19": "Covid nineteen", "COVID": "Covid", "NASA": "Nasa",
    "mRNA": "mRNA", "DNA": "DNA", "RNA": "RNA", "FDA": "FDA", "CDC": "CDC", "WHO": "WHO",
}
_ACR_RE = re.compile(
    r"\b(" + "|".join(re.escape(k) for k in sorted(_ACRONYMS, key=len, reverse=True)) + r")\b"
)


def _protect(text: str) -> tuple[str, dict[str, str]]:
    mapping: dict[str, str] = {}

    def repl(m: re.Match) -> str:
        token = f"ACRTKN{len(mapping)}"
        mapping[token] = _ACRONYMS[m.group(0)]
        return token

    return _ACR_RE.sub(repl, text), mapping


def _restore(text: str, mapping: dict[str, str]) -> str:
    for token, spoken in mapping.items():
        text = text.replace(token, spoken)
    return text


SYSTEM = (
    "You are a voice/delivery editor for a podcast. Given the last few turns for context, rewrite "
    "ONLY THE FINAL turn so it sounds like natural SPOKEN speech, not written text. Rules: "
    "(a) write numbers, units, currencies and symbols the way they'd be SPOKEN (e.g. 'US$0.50/m3' "
    "-> 'fifty cents per cubic meter'; '0.83' -> 'zero point eight three'); "
    "(b) use natural spoken punctuation for pauses (commas, ellipses, em-dashes); "
    "(c) add AT MOST one or two light, context-appropriate disfluencies or discourse markers "
    "('so', 'right', 'you know', an occasional 'um') — only where natural, do NOT overdo it. "
    "Keep any placeholder token that looks like ACRTKN followed by digits EXACTLY as it appears — "
    "do not translate, spell out, or remove it. Do NOT change any facts, numeric values, or "
    f"names — only HOW they are said. Also choose a delivery pace from {config.PACE_MIN} "
    f"(measured / emphatic) to {config.PACE_MAX} (quick / excited). "
    'Respond with ONLY JSON: {"spoken": "<spoken final turn>", "pace": 1.0}.'
)


def humanize_turn(client, window_turns, run, settings=None) -> tuple[str, float]:
    """window_turns = up to 3 clean turns; rewrite ONLY the last. Degrades to clean text."""
    target = window_turns[-1]
    prior = window_turns[:-1]
    protected, mapping = _protect(target.text)  # shield acronyms from the model

    parts: list[str] = []
    if prior:
        parts.append("CONTEXT (earlier turns):")
        parts += [f"  {t.speaker.upper()}: {t.text}" for t in prior]
        parts.append("")
    if settings:
        parts.append("STYLE GUIDE:")
        parts.append(config.style_brief(settings))
        parts.append("")
    parts.append(f"FINAL TURN TO REWRITE — {target.speaker.upper()}: {protected}")
    user = "\n".join(parts)

    try:
        data = sarvam_llm.complete_json(client, SYSTEM, user, run, stage="humanize", temperature=0.6)
        spoken = _restore(str(data.get("spoken", "")).strip() or protected, mapping)
        try:
            pace = float(data.get("pace", 1.0))
        except (TypeError, ValueError):
            pace = 1.0
        return spoken, _clamp_pace(pace)
    except Exception as e:  # noqa: BLE001 - delivery is best-effort; never worse than clean text
        run.log(stage="humanize", kind="fallback", error=str(e)[:150])
        return target.text, 1.0


# --- M4.1: per-language humanizer (runs in render, AFTER translate) ----------
_LANG_NAMES = {
    "hi-IN": "Hindi", "bn-IN": "Bengali", "gu-IN": "Gujarati", "kn-IN": "Kannada",
    "ml-IN": "Malayalam", "mr-IN": "Marathi", "od-IN": "Odia", "pa-IN": "Punjabi",
    "ta-IN": "Tamil", "te-IN": "Telugu", "en-IN": "English",
}


def _mostly_native(text: str) -> bool:
    """True if most alphabetic chars are non-ASCII (i.e. native Indic script, not romanized)."""
    letters = [ch for ch in text if ch.isalpha()]
    if not letters:
        return True
    return sum(1 for ch in letters if ord(ch) > 127) / len(letters) >= 0.5


def humanize_lang(client, text: str, lang: str, run, settings=None) -> tuple[str, float]:
    """Add natural spoken disfluencies to already-translated text, IN that language.
    Delivery-only (don't change facts/numbers/names). Degrades to the input text; guards against
    the model romanizing the script (Bulbul needs native script)."""
    text = (text or "").strip()
    if not text:
        return text, 1.0
    language = _LANG_NAMES.get(lang, lang)
    system = (
        f"You are a voice/delivery editor for a {language} podcast. Rewrite the given {language} "
        f"text so it sounds like natural SPOKEN {language}: add AT MOST one or two light, natural "
        f"filler / discourse words appropriate to {language} (e.g. in Hindi 'matlab', 'toh', "
        "'haan'), and natural spoken pauses (commas, ellipses, em-dashes). Do NOT change any "
        f"facts, numbers, or names — only how it is said. Keep the output ENTIRELY in the native "
        f"{language} script — do NOT romanize or use Latin letters. Also choose a delivery pace "
        f"from {config.PACE_MIN} (measured) to {config.PACE_MAX} (quick). "
        + (f"STYLE GUIDE:\n{config.style_brief(settings)} " if settings else "")
        + 'Respond with ONLY JSON: {"spoken": "...", "pace": 1.0}.'
    )
    try:
        data = sarvam_llm.complete_json(client, system, text, run, stage="humanize_lang", temperature=0.6)
        spoken = str(data.get("spoken", "")).strip()
        # Guard: reject a romanized rewrite of a native-script input → keep the plain translation.
        if not spoken or (_mostly_native(text) and not _mostly_native(spoken)):
            run.log(stage="humanize_lang", kind="script_fallback", lang=lang)
            return text, 1.0
        try:
            pace = float(data.get("pace", 1.0))
        except (TypeError, ValueError):
            pace = 1.0
        return spoken, _clamp_pace(pace)
    except Exception as e:  # noqa: BLE001 - never worse than the plain translation
        run.log(stage="humanize_lang", kind="fallback", error=str(e)[:150])
        return text, 1.0


def _clamp_pace(pace: float) -> float:
    return max(config.PACE_MIN, min(config.PACE_MAX, pace))
