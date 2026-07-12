"""Exa adapter: search queries -> source candidates with contents."""
from __future__ import annotations

import time

from app.artifacts import Source, SourceCorpus


def search_sources(exa, query: str, num: int, run, query_id: str = "",
                   query_intent: str = "") -> list[Source]:
    t0 = time.time()
    res = exa.search_and_contents(query, num_results=num, text=True, highlights=True, type="auto")
    dt = round(time.time() - t0, 2)

    sources: list[Source] = []
    for i, r in enumerate(res.results, start=1):
        sources.append(Source(
            id="",
            url=r.url,
            title=getattr(r, "title", "") or "",
            text=getattr(r, "text", "") or "",  # full text (Sarvam-105B has 128K context)
            highlights=list(getattr(r, "highlights", None) or []),
            origin="exa",
            query_ids=[query_id] if query_id else [],
            query_intents=[query_intent] if query_intent else [],
            search_rank=i,
        ))
    run.log(stage="research", kind="exa", query=query, query_id=query_id,
            query_intent=query_intent, latency_s=dt, n_sources=len(sources))
    return sources


def fetch_sources(exa, topic: str, num: int, run) -> SourceCorpus:
    sources = search_sources(exa, topic, num, run)
    for i, source in enumerate(sources[:num], start=1):
        source.id = f"S{i}"
    return SourceCorpus(sources=sources)
