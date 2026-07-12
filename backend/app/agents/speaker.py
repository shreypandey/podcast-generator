"""Speaker agents (Host / Expert): generate one in-character, grounded turn.

Short context window + tight per-turn contract = the small-model pattern
(SCRIPT_GENERATION.md §7.1)."""
from __future__ import annotations

from app import config
from app.adapters import sarvam_llm

ROLE_TEMP = {"host": 0.7, "expert": 0.5}

# M3 depth → how detailed the Expert gets (host stays general).
_DEPTH_HINTS = {
    1: "Keep it high-level and brief.",
    2: "Keep it fairly high-level.",
    3: "Balance the overview with a few specifics, but keep prerequisites clear.",
    4: "Go into specifics and mechanisms only after the prerequisite mental model is clear.",
    5: "Go deep — specifics, mechanisms, and nuance — without skipping prerequisite definitions.",
}

# Only the EXPERT holds the research. The HOST is a smart audience-proxy who reasons and
# pushes back but must not invent specific facts (SCRIPT_GENERATION.md §2).
_COMMON = (
    "Do not narrate stage directions or say your own name. Never OPEN a turn by attributing a "
    "topic to your co-host (\"you mentioned...\", \"you said...\", \"as you noted...\") — ask a "
    "forward question instead (\"what about...?\"). Genuine agreement reactions (\"you're "
    "right\") are fine. Refer to your co-host as \"you\"; never invent a name for them. "
    "Learning ladder rule: when a technical term is needed, say the plain idea first, then name "
    "the term; do not use dense terms as shortcuts before defining them. "
    'Respond with ONLY JSON: {{"text": "<your spoken turn>"}}.'
)

EXPERT_SYSTEM = (
    "You are {name}, {background}. You are the EXPERT on a two-host podcast — the one who holds "
    "the research. It is your turn. Perform this conversational move: {move}. Intent: {intent}. "
    "Speak ONE natural, spoken-style turn of 1-3 sentences, in character. You may reference "
    "ONLY the FACTS provided below — no outside knowledge. If no facts are given, speak "
    "generally without inventing specifics. Evidence snippets are private grounding context: "
    "do not quote them aloud, cite sources, or mention evidence labels. You EXPLAIN and ANSWER "
    "— do NOT pose the audience's curiosity/driving questions ('so how does X work?'); that is "
    "the HOST's job. A brief genuine clarifying question is fine occasionally, but never end "
    "your turn by handing the host's question back. {depth_hint} " + _COMMON
)

HOST_SYSTEM = (
    "You are {name}, {background}. You are the HOST on a two-host podcast — a sharp, curious "
    "generalist and the audience's proxy. You do NOT have the research notes. It is your turn. "
    "Perform this conversational move: {move}. Intent: {intent}. Speak ONE natural, spoken-style "
    "turn of 1-3 sentences. You may reason, ask incisive questions, react, connect points the "
    "expert has already made, and push back — but you must NOT introduce specific statistics, "
    "figures, dates, or study findings. Reference only what the expert has already said in the "
    "RECENT CONVERSATION, or broadly-known general knowledge. When you react to a number the "
    "expert gave, put its SIGNIFICANCE in your own words (e.g. \"that's a striking share\") — "
    "do not repeat the exact figure. If the discussion jumps to a dense term too early, ask the "
    "basic listener question before moving on. " + _COMMON
)


def generate(client, role: str, persona, beat, fact_texts: list[str], recent_turns, run,
             extra_instruction: str = "", depth: int = 3, settings=None) -> str:
    is_expert = role == "expert"
    intent = beat.intent or "advance the conversation"
    if is_expert:
        system = EXPERT_SYSTEM.format(name=persona.name, background=persona.background,
                                      move=beat.move, intent=intent,
                                      depth_hint=_DEPTH_HINTS.get(depth, ""))
    else:
        system = HOST_SYSTEM.format(name=persona.name, background=persona.background,
                                    move=beat.move, intent=intent)

    parts: list[str] = []
    if is_expert:  # only the expert sees the facts
        if fact_texts:
            parts.append(
                "FACTS YOU MAY USE (private evidence cards; do not read quotes aloud):"
            )
            parts += [f"  - {t}" for t in fact_texts]
        else:
            parts.append("FACTS YOU MAY USE: (none — speak generally, invent nothing)")
    if settings:
        parts += ["", "STYLE GUIDE:", config.style_brief(settings)]
    if recent_turns:
        parts += ["", "RECENT CONVERSATION:"]
        parts += [f"  {t.speaker.upper()}: {t.text}" for t in recent_turns]
    if extra_instruction:
        parts += ["", f"NOTE: {extra_instruction}"]
    user = "\n".join(parts) or "(start of the discussion)"

    data = sarvam_llm.complete_json(
        client, system, user, run, stage="dialogue", temperature=ROLE_TEMP.get(role, 0.6),
        fallback_text=True,
    )
    return str(data.get("text", "")).strip()


FRAMING_SYSTEM = (
    "You are {name}, {background}. You are the {role} on a two-host podcast. Speak ONE natural, "
    "warm, conversational turn (1-3 sentences) for this moment: {instruction}. This is show "
    "framing (an intro or outro), not a fact claim — you may greet listeners, name your "
    "co-host, and set up or wrap up the topic, but do NOT invent statistics or specific "
    "numbers. If you name your co-host, use exactly the name given in the instruction — never "
    'invent one. Respond with ONLY JSON: {{"text": "<your spoken turn>"}}.'
)


def framing_turn(client, role: str, persona, instruction: str, recent_turns, run, settings=None) -> str:
    """Intro/outro turns: greeting + framing, no fact-grounding constraint."""
    system = FRAMING_SYSTEM.format(name=persona.name, background=persona.background,
                                   role=role.upper(), instruction=instruction)
    parts: list[str] = []
    if settings:
        parts += ["STYLE GUIDE:", config.style_brief(settings), ""]
    if recent_turns:
        parts += ["RECENT CONVERSATION:"]
        parts += [f"  {t.speaker.upper()}: {t.text}" for t in recent_turns]
    user = "\n".join(parts) or "(this is the very start of the show)"
    data = sarvam_llm.complete_json(
        client, system, user, run, stage="framing", temperature=ROLE_TEMP.get(role, 0.6),
        fallback_text=True,
    )
    return str(data.get("text", "")).strip()
