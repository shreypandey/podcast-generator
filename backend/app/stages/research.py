"""Research stage: Brief -> QueryPlan -> SourceCorpus (N final sources)."""
from __future__ import annotations

import math
from urllib.parse import urlsplit, urlunsplit

from app.adapters import exa as exa_adapter
from app.agents import query_planner
from app.artifacts import Brief, QueryPlan, Source, SourceCorpus


def _normalized_url(url: str) -> str:
    parts = urlsplit((url or "").strip())
    scheme = parts.scheme.lower()
    netloc = parts.netloc.lower()
    path = parts.path.rstrip("/")
    return urlunsplit((scheme, netloc, path, "", ""))


def _merge_source(existing: Source, incoming: Source) -> None:
    if len(incoming.text or "") > len(existing.text or ""):
        existing.text = incoming.text
    if not existing.title and incoming.title:
        existing.title = incoming.title
    for h in incoming.highlights:
        if h not in existing.highlights:
            existing.highlights.append(h)
    for qid in incoming.query_ids:
        if qid not in existing.query_ids:
            existing.query_ids.append(qid)
    for intent in incoming.query_intents:
        if intent not in existing.query_intents:
            existing.query_intents.append(intent)
    existing.search_rank = min(existing.search_rank, incoming.search_rank)


def _dedupe(candidates: list[Source]) -> list[Source]:
    by_url: dict[str, Source] = {}
    for source in candidates:
        key = _normalized_url(source.url)
        if not key:
            continue
        if key in by_url:
            _merge_source(by_url[key], source)
        else:
            source.url = key
            by_url[key] = source
    return list(by_url.values())


def _rank_sources(candidates: list[Source], plan: QueryPlan, limit: int) -> list[Source]:
    priority_by_query = {q.id: q.priority for q in plan.queries}
    selected: list[Source] = []
    selected_urls: set[str] = set()

    def source_priority(source: Source) -> int:
        priorities = [priority_by_query[qid] for qid in source.query_ids if qid in priority_by_query]
        return min(priorities) if priorities else 999

    def quality_key(source: Source):
        return (0 if (source.text or "").strip() else 1, source.search_rank, source.url)

    for query in sorted(plan.queries, key=lambda q: q.priority):
        options = [
            s for s in candidates
            if query.id in s.query_ids and s.url not in selected_urls
        ]
        if not options:
            continue
        best = sorted(options, key=quality_key)[0]
        selected.append(best)
        selected_urls.add(best.url)
        if len(selected) >= limit:
            break

    if len(selected) < limit:
        remaining = [s for s in candidates if s.url not in selected_urls]
        remaining.sort(key=lambda s: (source_priority(s),) + quality_key(s))
        for source in remaining:
            selected.append(source)
            selected_urls.add(source.url)
            if len(selected) >= limit:
                break

    for i, source in enumerate(selected, start=1):
        source.id = f"S{i}"
    return selected


def _fallback_single_search(exa, brief: Brief, settings, run) -> tuple[QueryPlan, SourceCorpus]:
    plan = query_planner.fallback_plan(brief.topic, 1, settings)
    source_limit = getattr(settings, "max_grounding_sources", settings.num_sources)
    corpus = exa_adapter.fetch_sources(exa, brief.topic, source_limit, run)
    for source in corpus.sources:
        source.query_ids = [plan.queries[0].id]
        source.query_intents = [plan.queries[0].intent]
    run.log(stage="research", kind="fallback_single_search", n_sources=len(corpus.sources))
    return plan, corpus


def run(exa, sarvam, brief: Brief, settings, run) -> tuple[QueryPlan, SourceCorpus]:
    plan = query_planner.plan_queries(sarvam, brief.topic, settings.num_queries, run, settings)
    source_limit = getattr(settings, "max_grounding_sources", settings.num_sources)
    per_query = max(3, min(8, math.ceil(source_limit * 3 / max(1, len(plan.queries)))))

    candidates: list[Source] = []
    for query in plan.queries:
        try:
            candidates.extend(exa_adapter.search_sources(
                exa, query.query, per_query, run,
                query_id=query.id, query_intent=query.intent,
            ))
        except Exception as e:  # noqa: BLE001 - one bad search should not kill the run
            run.log(stage="research", kind="exa_error", query=query.query,
                    query_id=query.id, error=str(e)[:200])

    deduped = _dedupe(candidates)
    final_sources = _rank_sources(deduped, plan, source_limit)
    run.log(stage="research", kind="rank", candidates=len(candidates),
            deduped=len(deduped), final_sources=len(final_sources))

    if not final_sources:
        return _fallback_single_search(exa, brief, settings, run)
    return plan, SourceCorpus(sources=final_sources)
