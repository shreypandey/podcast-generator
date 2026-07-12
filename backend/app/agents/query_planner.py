"""Query planner agent: topic -> podcast-oriented Exa search plan.

The planner improves source diversity before grounding while keeping the final source count
bounded by depth. If the LLM plan fails, deterministic templates keep research runnable.
"""
from __future__ import annotations

from app import config
from app.adapters import sarvam_llm
from app.artifacts import QueryPlan, SearchQuery

INTENT_ORDER = [
    "core_explainer",
    "primary_official",
    "caveat_critique",
    "recent_current",
    "example_case",
]
_INTENTS = set(INTENT_ORDER)

SYSTEM = (
    "You are a research query planner for a grounded podcast. Given a topic, produce diverse web "
    "search queries that will help create an accurate, interesting episode. Optimize for podcast "
    "evidence: a clear explainer source, primary/official source, caveats or criticism, recent or "
    "current source, and a concrete example or case study when relevant. Queries must be concise, "
    "standalone, and non-overlapping. Use only these intents: core_explainer, primary_official, "
    "caveat_critique, recent_current, example_case. Respond with ONLY JSON: "
    '{"queries": [{"intent": "core_explainer", "query": "...", "rationale": "...", '
    '"priority": 1}]}.'
)


_ANGLE_QUERY_HINTS = {
    "balanced": [],
    "mechanism": [
        ("core_explainer", "{topic} mechanism how it works step by step"),
        ("example_case", "{topic} concrete example mechanism case study"),
    ],
    "current": [
        ("recent_current", "{topic} latest updates current status recent research"),
        ("primary_official", "{topic} official update current guidance"),
    ],
    "controversy": [
        ("caveat_critique", "{topic} controversy limitations criticism evidence"),
        ("primary_official", "{topic} official evidence safety review"),
    ],
    "practical": [
        ("example_case", "{topic} practical implications real world examples"),
        ("core_explainer", "{topic} what it means practical guide"),
    ],
    "mythbusting": [
        ("caveat_critique", "{topic} myths misconceptions fact check"),
        ("primary_official", "{topic} official myth facts FAQ"),
    ],
    "beginner": [
        ("core_explainer", "{topic} beginner guide explained simply"),
        ("example_case", "{topic} simple example analogy"),
    ],
}


def _template_queries(topic: str, max_queries: int, settings=None) -> list[SearchQuery]:
    templates = [
        ("core_explainer", f"{topic} explained how it works overview"),
        ("primary_official", f"{topic} official source primary evidence"),
        ("caveat_critique", f"{topic} limitations caveats criticism evidence"),
        ("recent_current", f"{topic} latest research current status"),
        ("example_case", f"{topic} case study example real world"),
    ]
    angle = getattr(settings, "angle", "balanced") if settings else "balanced"
    angled = [(intent, query.format(topic=topic)) for intent, query in _ANGLE_QUERY_HINTS.get(angle, [])]
    focus_queries = [
        ("core_explainer", f"{topic} {question}")
        for question in getattr(settings, "focus_questions", [])[:2]
    ] if settings else []
    templates = angled + focus_queries + templates
    queries = []
    seen: set[str] = set()
    for intent, query in templates:
        key = " ".join(query.lower().split())
        if key in seen:
            continue
        seen.add(key)
        if len(queries) >= max_queries:
            break
        queries.append(SearchQuery(
            id=f"Q{len(queries) + 1}",
            intent=intent,
            query=query,
            rationale=f"Fallback {intent.replace('_', ' ')} query.",
            priority=len(queries) + 1,
        ))
    return queries


def fallback_plan(topic: str, max_queries: int, settings=None) -> QueryPlan:
    return QueryPlan(topic=topic, queries=_template_queries(topic, max_queries, settings))


def _normalize_plan(topic: str, raw_queries: list, max_queries: int, settings=None) -> QueryPlan:
    queries: list[SearchQuery] = []
    seen_queries: set[str] = set()

    for item in raw_queries:
        if not isinstance(item, dict):
            continue
        query = str(item.get("query", "")).strip()
        if not query:
            continue
        key = " ".join(query.lower().split())
        if key in seen_queries:
            continue
        seen_queries.add(key)

        intent = str(item.get("intent", "core_explainer")).strip().lower()
        if intent not in _INTENTS:
            intent = "core_explainer"
        try:
            priority = int(item.get("priority", len(queries) + 1))
        except (TypeError, ValueError):
            priority = len(queries) + 1

        queries.append(SearchQuery(
            id="",  # assigned after sorting
            intent=intent,
            query=query,
            rationale=str(item.get("rationale", "")).strip(),
            priority=max(1, priority),
        ))

    queries.sort(key=lambda q: (q.priority, INTENT_ORDER.index(q.intent), q.query))
    queries = queries[:max_queries]
    for i, q in enumerate(queries, start=1):
        q.id = f"Q{i}"
        q.priority = i

    if not queries:
        return fallback_plan(topic, max_queries, settings)
    return QueryPlan(topic=topic, queries=queries)


def _steering_block(settings) -> str:
    if not settings:
        return ""
    return "\n\nSTEERING:\n" + config.angle_brief(settings)


def plan_queries(client, topic: str, max_queries: int, run, settings=None) -> QueryPlan:
    max_queries = max(1, min(5, int(max_queries or 1)))
    user = (
        f"TOPIC: {topic}\n\n"
        f"{_steering_block(settings)}\n\n"
        f"Return exactly {max_queries} queries, ordered by priority. If an intent is not relevant, "
        "prefer the next most useful podcast-evidence query instead of forcing it. For mythbusting, "
        "include queries that find misconception/FAQ/fact-check sources. For controversy, include "
        "critique/limitation/safety-review sources. For current, include recent/current sources."
    )
    try:
        data = sarvam_llm.complete_json(client, SYSTEM, user, run, stage="query_plan", temperature=0.2)
        plan = _normalize_plan(topic, data.get("queries") or [], max_queries, settings)
        if plan.queries:
            return plan
    except Exception as e:  # noqa: BLE001 - research should degrade to deterministic planning
        run.log(stage="query_plan", kind="fallback", error=str(e)[:200])
    return fallback_plan(topic, max_queries, settings)
