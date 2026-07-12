"""Director agent: casting (topic-derived personas), outline planning, and per-turn
beat decisions. All role-conditioned JSON calls (SCRIPT_GENERATION.md §1, §6, §7)."""
from __future__ import annotations

import concurrent.futures
import math
from dataclasses import dataclass

from app import config
from app.adapters import sarvam_llm
from app.artifacts import Cast, FactSheet, Outline, Persona, Segment

MOVES = ["ask", "explain", "illustrate", "react", "connect", "advance", "transition", "challenge"]
_OUTLINE_FACT_CAP = 6
_FACT_TYPE_PRIORITY = {
    "mechanism": 0,
    "finding": 1,
    "stat": 2,
    "example": 3,
    "misconception": 4,
    "caveat": 5,
    "counterclaim": 6,
    "background": 7,
}
_ANGLE_FACT_TYPE_PRIORITY = {
    "balanced": _FACT_TYPE_PRIORITY,
    "mechanism": {
        "mechanism": 0, "example": 1, "finding": 2, "stat": 3,
        "misconception": 4, "caveat": 5, "counterclaim": 6, "background": 7,
    },
    "current": {
        "finding": 0, "stat": 1, "mechanism": 2, "example": 3,
        "caveat": 4, "counterclaim": 5, "misconception": 6, "background": 7,
    },
    "controversy": {
        "caveat": 0, "counterclaim": 1, "finding": 2, "stat": 3,
        "mechanism": 4, "misconception": 5, "example": 6, "background": 7,
    },
    "practical": {
        "example": 0, "finding": 1, "mechanism": 2, "stat": 3,
        "caveat": 4, "misconception": 5, "counterclaim": 6, "background": 7,
    },
    "mythbusting": {
        "misconception": 0, "mechanism": 1, "caveat": 2, "finding": 3,
        "stat": 4, "example": 5, "counterclaim": 6, "background": 7,
    },
    "beginner": {
        "mechanism": 0, "example": 1, "misconception": 2, "finding": 3,
        "stat": 4, "caveat": 5, "counterclaim": 6, "background": 7,
    },
}


def _topic_and_facts(topic: str, factsheet: FactSheet) -> str:
    lines = [f"TOPIC: {topic}", "", "FACTS:"]
    for f in factsheet.facts:
        lines.append(f"  {f.id}: {f.claim}")
    return "\n".join(lines)


def _fact_id_num(fid: str) -> int:
    try:
        return int(str(fid).lstrip("F"))
    except ValueError:
        return 9999


def _is_tension_fact(f) -> bool:
    return (
        getattr(f, "fact_type", "") in ("caveat", "counterclaim")
        or getattr(f, "story_role", "") == "challenge"
        or getattr(f, "evidence_strength", "") == "weak"
        or bool(getattr(f, "conflicts_with", []))
        or bool(getattr(f, "caveats", []))
        or getattr(f, "tension_type", "none") not in ("", "none")
    )


def _type_priority(f, settings=None) -> int:
    angle = getattr(settings, "angle", "balanced") if settings else "balanced"
    priority = _ANGLE_FACT_TYPE_PRIORITY.get(angle, _FACT_TYPE_PRIORITY)
    return priority.get(getattr(f, "fact_type", "background"), 9)


def _fact_priority(f, settings=None) -> tuple:
    return (
        _type_priority(f, settings),
        -float(getattr(f, "quality_score", 0.0)),
        _fact_id_num(getattr(f, "id", "")),
    )


def _tension_priority(f, settings=None) -> tuple:
    return (
        -float(getattr(f, "quality_score", 0.0)),
        _type_priority(f, settings),
        _fact_id_num(getattr(f, "id", "")),
    )


def _repair_outline_coverage(outline: Outline, factsheet: FactSheet, settings) -> Outline:
    """Deterministically ensure the outline exposes the strongest facts to the turn loop."""
    fact_by_id = {f.id: f for f in factsheet.facts}
    if not outline.segments or not fact_by_id:
        return outline

    segs = outline.segments[:settings.max_segments]
    cap = max(3, min(_OUTLINE_FACT_CAP, math.ceil(len(fact_by_id) / max(1, len(segs))) + 1))

    for seg in segs:
        cleaned = []
        for fid in seg.fact_ids:
            if fid in fact_by_id and fid not in cleaned:
                cleaned.append(fid)
        cleaned.sort(key=lambda fid: _fact_priority(fact_by_id[fid], settings))
        seg.fact_ids = cleaned[:cap]

    def assigned_ids() -> set[str]:
        return {fid for seg in segs for fid in seg.fact_ids}

    for fact in sorted(factsheet.facts, key=lambda f: _fact_priority(f, settings)):
        if fact.id in assigned_ids():
            continue
        target = min(segs, key=lambda seg: (len(seg.fact_ids), seg.id))
        if len(target.fact_ids) < cap:
            target.fact_ids.append(fact.id)
            target.fact_ids.sort(key=lambda fid: _fact_priority(fact_by_id[fid], settings))
            continue

        weakest = max(target.fact_ids, key=lambda fid: _fact_priority(fact_by_id[fid], settings))
        if _fact_priority(fact, settings) < _fact_priority(fact_by_id[weakest], settings):
            target.fact_ids.remove(weakest)
            target.fact_ids.append(fact.id)
            target.fact_ids.sort(key=lambda fid: _fact_priority(fact_by_id[fid], settings))

    tension_facts = sorted((f for f in factsheet.facts if _is_tension_fact(f)),
                           key=lambda f: _tension_priority(f, settings))
    has_tension = any(_is_tension_fact(fact_by_id[fid]) for fid in assigned_ids())
    if tension_facts and not has_tension:
        tension = tension_facts[0]
        target = min(segs, key=lambda seg: (len(seg.fact_ids), seg.id))
        if len(target.fact_ids) >= cap:
            weakest_non_tension = [
                fid for fid in sorted(
                    target.fact_ids,
                    key=lambda fid: _fact_priority(fact_by_id[fid], settings),
                    reverse=True,
                )
                if not _is_tension_fact(fact_by_id[fid])
            ]
            if weakest_non_tension:
                target.fact_ids.remove(weakest_non_tension[0])
        if len(target.fact_ids) < cap and tension.id not in target.fact_ids:
            target.fact_ids.append(tension.id)
            target.fact_ids.sort(key=lambda fid: _fact_priority(fact_by_id[fid], settings))

    outline.segments = segs
    return outline


# --- Casting -----------------------------------------------------------------
CAST_SYSTEM = (
    "You are the director of a two-host podcast. Given the TOPIC and FACTS, design two "
    "complementary co-hosts: a HOST (a sharp, curious generalist who asks incisive questions "
    "and brings their own knowledge) and an EXPERT (a deep domain specialist who explains with "
    "depth). Both are intelligent peers, not a novice and a teacher. Tailor their names and a "
    "one-line background to this topic, and give each a gender that matches the name "
    "(\"male\" or \"female\"). Respond with ONLY JSON: "
    '{"host": {"name": "...", "gender": "male|female", "background": "..."}, '
    '"expert": {"name": "...", "gender": "male|female", "background": "..."}}.'
)


def _norm_gender(value: str) -> str:
    return "female" if str(value).strip().lower().startswith("f") else "male"


def _assign_voices(host_gender: str, expert_gender: str) -> tuple[str, str]:
    pools = {"female": config.FEMALE_VOICES, "male": config.MALE_VOICES}
    host_voice = pools[host_gender][0]
    if host_gender == expert_gender:  # same gender → keep the two voices distinct
        pool = pools[expert_gender]
        expert_voice = pool[1] if len(pool) > 1 else pool[0]
    else:
        expert_voice = pools[expert_gender][0]
    return host_voice, expert_voice


def cast(client, topic: str, factsheet: FactSheet, run) -> Cast:
    data = sarvam_llm.complete_json(
        client, CAST_SYSTEM, _topic_and_facts(topic, factsheet), run, stage="cast", temperature=0.5
    )
    h, e = data["host"], data["expert"]
    hg, eg = _norm_gender(h.get("gender")), _norm_gender(e.get("gender"))
    host_voice, expert_voice = _assign_voices(hg, eg)
    return Cast(
        host=Persona(role="host", name=str(h["name"]).strip(), gender=hg,
                     background=str(h["background"]).strip(), voice=host_voice),
        expert=Persona(role="expert", name=str(e["name"]).strip(), gender=eg,
                       background=str(e["background"]).strip(), voice=expert_voice),
    )


# --- Outline -----------------------------------------------------------------
def _outline_system(settings) -> str:
    steering = config.angle_brief(settings)
    return (
        f"You are the director planning a podcast (~{settings.max_total_turns} turns total, "
        f"depth {settings.depth}/5). Given the TOPIC and FACTS, produce an ordered outline of at "
        f"most {settings.max_segments} segments that tells a coherent story: open with the "
        "big-picture framing and why it matters, then build into the specifics and evidence, "
        "then close. Don't lead with raw statistics. Each segment has a goal and lists the fact "
        "ids it should cover. Follow the STEERING block for emphasis, but never invent facts or "
        "ignore strong evidence. Also give a one-line opening hook and a closing.\n\n"
        f"STEERING:\n{steering}\n\nRespond with ONLY "
        'JSON: {"opening_hook": "...", "closing": "...", '
        '"segments": [{"goal": "...", "fact_ids": ["F1", "F2"]}]}.'
    )


def plan_outline(client, topic: str, factsheet: FactSheet, settings, run) -> Outline:
    data = sarvam_llm.complete_json(
        client, _outline_system(settings), _topic_and_facts(topic, factsheet), run,
        stage="plan", temperature=0.3
    )
    segs: list[Segment] = []
    for i, s in enumerate((data.get("segments") or [])[:settings.max_segments], start=1):
        segs.append(Segment(
            id=f"SEG{i}",
            goal=str(s.get("goal", "")).strip(),
            fact_ids=[str(x).strip() for x in (s.get("fact_ids") or [])],
        ))
    if not segs:  # fallback: one segment covering everything
        segs = [Segment(id="SEG1", goal=topic, fact_ids=[f.id for f in factsheet.facts])]
    outline = Outline(
        opening_hook=str(data.get("opening_hook", "")).strip(),
        closing=str(data.get("closing", "")).strip(),
        segments=segs,
    )
    return _repair_outline_coverage(outline, factsheet, settings)


# --- Per-turn beat -----------------------------------------------------------
@dataclass
class Beat:
    speaker: str
    move: str
    fact_focus: list[str]
    intent: str
    segment_status: str


BEAT_SYSTEM = (
    "You are the director conducting a live two-host podcast. Decide the NEXT single turn.\n"
    f"Choose: speaker (host or expert); a move from {MOVES}; the fact ids to focus on (only "
    "from those offered this segment, [] for a pure question/reaction); a one-line intent for "
    "the speaker; and whether this closes the segment.\n"
    "FACT LABELS: facts may be labeled like [mechanism/explain], [example/illustrate], "
    "[caveat/challenge], or [counterclaim/challenge]. Use mechanism/finding/stat facts for clear "
    "explanations, example facts for illustrations, and caveat/counterclaim facts for earned "
    "challenges. Prefer unused high-score facts, cover caveats/challenges when available, and "
    "avoid repeatedly using the same mechanism fact unless continuity requires it. Avoid "
    "overusing background facts when more substantive labeled facts are available.\n"
    "ROLES: specific facts and statistics belong to the EXPERT. The HOST is a smart generalist "
    "who reasons, reacts, connects, and pushes back — never states new specific facts (use "
    "fact_focus [] for host turns). For an EXPERT 'explain' or 'illustrate' turn you MUST "
    "assign at least one fact_focus id (the expert may only state specifics that are in the "
    "facts).\n"
    "CHALLENGE: use the 'challenge' move ONLY when the focused fact is tagged TENSION (weak "
    "evidence, a caveat, or conflicts with another fact) AND the CHALLENGE BUDGET is > 0. Then "
    "pick who challenges: the HOST to voice the listener's skeptical doubt (fact_focus []), or "
    "the EXPERT to honestly surface the caveat/conflict (fact_focus = the tagged fact plus any "
    "fact it conflicts with). Never manufacture disagreement where the facts don't conflict.\n"
    "COHERENCE: the intent you write must make the turn ANSWER or FOLLOW FROM the previous turn "
    "— never ignore the question just asked. If the assigned fact names a specific entity or "
    "example not yet mentioned (a disease, product, study, place), write the intent so the "
    "speaker INTRODUCES it with a bridge from what is already established — do not drop it as if "
    "it were already the subject.\n"
    "MAKE IT LIVELY — do NOT just alternate host-ask then expert-explain. Vary it: the host "
    "reacts (react), draws a connection (connect), or pushes back with reasoning (challenge, "
    "e.g. 'but wouldn't that mean...?'); the expert illustrates with an example (illustrate) or "
    "builds on the host's point, and MAY take two turns in a row to develop an idea. Avoid "
    "repeating the previous move; prefer facts not yet used.\n"
    "STEERING: if the view includes angle/focus or style guidance, use it to choose emphasis and "
    "wording, but grounding and role rules still override it.\n"
    "Examples of good next beats:\n"
    '  {"speaker":"host","move":"react","fact_focus":[],"intent":"react with surprise to the '
    'scale, then wonder aloud what makes it possible","segment_status":"continue"}\n'
    '  {"speaker":"expert","move":"illustrate","fact_focus":["F3"],"intent":"give a concrete '
    'example that makes F3 tangible","segment_status":"continue"}\n'
    '  {"speaker":"host","move":"challenge","fact_focus":[],"intent":"gently push back — '
    'doesn\'t that tradeoff undercut the benefit?","segment_status":"continue"}\n'
    "Respond with ONLY JSON: "
    '{"speaker": "host|expert", "move": "...", "fact_focus": ["F1"], "intent": "...", '
    '"segment_status": "continue|close"}.'
)


def next_beat(client, view: str, run, extra: str = "") -> Beat:
    user = f"{view}\n\n{extra}" if extra else view
    data = sarvam_llm.complete_json(client, BEAT_SYSTEM, user, run, stage="dialogue", temperature=0.5)
    speaker = str(data.get("speaker", "host")).lower().strip()
    if speaker not in ("host", "expert"):
        speaker = "host"
    status = str(data.get("segment_status", "continue")).lower().strip()
    return Beat(
        speaker=speaker,
        move=str(data.get("move", "explain")).lower().strip(),
        fact_focus=[str(x).strip() for x in (data.get("fact_focus") or []) if str(x).strip()],
        intent=str(data.get("intent", "")).strip(),
        segment_status="close" if status == "close" else "continue",
    )


# --- M3 editor: per-segment reviewer PANEL (parallel focused subagents) -------
# One narrow objective per reviewer beats one omnibus check (small-model recall). All share a
# stable prefix and swap only the objective at the end (caching-ready if Sarvam adds it).
_REVIEW_RUBRIC = (
    "You are one focused editor on a panel reviewing a SEGMENT of a two-host podcast. Consider "
    "the TOPIC and the CONVERSATION SO FAR, then apply ONLY your assigned CHECK to the SEGMENT "
    "turns. Flag ONLY genuine defects — if none, return an empty list. For each flagged turn "
    "give its 0-based index within the segment, the issue, and a one-line fix hint. Respond "
    'with ONLY JSON: {"flags": [{"idx": 0, "issue": "...", "hint": "..."}]}.'
)

_REVIEWERS = (
    {"name": "continuity", "severity": "hard", "objective":
     "CONTINUITY — flag a turn that is a NON-SEQUITUR (does not answer or follow from the "
     "previous turn), or that introduces a specific subject, entity, or example (a disease, "
     "product, study, place, etc.) as if already established when it was NOT mentioned earlier "
     "in the conversation."},
    {"name": "consistency", "severity": "hard", "objective":
     "CONSISTENCY — flag PERSONA BLEED (the host stating specific researched facts/numbers, or "
     "the EXPERT posing a curiosity/driving question that the host should ask — e.g. ending a "
     "turn with 'so how does X work?' instead of explaining/answering), REPETITION of a "
     "point/fact already made, or a fabricated back-reference (\"you mentioned...\" for "
     "something never said)."},
    {"name": "liveliness", "severity": "soft", "objective":
     "LIVELINESS — flag a FLAT or lifeless turn that adds nothing and kills momentum. Be extra "
     "conservative here; only flag a clearly dead turn."},
)


def _review_context(cast, topic: str, prior_turns, segment_turns) -> str:
    lines = [f"TOPIC: {topic}", f"HOST = {cast.host.name}; EXPERT = {cast.expert.name}", "",
             "CONVERSATION SO FAR (before this segment):"]
    lines += [f"  {t.speaker.upper()}: {t.text}" for t in prior_turns] or ["  (none)"]
    lines += ["", "SEGMENT TO REVIEW:"]
    lines += [f"  [{i}] {t.speaker.upper()} ({t.move}): {t.text}"
              for i, t in enumerate(segment_turns)]
    return "\n".join(lines)


def _run_reviewer(client, context: str, reviewer: dict, run) -> list[dict]:
    user = f"{context}\n\nYOUR CHECK: {reviewer['objective']}"
    data = sarvam_llm.complete_json(client, _REVIEW_RUBRIC, user, run, stage="review", temperature=0.2)
    flags = []
    for r in (data.get("flags") or []):
        try:
            idx = int(r.get("idx"))
        except (TypeError, ValueError):
            continue
        flags.append({"idx": idx, "issue": str(r.get("issue", "")).strip(),
                      "hint": str(r.get("hint", "")).strip(), "severity": reviewer["severity"]})
    return flags


def review_segment(client, segment_turns, cast, topic: str, prior_turns, run) -> list[dict]:
    """Run the reviewer panel IN PARALLEL; aggregate flags (hard first, one per turn)."""
    context = _review_context(cast, topic, prior_turns, segment_turns)
    results: list[dict] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(_REVIEWERS)) as ex:
        futures = [ex.submit(_run_reviewer, client, context, rv, run) for rv in _REVIEWERS]
        for fut in concurrent.futures.as_completed(futures):
            try:
                results.extend(fut.result())
            except Exception as e:  # noqa: BLE001 - one reviewer failing shouldn't sink the panel
                run.log(stage="review", kind="reviewer_error", error=str(e)[:200])

    n = len(segment_turns)
    by_idx: dict[int, dict] = {}
    for flag in results:
        if not (0 <= flag["idx"] < n):
            continue
        cur = by_idx.get(flag["idx"])
        if cur is None or (flag["severity"] == "hard" and cur["severity"] != "hard"):
            by_idx[flag["idx"]] = flag  # prefer a hard flag when two reviewers hit one turn
    return sorted(by_idx.values(), key=lambda r: (0 if r["severity"] == "hard" else 1, r["idx"]))
