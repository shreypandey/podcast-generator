"""Grounder agent (map step): one source -> atomic, cited claims.

M1: extraction only. Tension annotation + turn verification arrive in M2
(SCRIPT_GENERATION.md §4-5)."""
from __future__ import annotations

from app import config
from app.adapters import sarvam_llm
from app.artifacts import Fact, Source

SYSTEM = (
    "You are a careful grounding agent. From the SOURCE below, extract 2-4 atomic, factual, "
    "individually-checkable claims that are FULLY supported by the source text. Prefer claims "
    "that are useful in a podcast: mechanisms, substantive findings, caveats, recent/current "
    "evidence, concrete examples, and misconception-correcting facts. Avoid generic background, "
    "methodology-only details, navigation text, and institutional boilerplate unless they are the "
    "source's strongest evidence. Use no outside knowledge and no opinions. Each claim must be "
    "one self-contained sentence. Classify each fact_type as one of: mechanism, finding, stat, "
    "caveat, counterclaim, example, misconception, background. Classify story_role as one of: "
    "explain, illustrate, challenge, context, transition. For each fact, include 1-2 short "
    "source_quotes copied exactly from the SOURCE text that directly support the claim; do not "
    "invent, paraphrase, or use long paragraphs as quotes. Respond with ONLY JSON: "
    '{"facts": [{"claim": "...", "fact_type": "mechanism", "story_role": "explain", '
    '"source_quotes": ["short exact source excerpt"]}]}.'
)

FACT_TYPES = {
    "mechanism", "finding", "stat", "caveat", "counterclaim", "example", "misconception", "background",
}
STORY_ROLES = {"explain", "illustrate", "challenge", "context", "transition"}
_DEFAULT_ROLE_BY_TYPE = {
    "caveat": "challenge",
    "counterclaim": "challenge",
    "example": "illustrate",
    "background": "context",
}
MAX_QUOTES_PER_FACT = 2
MAX_QUOTE_CHARS = 300


def _trim_quote(value: str, limit: int = MAX_QUOTE_CHARS) -> str:
    quote = " ".join(str(value or "").split())
    if len(quote) <= limit:
        return quote
    return quote[: max(0, limit - 3)].rstrip() + "..."


def _normalize_quotes(values) -> list[str]:
    if isinstance(values, str):
        raw_values = [values]
    elif isinstance(values, list):
        raw_values = values
    else:
        raw_values = []

    quotes: list[str] = []
    for value in raw_values:
        quote = _trim_quote(str(value))
        if quote and quote not in quotes:
            quotes.append(quote)
        if len(quotes) >= MAX_QUOTES_PER_FACT:
            break
    return quotes


def _normalize_fact_type(value: str) -> str:
    fact_type = str(value or "").strip().lower().replace("-", "_")
    return fact_type if fact_type in FACT_TYPES else "background"


def _default_story_role(fact_type: str) -> str:
    return _DEFAULT_ROLE_BY_TYPE.get(fact_type, "explain")


def _normalize_story_role(value: str, fact_type: str) -> str:
    if fact_type in ("caveat", "counterclaim"):
        return "challenge"
    story_role = str(value or "").strip().lower().replace("-", "_")
    return story_role if story_role in STORY_ROLES else _default_story_role(fact_type)


def _fact_from_item(item, source_id: str) -> Fact | None:
    if isinstance(item, dict):
        claim = str(item.get("claim", "")).strip()
        if not claim:
            return None
        quotes = _normalize_quotes(item.get("source_quotes"))
        if not quotes:
            return None
        fact_type = _normalize_fact_type(str(item.get("fact_type", "")))
        story_role = _normalize_story_role(str(item.get("story_role", "")), fact_type)
        return Fact(id="", claim=claim, source_ids=[source_id],
                    source_quotes=quotes,
                    fact_type=fact_type, story_role=story_role)

    claim = str(item).strip()
    if not claim:
        return None
    return Fact(id="", claim=claim, source_ids=[source_id],
                fact_type="background", story_role="explain")


def _chunks(text: str) -> list[str]:
    """Split into gateway-safe chunks; bound the count so huge pages don't explode cost."""
    size = config.GROUND_CHUNK_CHARS
    parts = [text[i:i + size] for i in range(0, len(text), size)]
    return parts[:config.MAX_CHUNKS_PER_SOURCE]


def extract_facts(client, source: Source, run) -> list[Fact]:
    body = source.text or " ".join(source.highlights)
    facts: list[Fact] = []
    chunks = _chunks(body) or [body]
    for ci, chunk in enumerate(chunks, start=1):
        if not chunk.strip():
            continue
        user = f"SOURCE {source.id} — {source.title} (part {ci}/{len(chunks)})\n\n{chunk}"
        data = sarvam_llm.complete_json(client, SYSTEM, user, run, stage="ground")
        items = data.get("facts") or data.get("claims") or []
        for item in items[:4]:
            fact = _fact_from_item(item, source.id)
            if fact:
                facts.append(fact)  # id set in reduce
    return facts


# --- M2a: verification gate (Grounder-as-judge) ------------------------------
VERIFY_SYSTEM = (
    "You are a strict fact-checker for a podcast. Given the EXPERT'S SPOKEN TURN and the list "
    "of KNOWN FACTS WITH SOURCE QUOTES, identify any SPECIFIC factual claim in the turn — "
    "numbers, named mechanisms, dates, named entities, or concrete causal claims — that is NOT "
    "supported by the fact claim and its exact quote evidence. Treat the quote as controlling: "
    "if a detail is not present in either the claim or quote, do not infer it from outside "
    "knowledge. Allow natural paraphrases and conservative synthesis across multiple quoted "
    "facts. Ignore general framing, opinions, analogies, and paraphrases that are consistent "
    "with the quoted facts. Respond with ONLY JSON: "
    '{"supported": true, "unsupported_claims": []}. Set supported=false only if the turn '
    "contains at least one unsupported specific claim (list those claims)."
)


def _verification_fact_block(f) -> str:
    label = f"[{getattr(f, 'fact_type', 'background')}/{getattr(f, 'story_role', 'explain')}]"
    score = float(getattr(f, "quality_score", 0.0))
    lines = [f"  {f.id} {label} score={score:.2f}: {f.claim}"]
    for quote in (getattr(f, "source_quotes", []) or [])[:2]:
        lines.append(f"    quote: \"{' '.join(str(quote).split())}\"")
    return "\n".join(lines)


def _verification_facts(factsheet, cited_fact_ids: list[str] | None = None) -> str:
    facts = factsheet.facts
    if cited_fact_ids:
        wanted = set(cited_fact_ids)
        filtered = [f for f in facts if f.id in wanted]
        facts = filtered or facts
    return "\n".join(_verification_fact_block(f) for f in facts)


def verify_turn(client, turn_text: str, factsheet, run,
                cited_fact_ids: list[str] | None = None) -> tuple[bool, list[str]]:
    facts = _verification_facts(factsheet, cited_fact_ids)
    user = f"KNOWN FACTS:\n{facts}\n\nEXPERT'S SPOKEN TURN:\n{turn_text}"
    try:
        data = sarvam_llm.complete_json(client, VERIFY_SYSTEM, user, run, stage="verify", temperature=0.1)
    except Exception as e:  # noqa: BLE001 - accept-and-flag; verifier failure should not sink run
        run.log(stage="verify", kind="verifier_error", error=str(e)[:300])
        return False, [f"verifier error: {str(e)[:180]}"]
    unsupported = [str(x).strip() for x in (data.get("unsupported_claims") or []) if str(x).strip()]
    supported = bool(data.get("supported", True)) and not unsupported
    return supported, unsupported


# --- M2b: tension annotation (reduce step) -----------------------------------
ANNOTATE_SYSTEM = (
    "You annotate a list of FACTS with genuine tension, CONSERVATIVELY. For each fact id give: "
    "evidence_strength (weak|moderate|strong); conflicts_with (ids of OTHER facts that state an "
    "incompatible number or claim — only real contradictions, usually none); caveats (short "
    "strings like 'small sample' or 'one location'); tension_type "
    "(empirical|interpretive|normative|none). Most facts are strong/moderate with no conflicts "
    "and tension_type 'none' — only flag tension that genuinely exists in the text. "
    'Respond with ONLY JSON: {"annotations": [{"id": "F1", "evidence_strength": "moderate", '
    '"conflicts_with": [], "caveats": [], "tension_type": "none"}]}.'
)

_STRENGTHS = {"weak", "moderate", "strong"}
_TENSIONS = {"empirical", "interpretive", "normative", "none"}


def annotate_tension(client, factsheet, run):
    by_id = {f.id: f for f in factsheet.facts}
    facts = "\n".join(f"  {f.id}: {f.claim}" for f in factsheet.facts)
    try:
        data = sarvam_llm.complete_json(client, ANNOTATE_SYSTEM, facts, run, stage="annotate", temperature=0.2)
    except Exception as e:  # noqa: BLE001 - tension is useful, but should not sink the run
        run.log(stage="annotate", kind="fallback", error=str(e)[:300])
        data = {"annotations": [
            {
                "id": f.id,
                "evidence_strength": "moderate",
                "conflicts_with": [],
                "caveats": [],
                "tension_type": "none",
            }
            for f in factsheet.facts
        ]}

    for a in (data.get("annotations") or []):
        f = by_id.get(str(a.get("id", "")).strip())
        if not f:
            continue
        es = str(a.get("evidence_strength", "moderate")).strip().lower()
        f.evidence_strength = es if es in _STRENGTHS else "moderate"
        f.conflicts_with = [c for c in (str(x).strip() for x in (a.get("conflicts_with") or []))
                            if c in by_id and c != f.id]
        f.caveats = [str(x).strip() for x in (a.get("caveats") or []) if str(x).strip()]
        tt = str(a.get("tension_type", "none")).strip().lower()
        f.tension_type = tt if tt in _TENSIONS else "none"

    # make conflicts symmetric so either fact surfaces the tension
    for f in factsheet.facts:
        for c in f.conflicts_with:
            if f.id not in by_id[c].conflicts_with:
                by_id[c].conflicts_with.append(f.id)
    return factsheet
