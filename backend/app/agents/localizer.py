"""LLM localization agent: English canonical turn -> native spoken target-language turn.

This is used as an optional quality path for non-English renders. It is not a literal translator:
it rewrites one verified English podcast turn as natural target-language podcast speech while
preserving facts, names, numbers, and the speaker's role.
"""
from __future__ import annotations

import re

from app import config
from app.adapters import sarvam_llm
from app.artifacts import Cast, Turn


class LocalizationError(RuntimeError):
    """Raised when an LLM localization is missing or unsafe to render."""


_LANG_NAMES = {
    "hi-IN": "Hindi", "bn-IN": "Bengali", "gu-IN": "Gujarati", "kn-IN": "Kannada",
    "ml-IN": "Malayalam", "mr-IN": "Marathi", "od-IN": "Odia", "pa-IN": "Punjabi",
    "ta-IN": "Tamil", "te-IN": "Telugu", "en-IN": "English",
}
_SCRIPT_NAMES = {
    "hi-IN": "Devanagari", "bn-IN": "Bengali", "gu-IN": "Gujarati", "kn-IN": "Kannada",
    "ml-IN": "Malayalam", "mr-IN": "Devanagari", "od-IN": "Odia", "pa-IN": "Gurmukhi",
    "ta-IN": "Tamil", "te-IN": "Telugu", "en-IN": "Latin",
}
_COMMON_CODE_MIX_RE = re.compile(
    r"\b(excited|key|start|basics|simple|idea|cells?|blueprint|traditional|welcome)\b",
    re.IGNORECASE,
)
_ACRONYM_RE = re.compile(r"\b(COVID-19|COVID|mRNA|DNA|RNA|FDA|CDC|WHO)\b")
_ACRONYM_LOCALIZATIONS = {
    "hi-IN": {
        "COVID-19": "कोविड उन्नीस", "COVID": "कोविड", "mRNA": "एम-आर-एन-ए",
        "DNA": "डी-एन-ए", "RNA": "आर-एन-ए", "FDA": "एफ-डी-ए", "CDC": "सी-डी-सी",
        "WHO": "डब्ल्यू-एच-ओ",
    },
    "mr-IN": {
        "COVID-19": "कोविड एकोणीस", "COVID": "कोविड", "mRNA": "एम-आर-एन-ए",
        "DNA": "डी-एन-ए", "RNA": "आर-एन-ए", "FDA": "एफ-डी-ए", "CDC": "सी-डी-सी",
        "WHO": "डब्ल्यू-एच-ओ",
    },
}


SYSTEM = (
    "You are a senior podcast localization writer. Convert ONE English podcast turn into natural, "
    "publishable spoken {language}. This is localization, not literal translation. Preserve every "
    "fact, number, entity, causal relationship, uncertainty, and question/answer function. Do NOT "
    "add claims, extra greetings, summaries, citations, source references, or speaker labels. "
    "Use {script_name} script for ordinary words. Avoid code-mixing/Hinglish/Tanglish: do not "
    "leave common English words like 'excited', 'key', 'start', 'basics', 'simple', or 'idea' in "
    "the output when a natural {language} phrase exists. Keep person names recognizable; render "
    "titles like Dr. naturally for the language. Acronyms such as mRNA, DNA, RNA, FDA, CDC, WHO, "
    "and COVID may be written in the form a native speaker would say them, but do not invent an "
    "expansion. Avoid literal translations of English idioms; rewrite the idea naturally. Every "
    "sentence must be grammatically complete. For Hindi, write 'नमस्ते सबको' not 'Namaste sabko', "
    "'उत्साहित' or 'खुशी' not 'excited', 'मुख्य बात' not 'key', 'शुरू' not 'start', "
    "'कोशिकाएं' not 'सेल्स', and 'सही बात को भ्रम से अलग करना' rather than a literal "
    "'signal/noise' phrase. Make it sound like real podcast dialogue for a smart non-specialist "
    "listener. "
    'Respond with ONLY JSON: {{"spoken": "<localized spoken turn>", "pace": 1.0}}.'
)


def localize_turn(client, target: Turn, prior_turns: list[Turn], target_lang: str,
                  cast: Cast, run, settings=None) -> tuple[str, float]:
    """Localize one English turn. Raises LocalizationError when the result should not be used."""
    if target_lang == "en-IN":
        return target.spoken or target.text, target.pace

    language = _LANG_NAMES.get(target_lang, target_lang)
    script_name = _SCRIPT_NAMES.get(target_lang, "native")
    system = SYSTEM.format(language=language, script_name=script_name)
    user = _prompt(target, prior_turns, target_lang, language, cast, settings)
    data = sarvam_llm.complete_json(client, system, user, run, stage="localize", temperature=0.3)
    spoken = str(data.get("spoken", "")).strip()
    if _needs_repair(spoken):
        repair_user = (
            user
            + "\n\nThe previous output was rejected because it was romanized or code-mixed. "
            + f"Rewrite the SAME turn again in {script_name} script for ordinary words. "
            + "Do not use Latin transliteration. Do not add or remove facts.\n\n"
            + f"REJECTED OUTPUT:\n{spoken}"
        )
        data = sarvam_llm.complete_json(client, system, repair_user, run,
                                        stage="localize", temperature=0.2)
        spoken = str(data.get("spoken", "")).strip()
    spoken = _localize_acronyms(spoken, target_lang)
    if not spoken:
        raise LocalizationError("empty localization")
    if not _mostly_native(spoken):
        raise LocalizationError("localized output is not mostly native script")
    if _COMMON_CODE_MIX_RE.search(spoken):
        run.log(stage="localize", kind="code_mix_warning", target=target_lang,
                turn_idx=target.idx, text=spoken[:240])
    try:
        pace = float(data.get("pace", 1.0))
    except (TypeError, ValueError):
        pace = 1.0
    return spoken, max(0.9, min(1.15, pace))


def _prompt(target: Turn, prior_turns: list[Turn], target_lang: str, language: str,
            cast: Cast, settings=None) -> str:
    speaker = _persona_name(cast, target.speaker)
    other = _persona_name(cast, "expert" if target.speaker == "host" else "host")
    parts = [
        f"TARGET LANGUAGE: {language} ({target_lang})",
        f"SPEAKER: {target.speaker.upper()} - {speaker}",
        f"OTHER SPEAKER: {other}",
        f"TURN MOVE: {target.move or 'dialogue'}",
        "",
        "LOCALIZATION RULES:",
        "- Preserve the original turn's meaning and length band; do not add a new mini-explainer.",
        "- If the English line is a question, keep it as a question.",
        "- If the English line addresses the other speaker, keep the address natural.",
        "- Use the recent English context for continuity of address, register, terminology, and flow.",
        "- Avoid literal English podcast phrasing when a native podcast phrasing is better.",
        "- Avoid English filler/common words; use natural target-language equivalents.",
        "- Do not include markdown, citations, source names, or speaker labels.",
    ]
    if settings:
        parts += ["", "STYLE GUIDE:", config.style_brief(settings)]
    if prior_turns:
        parts += ["", "RECENT ENGLISH CONTEXT:"]
        parts += [f"{turn.speaker.upper()}: {turn.text}" for turn in prior_turns[-2:]]
    parts += ["", "FINAL ENGLISH TURN TO LOCALIZE:", target.text]
    return "\n".join(parts)


def _persona_name(cast: Cast, speaker: str) -> str:
    persona = cast.expert if speaker == "expert" else cast.host
    return persona.name


def _mostly_native(text: str) -> bool:
    letters = [ch for ch in text if ch.isalpha()]
    if len(letters) < 12:
        return True
    return sum(1 for ch in letters if ord(ch) > 127) / len(letters) >= 0.5


def _needs_repair(text: str) -> bool:
    return bool(text and (not _mostly_native(text) or _COMMON_CODE_MIX_RE.search(text)))


def _localize_acronyms(text: str, target_lang: str) -> str:
    mapping = _ACRONYM_LOCALIZATIONS.get(target_lang)
    if not mapping:
        return text
    return _ACRONYM_RE.sub(lambda match: mapping.get(match.group(0), match.group(0)), text)
