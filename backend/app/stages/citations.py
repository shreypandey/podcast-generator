"""M2a citations: map cited facts → sources, and render a human-readable transcript.md.

Citations = Turn.cited_fact_ids → Fact.source_ids → Source. Host turns cite nothing;
Expert turns cite their assigned facts."""
from __future__ import annotations

from app.artifacts import Cast, Script, Source


def _ordered_sources(script: Script, fact_by_id: dict, source_by_id: dict):
    """Assign [n] citation numbers to sources in order of first appearance."""
    number: dict[str, int] = {}
    order: list[Source] = []
    for t in script.turns:
        for fid in t.cited_fact_ids:
            f = fact_by_id.get(fid)
            if not f:
                continue
            for sid in f.source_ids:
                if sid in source_by_id and sid not in number:
                    number[sid] = len(order) + 1
                    order.append(source_by_id[sid])
    return number, order


def cited_sources(script: Script, fact_by_id: dict, source_by_id: dict) -> list[Source]:
    _, order = _ordered_sources(script, fact_by_id, source_by_id)
    return order


def _turn_citation_numbers(turn, fact_by_id: dict, number: dict) -> list[int]:
    nums: list[int] = []
    for fid in turn.cited_fact_ids:
        f = fact_by_id.get(fid)
        if not f:
            continue
        for sid in f.source_ids:
            n = number.get(sid)
            if n and n not in nums:
                nums.append(n)
    return sorted(nums)


def write_transcript_md(path: str, topic: str, cast: Cast, script: Script,
                        fact_by_id: dict, source_by_id: dict,
                        display_texts: list[str] | None = None,
                        include_citations: bool = True,
                        include_sources: bool = True,
                        include_verification_flags: bool = True) -> None:
    """`display_texts` (per-turn) overrides the turn text — e.g. the translated/spoken
    delivery. Public transcripts can hide citation/debug markers while evidence transcripts
    keep them for inspection."""
    number, order = _ordered_sources(script, fact_by_id, source_by_id)
    name = {"host": cast.host.name, "expert": cast.expert.name}

    lines = [f"# {topic}", ""]
    for i, t in enumerate(script.turns):
        cites = _turn_citation_numbers(t, fact_by_id, number)
        marker = " " + "".join(f"[{n}]" for n in cites) if include_citations and cites else ""
        flag = (
            "" if (getattr(t, "verified", True) or not include_verification_flags)
            else "  _(unverified)_"
        )
        text = display_texts[i] if (display_texts and i < len(display_texts) and display_texts[i]) else t.text
        lines.append(f"**{name.get(t.speaker, t.speaker.title())}:** {text}{marker}{flag}")
        lines.append("")

    if include_sources:
        lines += ["## Sources", ""]
        for i, s in enumerate(order, start=1):
            lines.append(f"{i}. [{s.title or s.url}]({s.url})")

    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")
