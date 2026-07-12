"""Grounding stage: SourceCorpus -> FactSheet (map-reduce).

Map: Grounder extracts facts per source. Reduce: merge, cap, assign global ids."""
from __future__ import annotations

import concurrent.futures
import re
from urllib.parse import urlsplit

from app import config
from app.agents import grounder
from app.artifacts import Fact, FactSheet, Source, SourceCorpus

_INTENT_BONUS = {
    "caveat_critique": 0,
    "recent_current": 1,
    "primary_official": 2,
    "core_explainer": 3,
    "example_case": 4,
}
_FACT_TYPE_BONUS = {
    "caveat": 0,
    "counterclaim": 1,
    "mechanism": 2,
    "finding": 3,
    "stat": 4,
    "example": 5,
    "misconception": 6,
    "background": 7,
}
_TYPE_SCORE = {
    "counterclaim": 0.68,
    "caveat": 0.66,
    "mechanism": 0.63,
    "finding": 0.6,
    "stat": 0.58,
    "example": 0.55,
    "misconception": 0.54,
    "background": 0.32,
}
_INTENT_SCORE = {
    "caveat_critique": 0.05,
    "recent_current": 0.045,
    "primary_official": 0.04,
    "example_case": 0.035,
    "core_explainer": 0.025,
}
_CREDIBLE_DOMAIN_NAMES = (
    "who.int", "nih.gov", "cdc.gov", "fda.gov", "nhs.uk", "medlineplus.gov",
    "nature.com", "nejm.org", "thelancet.com", "bmj.com",
    "frontiersin.org", "sciencedirect.com", "springer.com", "wiley.com", "jamanetwork.com",
)
_REPUTABLE_DOMAIN_PARTS = (
    "clevelandclinic.org", "mayoclinic.org", "scientificamerican.com",
)
_GENERIC_PATTERNS = (
    "this article", "this report", "this review", "this study used", "we searched",
    "pubmed", "methodology", "systematic review was conducted", "copyright",
    "all rights reserved", "click here", "subscribe",
)


def _tokens(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9]+", text.lower()) if len(t) > 2}


def _domain(url: str) -> str:
    return urlsplit(url or "").netloc.lower().removeprefix("www.")


def _is_named_domain(domain: str, name: str) -> bool:
    return domain == name or domain.endswith(f".{name}")


def _is_credible_domain(domain: str) -> bool:
    if domain.endswith(".gov") or domain.endswith(".edu") or ".ac." in domain:
        return True
    return any(_is_named_domain(domain, name) for name in _CREDIBLE_DOMAIN_NAMES)


def _source_credibility(source: Source) -> tuple[float, str]:
    domain = _domain(source.url)
    if _is_credible_domain(domain):
        return 0.04, "credible source domain"
    if any(part in domain for part in _REPUTABLE_DOMAIN_PARTS):
        return 0.02, "reputable explainer domain"
    return -0.05, "unscored source domain"


def _quote_support(fact: Fact) -> tuple[float, list[str]]:
    notes: list[str] = []
    if not fact.source_quotes:
        return -0.12, ["missing source quote"]
    score = 0.04 if len(fact.source_quotes) == 1 else 0.05
    notes.append("quoted evidence")

    claim_tokens = _tokens(fact.claim)
    quote_tokens = _tokens(" ".join(fact.source_quotes))
    overlap = len(claim_tokens & quote_tokens) / max(1, len(claim_tokens))
    if overlap >= 0.45:
        score += 0.04
        notes.append("quote supports claim")
    elif overlap < 0.2:
        score -= 0.08
        notes.append("weak quote overlap")
    if all(len(q) < 35 for q in fact.source_quotes):
        score -= 0.04
        notes.append("short quote")
    return score, notes


def _generic_penalty(claim: str) -> tuple[float, list[str]]:
    lower = claim.lower()
    if any(pattern in lower for pattern in _GENERIC_PATTERNS):
        return -0.14, ["generic or methodology-like wording"]
    if len(_tokens(claim)) < 6:
        return -0.08, ["thin claim"]
    return 0.0, []


def _duplicate_penalties(facts: list[Fact]) -> dict[int, tuple[float, str]]:
    penalties: dict[int, tuple[float, str]] = {}
    seen: list[set[str]] = []
    for fact in facts:
        tokens = _tokens(fact.claim)
        penalty = 0.0
        note = ""
        for prev in seen:
            jaccard = len(tokens & prev) / max(1, len(tokens | prev))
            if jaccard >= 0.72:
                penalty = -0.12
                note = "near-duplicate claim"
                break
        seen.append(tokens)
        if penalty:
            penalties[id(fact)] = (penalty, note)
    return penalties


def _score_facts(facts: list[Fact], corpus: SourceCorpus) -> None:
    source_by_id = {source.id: source for source in corpus.sources}
    duplicate_penalty = _duplicate_penalties(facts)
    for fact in facts:
        sid = fact.source_ids[0] if fact.source_ids else ""
        source = source_by_id.get(sid)
        notes: list[str] = []
        score = _TYPE_SCORE.get(fact.fact_type, _TYPE_SCORE["background"])
        notes.append(f"type={fact.fact_type}")

        if source:
            intent_bonus = max((_INTENT_SCORE.get(intent, 0.0) for intent in source.query_intents), default=0.0)
            if intent_bonus:
                score += intent_bonus
                notes.append("useful query intent")
            if source.search_rank <= 1:
                score += 0.02
                notes.append("top search result")
            elif source.search_rank <= 3:
                score += 0.01
                notes.append("high search result")
            credibility_score, credibility_note = _source_credibility(source)
            score += credibility_score
            notes.append(credibility_note)

        quote_score, quote_notes = _quote_support(fact)
        score += quote_score
        notes.extend(quote_notes)

        generic_score, generic_notes = _generic_penalty(fact.claim)
        score += generic_score
        notes.extend(generic_notes)

        if id(fact) in duplicate_penalty:
            penalty, note = duplicate_penalty[id(fact)]
            score += penalty
            notes.append(note)

        fact.quality_score = round(max(0.0, min(1.0, score)), 3)
        fact.quality_notes = notes


def _source_order(corpus: SourceCorpus) -> dict[str, int]:
    return {source.id: i for i, source in enumerate(corpus.sources)}


def _intent_rank_by_source(corpus: SourceCorpus) -> dict[str, int]:
    ranks: dict[str, int] = {}
    for source in corpus.sources:
        intent_ranks = [_INTENT_BONUS.get(intent, 9) for intent in source.query_intents]
        ranks[source.id] = min(intent_ranks) if intent_ranks else 9
    return ranks


def _fact_key(fact: Fact, source_pos: dict[str, int], intent_rank: dict[str, int], order: int):
    sid = fact.source_ids[0] if fact.source_ids else ""
    return (
        -fact.quality_score,
        _FACT_TYPE_BONUS.get(fact.fact_type, 9),
        intent_rank.get(sid, 9),
        source_pos.get(sid, 999),
        order,
    )


def _reduce_facts(facts: list[Fact], corpus: SourceCorpus, max_facts: int) -> list[Fact]:
    """Keep facts source-diverse before filling by source/intent priority.

    The map step extracts source-by-source, so a plain global slice starves later sources. This
    reducer first gives every source with facts a slot, then adds a second pass for podcast-useful
    intents, then fills the remaining budget.
    """
    if len(facts) <= max_facts:
        return facts

    source_pos = _source_order(corpus)
    intent_rank = _intent_rank_by_source(corpus)
    facts_by_source: dict[str, list[tuple[int, Fact]]] = {}
    for order, fact in enumerate(facts):
        sid = fact.source_ids[0] if fact.source_ids else ""
        facts_by_source.setdefault(sid, []).append((order, fact))

    selected: list[Fact] = []
    selected_ids: set[int] = set()

    def add_fact(order: int, fact: Fact) -> bool:
        if len(selected) >= max_facts or id(fact) in selected_ids:
            return False
        selected.append(fact)
        selected_ids.add(id(fact))
        return True

    for source in corpus.sources:
        options = facts_by_source.get(source.id, [])
        if options:
            add_fact(*sorted(options, key=lambda item: _fact_key(item[1], source_pos, intent_rank, item[0]))[0])

    def second_pass_source_key(source):
        remaining = facts_by_source.get(source.id, [])[1:]
        best_quality = max((fact.quality_score for _, fact in remaining), default=-1.0)
        best_type = min((_FACT_TYPE_BONUS.get(fact.fact_type, 9) for _, fact in remaining), default=9)
        return (-best_quality, best_type, intent_rank.get(source.id, 9), source_pos.get(source.id, 999))

    prioritized_sources = sorted(corpus.sources, key=second_pass_source_key)
    for source in prioritized_sources:
        options = facts_by_source.get(source.id, [])
        remaining_options = [(order, fact) for order, fact in options if id(fact) not in selected_ids]
        if remaining_options:
            add_fact(*sorted(remaining_options, key=lambda item: _fact_key(item[1], source_pos, intent_rank, item[0]))[0])

    remaining = [
        (order, fact) for order, fact in enumerate(facts)
        if id(fact) not in selected_ids
    ]
    remaining.sort(key=lambda item: _fact_key(item[1], source_pos, intent_rank, item[0]))
    for order, fact in remaining:
        add_fact(order, fact)
        if len(selected) >= max_facts:
            break

    return selected


def run(client, corpus: SourceCorpus, settings, run) -> FactSheet:
    facts_by_source: dict[str, list[Fact]] = {}
    workers = max(1, min(config.GROUND_MAX_WORKERS, len(corpus.sources) or 1))

    def work(src):
        extracted = grounder.extract_facts(client, src, run)
        return src.id, extracted

    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        futures = {ex.submit(work, src): src for src in corpus.sources}
        for fut in concurrent.futures.as_completed(futures):
            src = futures[fut]
            try:
                sid, extracted = fut.result()
                facts_by_source[sid] = extracted
                run.log(stage="ground", kind="source_done", source_id=sid,
                        n_facts=len(extracted))
            except Exception as e:  # noqa: BLE001 - one failed source should not sink research
                facts_by_source[src.id] = []
                run.log(stage="ground", kind="source_error", source_id=src.id,
                        error=str(e)[:200])

    facts = []
    for src in corpus.sources:
        facts.extend(facts_by_source.get(src.id, []))
    if not facts:
        raise ValueError("Grounding produced no facts from any source")

    before = len(facts)
    _score_facts(facts, corpus)
    facts = _reduce_facts(facts, corpus, settings.max_facts)
    scores = [f.quality_score for f in facts]
    run.log(stage="ground", kind="reduce", candidates=before,
            final_facts=len(facts), sources=len({sid for f in facts for sid in f.source_ids}),
            quality_min=round(min(scores), 3) if scores else None,
            quality_max=round(max(scores), 3) if scores else None,
            quality_avg=round(sum(scores) / len(scores), 3) if scores else None)
    for i, f in enumerate(facts, start=1):
        f.id = f"F{i}"
    factsheet = FactSheet(facts=facts)
    return grounder.annotate_tension(client, factsheet, run)  # M2b: tension flags
