"""Central config: env, model ids, voice mapping, client factories."""
import math
import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()

EXA_API_KEY = os.getenv("EXA_API_KEY")
SARVAM_API_KEY = os.getenv("SARVAM_API_KEY")

APP_DIR = os.path.dirname(os.path.dirname(__file__))
RUNS_DIR = os.getenv("RUNS_DIR", os.path.join(APP_DIR, "runs"))
DATABASE_PATH = os.getenv("DATABASE_PATH", os.path.join(APP_DIR, "data", "app.db"))
FRONTEND_DIST_DIR = os.getenv(
    "FRONTEND_DIST_DIR",
    os.path.abspath(os.path.join(APP_DIR, "..", "frontend", "dist")),
)

# Models (see progress.md decision log)
LLM_MODEL = "sarvam-105b"
TTS_MODEL = "bulbul:v3"

# M0 is English-only; Host/Expert get distinct v3 voices.
LANGUAGE = "en-IN"
# Voice pools by gender (bulbul:v3). Casting picks a gender per persona → we map to a voice
# so the voice matches the character's name/gender (no "Alex" with a female voice).
FEMALE_VOICES = ["priya", "ritu", "neha"]
MALE_VOICES = ["aditya", "shubh"]  # NOTE: "rahul" excluded — poor quality (user)
TTS_PACE = 1.0          # default/fallback pace; humanizer sets per-turn pace (0.9..1.15)
TTS_GAP_SECONDS = 0.2   # silence between turns in assembly (tightened from 0.4 for naturalness)

# M4 render — Mayura translate (covers the 11 Bulbul languages; modern-colloquial + spoken form,
# 1000-char/request limit). sarvam-translate:v1 is formal-only, so Mayura is the better fit.
TRANSLATE_MODEL = "mayura:v1"
TRANSLATE_MODE = "modern-colloquial"
TRANSLATE_SCRIPT = "spoken-form-in-native"
RENDER_MAX_WORKERS = 4  # M4.1: parallel per-turn translate+TTS within a language
SUPPORTED_LANGUAGES = {
    "en-IN", "hi-IN", "bn-IN", "ta-IN", "te-IN", "mr-IN",
    "gu-IN", "kn-IN", "ml-IN", "pa-IN", "od-IN",
}

# Grounding: map-reduce over chunks. Each request must stay under the Sarvam gateway's
# request-size limit (a full page can be >100K chars → 403). 8K/chunk is safely under
# the observed working size (~27K). Chunks/source is bounded so huge pages don't explode cost.
GROUND_CHUNK_CHARS = 8000
MAX_CHUNKS_PER_SOURCE = 3
GROUND_MAX_WORKERS = 3
# Non-steerable loop constants
CONTEXT_WINDOW_TURNS = 4
VERIFY_MAX_REPAIRS = 1  # M2a: bounded repair attempts per unsupported expert turn
MAX_CHALLENGES = 2      # M2b: tension budget — rations evidence-driven challenges per episode
MAX_SEGMENT_REVISIONS = 2  # M3 editor: max turns the review_segment editor revises per segment

ANGLE_PRESETS = {
    "balanced": "Give a balanced overview: what it is, how it works, why it matters, and the key caveats.",
    "mechanism": "Emphasize how it works: mechanisms, causal steps, systems, and concrete process explanations.",
    "current": "Emphasize what is current: recent updates, current status, and what changed recently.",
    "controversy": "Emphasize contested points, caveats, tradeoffs, and what evidence does or does not settle.",
    "practical": "Emphasize practical implications, real-world use, decisions, and what listeners can take away.",
    "mythbusting": "Emphasize misconceptions, common false beliefs, and evidence-backed corrections.",
    "beginner": "Emphasize a beginner-friendly path: plain language, basics first, then careful specifics.",
}
TONE_PRESETS = {
    "conversational": "Natural, warm, and clear, like a smart podcast conversation.",
    "serious": "Measured, precise, and sober; avoid hype and jokes.",
    "energetic": "Lively and high-momentum without sounding breathless or promotional.",
    "calm": "Relaxed, steady, and reassuring; keep the pace unhurried.",
    "investigative": "Curious, probing, and evidence-seeking; ask what the facts really show.",
}
STYLE_PRESETS = {
    "curious_expert": "A curious host and a domain expert unpack the topic as intelligent peers.",
    "debate": "More explicit pushback and tradeoff-testing, while never manufacturing conflict.",
    "storytelling": "Use a narrative arc, concrete examples, and vivid but grounded transitions.",
    "classroom": "Teach clearly with layered explanation and quick checks for understanding.",
    "news_analysis": "Frame it like analysis of a current issue: context, stakes, evidence, implications.",
}
CUSTOM_STEERING_CHARS = 240
MAX_FOCUS_QUESTIONS = 5
MAX_FOCUS_CHARS = 160


# M3 deep steering: per-run budgets resolved from the Brief (length + depth).
@dataclass
class Settings:
    num_queries: int
    max_grounding_sources: int
    num_sources: int  # compatibility alias for max_grounding_sources
    max_facts: int
    max_segments: int
    max_turns_per_segment: int
    max_total_turns: int
    depth: int
    angle: str
    focus_questions: list[str]
    custom_angle: str
    tone: str
    style: str
    custom_style: str

_LENGTH_TURNS = {"short": 6, "medium": 10, "long": 16}
_DEPTH_QUERIES = {1: 2, 2: 3, 3: 4, 4: 5, 5: 5}
_DEPTH_GROUNDING_SOURCES = {1: 3, 2: 4, 3: 6, 4: 7, 5: 8}
_DEPTH_FACTS = {1: 6, 2: 9, 3: 12, 4: 16, 5: 20}


def _clean_text(value: str, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit].strip()


def _normalize_choice(value: str, allowed: dict[str, str], default: str) -> str:
    key = str(value or "").strip().lower().replace("-", "_")
    aliases = {"myth_busting": "mythbusting"}
    key = aliases.get(key, key)
    return key if key in allowed else default


def normalize_focus_questions(values) -> list[str]:
    if isinstance(values, str):
        raw = [values]
    elif isinstance(values, list):
        raw = values
    else:
        raw = []
    questions: list[str] = []
    for value in raw:
        text = _clean_text(str(value), MAX_FOCUS_CHARS)
        if text and text not in questions:
            questions.append(text)
        if len(questions) >= MAX_FOCUS_QUESTIONS:
            break
    return questions


def angle_brief(settings: Settings) -> str:
    angle = _normalize_choice(getattr(settings, "angle", "balanced"), ANGLE_PRESETS, "balanced")
    focus_questions = normalize_focus_questions(getattr(settings, "focus_questions", []))
    custom_angle = _clean_text(getattr(settings, "custom_angle", ""), CUSTOM_STEERING_CHARS)
    lines = [f"ANGLE: {angle} - {ANGLE_PRESETS[angle]}"]
    if focus_questions:
        lines.append("FOCUS QUESTIONS:")
        lines += [f"- {q}" for q in focus_questions]
    if custom_angle:
        lines.append(f"CUSTOM ANGLE: {custom_angle}")
    return "\n".join(lines)


def style_brief(settings: Settings) -> str:
    tone = _normalize_choice(getattr(settings, "tone", "conversational"), TONE_PRESETS, "conversational")
    style = _normalize_choice(getattr(settings, "style", "curious_expert"), STYLE_PRESETS, "curious_expert")
    custom_style = _clean_text(getattr(settings, "custom_style", ""), CUSTOM_STEERING_CHARS)
    lines = [
        f"TONE: {tone} - {TONE_PRESETS[tone]}",
        f"STYLE: {style} - {STYLE_PRESETS[style]}",
    ]
    if custom_style:
        lines.append(f"CUSTOM STYLE: {custom_style}")
    lines.append("Grounding, role boundaries, and citations override style guidance.")
    return "\n".join(lines)


def normalize_steering(*, angle: str = "balanced", focus_questions=None,
                       custom_angle: str = "", tone: str = "conversational",
                       style: str = "curious_expert", custom_style: str = "") -> dict:
    return {
        "angle": _normalize_choice(angle, ANGLE_PRESETS, "balanced"),
        "focus_questions": normalize_focus_questions(focus_questions or []),
        "custom_angle": _clean_text(custom_angle, CUSTOM_STEERING_CHARS),
        "tone": _normalize_choice(tone, TONE_PRESETS, "conversational"),
        "style": _normalize_choice(style, STYLE_PRESETS, "curious_expert"),
        "custom_style": _clean_text(custom_style, CUSTOM_STEERING_CHARS),
    }


def resolve_settings(brief) -> Settings:
    depth = min(5, max(1, int(getattr(brief, "depth", 3) or 3)))
    total = _LENGTH_TURNS.get(getattr(brief, "length", "medium") or "medium", 10)
    max_segments = 2 if total <= 6 else (3 if total <= 10 else 4)
    max_grounding_sources = _DEPTH_GROUNDING_SOURCES[depth]
    steering = normalize_steering(
        angle=getattr(brief, "angle", "balanced"),
        focus_questions=getattr(brief, "focus_questions", []),
        custom_angle=getattr(brief, "custom_angle", ""),
        tone=getattr(brief, "tone", "conversational"),
        style=getattr(brief, "style", "curious_expert"),
        custom_style=getattr(brief, "custom_style", ""),
    )
    return Settings(
        num_queries=_DEPTH_QUERIES[depth],
        max_grounding_sources=max_grounding_sources,
        num_sources=max_grounding_sources,
        max_facts=_DEPTH_FACTS[depth],
        max_segments=max_segments,
        max_turns_per_segment=max(2, math.ceil(total / max_segments)),
        max_total_turns=total,
        depth=depth,
        angle=steering["angle"],
        focus_questions=steering["focus_questions"],
        custom_angle=steering["custom_angle"],
        tone=steering["tone"],
        style=steering["style"],
        custom_style=steering["custom_style"],
    )


def require_keys() -> None:
    missing = [k for k, v in {"EXA_API_KEY": EXA_API_KEY, "SARVAM_API_KEY": SARVAM_API_KEY}.items() if not v]
    if missing:
        raise SystemExit(
            f"Missing env vars: {', '.join(missing)}. Add them to backend/.env (see .env.example)."
        )


def sarvam_client():
    from sarvamai import SarvamAI

    # Generous timeout — reasoning calls can take 25s+; short default timeouts read-timeout.
    return SarvamAI(api_subscription_key=SARVAM_API_KEY, timeout=120)


def exa_client():
    from exa_py import Exa

    return Exa(api_key=EXA_API_KEY)
