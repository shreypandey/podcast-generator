"""Dialogue stage: intro → per-turn Director→Speaker body loop → outro
(SCRIPT_GENERATION.md §7). Director decides each body beat; the speaker sees only a short
window. Code owns the arc, continuity, coverage, and budgets. M1: no verify gate (that's M2)."""
from __future__ import annotations

from app import config
from app.agents import director, grounder, speaker
from app.artifacts import Cast, FactSheet, Outline, Script, Turn

# Anti-monotony + coherence guards (M1 polish). Bounded to one re-ask each.
_PINGPONG_MOVES = {"ask", "explain"}
_VARY_DIRECTIVE = (
    "AVOID MONOTONY: the last turns were a plain ask/explain volley. Pick a DIFFERENT move "
    "(react, illustrate, connect, or a gentle challenge) — have the host react or the expert "
    "build, not another Q&A."
)
_FORWARD_DIRECTIVE = (
    "Do NOT open by attributing anything to your co-host ('you mentioned/you said'). Ask a "
    "forward question or react directly instead."
)
_BANNED_OPENERS = ("you mentioned", "you said", "as you said", "as you noted",
                   "you talked about", "you brought up", "you pointed out")
_VIEW_QUOTE_CHARS = 220
_SPEAKER_QUOTE_CHARS = 220
_SPEAKER_QUOTES_PER_FACT = 2
_REPAIR_UNSUPPORTED_ITEMS = 3
_REPAIR_UNSUPPORTED_CHARS = 420
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


def _is_pingpong(recent_beats: list[tuple[str, str]], beat) -> bool:
    """True if this beat would make a 3rd consecutive ask/explain turn."""
    seq = [m for _, m in recent_beats[-2:]] + [beat.move]
    return len(seq) == 3 and all(m in _PINGPONG_MOVES for m in seq)


def _has_banned_opener(text: str) -> bool:
    head = text.lower()[:60]
    return any(p in head for p in _BANNED_OPENERS)


def _fact_flags(f) -> str:
    flags = []
    if f.evidence_strength == "weak":
        flags.append("weak")
    if f.conflicts_with:
        flags.append("conflicts " + ",".join(f.conflicts_with))
    if f.caveats:
        flags.append("caveat: " + "; ".join(f.caveats))
    if f.tension_type not in ("none", ""):
        flags.append(f.tension_type)
    return f"  [TENSION: {'; '.join(flags)}]" if flags else ""


def _fact_label(f) -> str:
    return f"[{getattr(f, 'fact_type', 'background')}/{getattr(f, 'story_role', 'explain')}]"


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


def _source_coverage(fact_by_id: dict, coverage: dict) -> dict[str, int]:
    counts: dict[str, int] = {}
    for fid, used in coverage.items():
        fact = fact_by_id.get(fid)
        if not fact:
            continue
        for sid in getattr(fact, "source_ids", []):
            counts[sid] = counts.get(sid, 0) + used
    return counts


def _type_priority(f, settings=None) -> int:
    angle = getattr(settings, "angle", "balanced") if settings else "balanced"
    priority = _ANGLE_FACT_TYPE_PRIORITY.get(angle, _FACT_TYPE_PRIORITY)
    return priority.get(getattr(f, "fact_type", "background"), 9)


def _fact_use_key(f, coverage: dict, source_counts: dict[str, int], challenges_left: int,
                  settings=None) -> tuple:
    source_use = min((source_counts.get(sid, 0) for sid in getattr(f, "source_ids", [])), default=0)
    return (
        coverage.get(f.id, 0),
        source_use,
        _type_priority(f, settings),
        -float(getattr(f, "quality_score", 0.0)),
        _fact_id_num(f.id),
    )


def _segment_fact_ids(segment, fact_by_id: dict) -> list[str]:
    ids = [fid for fid in segment.fact_ids if fid in fact_by_id]
    return ids or list(fact_by_id.keys())


def _best_fact_id(segment_ids: list[str], fact_by_id: dict, coverage: dict,
                  challenges_left: int, *, tension_only: bool = False, settings=None) -> str:
    source_counts = _source_coverage(fact_by_id, coverage)
    candidates = [fact_by_id[fid] for fid in segment_ids if fid in fact_by_id]
    if tension_only:
        candidates = [f for f in candidates if _is_tension_fact(f)]
    if not candidates:
        return ""
    return sorted(
        candidates,
        key=lambda f: _fact_use_key(f, coverage, source_counts, challenges_left, settings),
    )[0].id


def _repair_focus(beat, focus: list[str], segment_ids: list[str], fact_by_id: dict,
                  coverage: dict, challenges_left: int, settings=None) -> list[str]:
    if beat.speaker != "expert":
        return []

    focus = [fid for fid in focus if fid in segment_ids and fid in fact_by_id]
    if beat.move == "challenge" and challenges_left > 0:
        if not focus or not any(_is_tension_fact(fact_by_id[fid]) for fid in focus):
            tension_id = _best_fact_id(segment_ids, fact_by_id, coverage, challenges_left,
                                       tension_only=True, settings=settings)
            if tension_id:
                return [tension_id]

    if beat.move in ("explain", "illustrate") and not focus:
        best_id = _best_fact_id(segment_ids, fact_by_id, coverage, challenges_left, settings=settings)
        return [best_id] if best_id else []

    if focus:
        unused = [fid for fid in segment_ids if fid in fact_by_id and coverage.get(fid, 0) == 0]
        if unused and any(coverage.get(fid, 0) > 0 for fid in focus):
            best_unused = _best_fact_id(unused, fact_by_id, coverage, challenges_left, settings=settings)
            selected_score = max(float(getattr(fact_by_id[fid], "quality_score", 0.0)) for fid in focus)
            unused_score = float(getattr(fact_by_id[best_unused], "quality_score", 0.0)) if best_unused else 0.0
            if best_unused and unused_score >= selected_score + 0.05:
                return [best_unused]

    return focus


def _quote_for_view(f) -> str:
    quotes = getattr(f, "source_quotes", []) or []
    if not quotes:
        return ""
    quote = " ".join(str(quotes[0]).split())
    if len(quote) > _VIEW_QUOTE_CHARS:
        quote = quote[:_VIEW_QUOTE_CHARS - 3].rstrip() + "..."
    return quote


def _trim_for_speaker(value: str, limit: int = _SPEAKER_QUOTE_CHARS) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[:limit - 3].rstrip() + "..."


def _fact_card(f) -> str:
    """Evidence card shown privately to the Expert; not meant to be read aloud."""
    label = f"[{getattr(f, 'fact_type', 'background')}/{getattr(f, 'story_role', 'explain')}]"
    lines = [f"{f.id} {label} CLAIM: {f.claim}"]
    for quote in (getattr(f, "source_quotes", []) or [])[:_SPEAKER_QUOTES_PER_FACT]:
        text = _trim_for_speaker(str(quote))
        if text:
            lines.append(f"  EVIDENCE: \"{text}\"")
    caveats = [str(c).strip() for c in getattr(f, "caveats", []) if str(c).strip()]
    if caveats:
        lines.append("  CAVEAT: " + "; ".join(caveats[:2]))
    return "\n".join(lines)


def _fact_cards(fact_by_id: dict, focus: list[str]) -> list[str]:
    return [_fact_card(fact_by_id[fid]) for fid in focus if fid in fact_by_id]


def _unsupported_note(unsupported: list[str]) -> str:
    items: list[str] = []
    for value in unsupported[:_REPAIR_UNSUPPORTED_ITEMS]:
        text = " ".join(str(value or "").split()).strip()
        if text:
            items.append(text)
    note = "; ".join(items)
    if len(unsupported) > len(items):
        note = f"{note}; ..." if note else "unsupported specifics"
    if len(note) > _REPAIR_UNSUPPORTED_CHARS:
        note = note[:_REPAIR_UNSUPPORTED_CHARS - 3].rstrip() + "..."
    return note or "unsupported specifics"


def _repair_instruction(unsupported: list[str]) -> str:
    return (
        "REPAIR: Rewrite the previous Expert turn using ONLY the FACTS YOU MAY USE above. "
        "Treat each EVIDENCE line as the boundary of what can be safely said. Do not add a new "
        "mechanism, example, number, failure mode, or replacement detail unless it is directly "
        "supported by those fact cards. Do not quote the evidence aloud. Drop or generalize "
        f"these unsupported specifics: {_unsupported_note(unsupported)}"
    )


def _segment_terms(segment) -> list[str]:
    return [str(t).strip() for t in getattr(segment, "terms_to_define", []) if str(t).strip()]


def _speaker_ladder_instruction(segment, body_count: int, beat) -> str:
    parts: list[str] = []
    listener_question = str(getattr(segment, "listener_question", "") or "").strip()
    terms = _segment_terms(segment)
    if body_count < 4:
        parts.append(
            "This is still listener onboarding: establish the plain object, ordinary problem, "
            "basic input/output, or everyday mental model before expert mechanisms."
        )
    if listener_question:
        parts.append(f"Answer this listener prerequisite before advancing: {listener_question}")
    if terms:
        parts.append(
            "Define these terms in plain language before using them as shorthand: "
            + ", ".join(terms)
        )
    if beat.speaker == "expert":
        parts.append(
            "Say the plain idea first, then optionally name the technical term. Use at most one "
            "new technical term in this turn unless each term is immediately defined."
        )
    else:
        parts.append(
            "If the expert concept is not yet simple, ask the basic clarifying question a smart "
            "listener would ask."
        )
    return "LEARNING LADDER: " + " ".join(parts)


def _view(topic: str, segment, fact_by_id: dict, recent_turns, coverage: dict,
          recent_beats: list[tuple[str, str]], challenges_left: int, settings=None) -> str:
    lines = [f"TOPIC: {topic}", f"CURRENT SEGMENT GOAL: {segment.goal}"]
    listener_question = str(getattr(segment, "listener_question", "") or "").strip()
    if listener_question:
        lines.append(f"LISTENER QUESTION TO ANSWER BEFORE ADVANCING: {listener_question}")
    terms = _segment_terms(segment)
    if terms:
        lines.append("TERMS TO DEFINE BEFORE USING AS SHORTHAND: " + ", ".join(terms))
    lines += [
        "LEARNING LADDER RULE: build prerequisites first; separate basics, mechanism, evidence, "
        "tradeoff, and recap instead of collapsing them into one expert answer.",
        "",
        "FACTS AVAILABLE THIS SEGMENT:",
    ]
    seg_ids = _segment_fact_ids(segment, fact_by_id)
    source_counts = _source_coverage(fact_by_id, coverage)
    seg_ids = sorted(
        seg_ids,
        key=lambda fid: _fact_use_key(fact_by_id[fid], coverage, source_counts, challenges_left, settings),
    )
    for fid in seg_ids:
        f = fact_by_id[fid]
        score = float(getattr(f, "quality_score", 0.0))
        lines.append(
            f"  {fid} {_fact_label(f)} score={score:.2f}: {f.claim}  "
            f"(used {coverage.get(fid, 0)}x){_fact_flags(f)}"
        )
        quote = _quote_for_view(f)
        if quote:
            lines.append(f"    evidence: \"{quote}\"")
    lines += ["", "RECENT TURNS:"]
    if recent_turns:
        lines += [f"  {t.speaker.upper()} [{t.move}]: {t.text}" for t in recent_turns]
    else:
        lines.append("  (start of the discussion)")
    if settings:
        lines += ["", "STEERING:", config.angle_brief(settings), config.style_brief(settings)]
    if recent_beats:
        lines += ["", "RECENT PATTERN: " + " → ".join(f"{s}:{m}" for s, m in recent_beats[-4:])]
    lines += ["", f"CHALLENGE BUDGET remaining: {challenges_left} (the 'challenge' move is "
              "allowed ONLY on a fact tagged TENSION, and only while this is > 0)"]
    return "\n".join(lines)


def _intro(client, topic: str, cast: Cast, outline: Outline, run, settings=None) -> list[Turn]:
    hook = outline.opening_hook or topic
    host_instr = (
        f"Open the show for a general listener who may not know why this matters yet. First "
        f"name the ordinary listener problem or confusion behind today's topic, \"{topic}\". "
        f"Use this hook only after that setup — \"{hook}\". Define the topic in one plain "
        f"sentence before any technical term. Then introduce expert guest {cast.expert.name} "
        f"({cast.expert.background}). Do not call the expert a co-host."
    )
    t0 = speaker.framing_turn(client, "host", cast.host, host_instr, [], run, settings)
    turns = [Turn(idx=0, speaker="host", text=t0, move="intro")]

    expert_instr = (
        f"Greet {cast.host.name} and the listeners. In one or two plain sentences, say what "
        f"you'll help unpack and why a normal listener should care. Avoid unexplained jargon, "
        f"specific numbers, and advanced terms in this opening."
    )
    t1 = speaker.framing_turn(client, "expert", cast.expert, expert_instr, turns, run, settings)
    turns.append(Turn(idx=1, speaker="expert", text=t1, move="intro"))
    return turns


def _outro(client, cast: Cast, outline: Outline, recent, run, settings=None) -> list[Turn]:
    closing = outline.closing or "wrap up the key takeaway"
    turns: list[Turn] = []
    if not recent or recent[-1].speaker != "host":
        bridge_instr = (
            f"Bridge from the last point into the ending. Ask expert guest {cast.expert.name} "
            f"(use exactly that name) for the three things listeners should remember. Keep it "
            f"short and conversational; do not introduce new facts."
        )
        bridge = speaker.framing_turn(client, "host", cast.host, bridge_instr, recent, run, settings)
        turns.append(Turn(idx=0, speaker="host", text=bridge, move="outro"))

    expert_instr = (
        f"Bring the conversation toward a close. If you address the host, call them "
        f"{cast.host.name} (use exactly that name). Give a real listener recap, not a generic "
        f"big-picture sentence. Use this natural shape: 'So, remember three things. First... "
        f"Second... Third...' Return to the opening listener problem or hook, and avoid new "
        f"technical terms. Note honestly what's still uncertain. Guidance: {closing}"
    )
    t0 = speaker.framing_turn(client, "expert", cast.expert, expert_instr,
                              recent + turns, run, settings)
    host_instr = (
        f"Thank expert guest {cast.expert.name} (use exactly that name) and the listeners. "
        f"End with one soft closing sentence that reinforces the simplest takeaway. Do not "
        f"call the expert a co-host."
    )
    turns.append(Turn(idx=0, speaker="expert", text=t0, move="outro"))
    t1 = speaker.framing_turn(client, "host", cast.host, host_instr, recent + turns, run, settings)
    turns.append(Turn(idx=0, speaker="host", text=t1, move="outro"))
    return turns


def _repair_speaker_sequence(beat: director.Beat, recent: list[Turn],
                             body_count: int) -> director.Beat:
    """Keep the body conversational: Host opens the body, then speakers alternate."""
    if body_count == 0 and beat.speaker != "host":
        return director.Beat(
            speaker="host",
            move="ask",
            fact_focus=[],
            intent="open the body with a concise question that sets up the current segment",
            segment_status="continue",
        )
    if not recent:
        return beat
    prev = recent[-1]
    if prev.move in ("intro", "outro") or prev.speaker != beat.speaker:
        return beat
    if beat.speaker == "expert":
        move = "challenge" if beat.move == "challenge" else "react"
        return director.Beat(
            speaker="host",
            move=move,
            fact_focus=[],
            intent=(
                "react to the expert's previous point and ask a concise follow-up that bridges "
                "to the next idea; do not add new facts"
            ),
            segment_status="continue",
        )
    return director.Beat(
        speaker="expert",
        move="explain",
        fact_focus=beat.fact_focus,
        intent="answer the host's previous turn directly, using only the focused facts",
        segment_status=beat.segment_status,
    )


def _can_close_segment(seg_turns: int, body_count: int, segment_index: int,
                       total_segments: int, settings) -> bool:
    min_turns = getattr(settings, "min_turns_per_segment", 2)
    if seg_turns < min_turns:
        return False
    min_total = getattr(settings, "min_total_turns", getattr(settings, "max_total_turns", body_count))
    if body_count >= min_total:
        return True
    remaining_segments = max(0, total_segments - segment_index - 1)
    future_capacity = remaining_segments * getattr(settings, "max_turns_per_segment", min_turns)
    return min_total - body_count <= future_capacity


def _should_stop_body_after_segment(segment_index: int, total_segments: int,
                                    body_count: int, settings,
                                    segment_closed: bool) -> bool:
    if body_count >= getattr(settings, "max_total_turns", body_count):
        return True
    min_total = getattr(settings, "min_total_turns", getattr(settings, "max_total_turns", body_count))
    if body_count < min_total:
        return False
    target_total = getattr(settings, "target_total_turns", min_total)
    if body_count >= target_total:
        return True
    return segment_closed and segment_index >= max(0, total_segments - 2)


def run(client, topic: str, factsheet: FactSheet, cast: Cast, outline: Outline, settings, run) -> Script:
    fact_by_id = {f.id: f for f in factsheet.facts}
    coverage: dict[str, int] = {}

    turns: list[Turn] = _intro(client, topic, cast, outline, run, settings)

    body_count = 0
    challenges_used = 0
    recent_beats: list[tuple[str, str]] = []
    def _revise(gi: int, rev: dict) -> None:
        """Regenerate turn[gi] in place per an editor flag; re-verify if it's the Expert."""
        turn = turns[gi]
        persona = cast.expert if turn.speaker == "expert" else cast.host
        focus = [fid for fid in turn.cited_fact_ids if fid in fact_by_id]
        fact_texts = _fact_cards(fact_by_id, focus) if turn.speaker == "expert" else []
        recent_ = turns[max(0, gi - config.CONTEXT_WINDOW_TURNS):gi]
        beat = director.Beat(speaker=turn.speaker, move=turn.move, fact_focus=focus,
                             intent="", segment_status="continue")
        instr = f"REVISION — {rev['issue']}. {rev['hint']}".strip()
        newtext = speaker.generate(client, turn.speaker, persona, beat, fact_texts, recent_, run,
                                   extra_instruction=instr, depth=settings.depth, settings=settings)
        if not newtext:
            return
        verified = turn.verified
        if turn.speaker == "expert":
            ok, unsupported = grounder.verify_turn(
                client, newtext, factsheet, run, cited_fact_ids=focus
            )
            if not ok and config.VERIFY_MAX_REPAIRS > 0:
                repair = _repair_instruction(unsupported)
                rt = speaker.generate(client, turn.speaker, persona, beat, fact_texts, recent_,
                                      run, extra_instruction=repair, depth=settings.depth,
                                      settings=settings)
                if rt:
                    newtext = rt
                    ok, _ = grounder.verify_turn(
                        client, newtext, factsheet, run, cited_fact_ids=focus
                    )
            verified = ok
        turn.text = newtext
        turn.verified = verified
        run.log(stage="review", kind="revised", idx=gi, issue=rev["issue"])

    total_segments = len(outline.segments)
    for segment_index, segment in enumerate(outline.segments):
        seg_start = len(turns)
        seg_turns = 0
        segment_closed = False
        while seg_turns < settings.max_turns_per_segment and body_count < settings.max_total_turns:
            recent = turns[-config.CONTEXT_WINDOW_TURNS:]
            view = _view(topic, segment, fact_by_id, recent, coverage, recent_beats,
                         config.MAX_CHALLENGES - challenges_used, settings)
            beat = director.next_beat(client, view, run)
            if _is_pingpong(recent_beats, beat):  # bounded anti-monotony re-ask
                beat = director.next_beat(client, view, run, extra=_VARY_DIRECTIVE)
            beat = _repair_speaker_sequence(beat, recent, body_count)

            persona = cast.expert if beat.speaker == "expert" else cast.host
            is_challenge = beat.move == "challenge"
            segment_ids = _segment_fact_ids(segment, fact_by_id)
            challenges_left = config.MAX_CHALLENGES - challenges_used
            # Only the EXPERT bears specific facts; the HOST reasons/asks/pushes back.
            if beat.speaker == "expert":
                focus = _repair_focus(beat, beat.fact_focus, segment_ids, fact_by_id,
                                      coverage, challenges_left, settings)
                if is_challenge:  # include conflicting facts so both sides are citable/grounded
                    conflicts = [c for fid in focus for c in fact_by_id[fid].conflicts_with
                                 if c in fact_by_id]
                    focus = list(dict.fromkeys(focus + conflicts))
            else:
                focus = []
            fact_texts = _fact_cards(fact_by_id, focus) if beat.speaker == "expert" else []

            gen_instr = ""
            ladder_instr = _speaker_ladder_instruction(segment, body_count, beat)
            if is_challenge:
                gen_instr = (
                    "Honestly surface the tension here: these facts genuinely conflict or the "
                    "evidence is weak/caveated — say so and lay out both sides."
                    if beat.speaker == "expert" else
                    "Voice a skeptical, listener's-doubt question about how solid this really is "
                    "— push back without asserting any new facts."
                )
            gen_instr = " ".join(part for part in [gen_instr, ladder_instr] if part).strip()

            text = speaker.generate(client, beat.speaker, persona, beat, fact_texts, recent, run,
                                    extra_instruction=gen_instr, depth=settings.depth, settings=settings)
            if text and _has_banned_opener(text):  # bounded coherence regen
                text = speaker.generate(client, beat.speaker, persona, beat, fact_texts, recent,
                                        run, extra_instruction=f"{_FORWARD_DIRECTIVE} {ladder_instr}",
                                        depth=settings.depth,
                                        settings=settings)
            if not text:
                break

            # M2a: verification gate — only the EXPERT bears facts, so only it needs checking.
            verified = True
            if beat.speaker == "expert":
                ok, unsupported = grounder.verify_turn(
                    client, text, factsheet, run, cited_fact_ids=focus
                )
                repairs = 0
                while not ok and repairs < config.VERIFY_MAX_REPAIRS:
                    repairs += 1
                    instr = _repair_instruction(unsupported)
                    retext = speaker.generate(client, beat.speaker, persona, beat, fact_texts,
                                              recent, run, extra_instruction=instr, depth=settings.depth,
                                              settings=settings)
                    if not retext:
                        break
                    text = retext
                    ok, unsupported = grounder.verify_turn(
                        client, text, factsheet, run, cited_fact_ids=focus
                    )
                verified = ok
                if not ok:
                    run.log(stage="verify", kind="unsupported", unsupported=unsupported,
                            text=text[:200])

            turns.append(Turn(idx=len(turns), speaker=beat.speaker, text=text,
                              move=beat.move, cited_fact_ids=focus, verified=verified))
            recent_beats.append((beat.speaker, beat.move))
            if is_challenge:
                challenges_used += 1
            for fid in focus:
                coverage[fid] = coverage.get(fid, 0) + 1
            body_count += 1
            seg_turns += 1
            if beat.segment_status == "close" and _can_close_segment(
                seg_turns, body_count, segment_index, total_segments, settings
            ):
                segment_closed = True
                break

        # M3 editor: review the completed segment and revise flagged turns
        seg_slice = turns[seg_start:]
        if len(seg_slice) >= 2:
            revisions = director.review_segment(client, seg_slice, cast, topic, turns[:seg_start], run)
            for rev in revisions[:config.MAX_SEGMENT_REVISIONS]:
                gi = seg_start + rev["idx"]
                if seg_start <= gi < len(turns):
                    _revise(gi, rev)

        if _should_stop_body_after_segment(
            segment_index, total_segments, body_count, settings, segment_closed
        ):
            break

    turns += _outro(client, cast, outline, turns[-config.CONTEXT_WINDOW_TURNS:], run, settings)

    for i, t in enumerate(turns):  # final sequential reindex (intro + body + outro)
        t.idx = i
    return Script(turns=turns)
