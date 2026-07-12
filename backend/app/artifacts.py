"""Typed artifacts that flow between stages. Mirrors ARCHITECTURE.md /
SCRIPT_GENERATION.md schemas (M1 subset: no tension annotation / verification yet)."""
from __future__ import annotations

from pydantic import BaseModel, Field


class Brief(BaseModel):
    topic: str
    length: str = "medium"  # short | medium | long  (drives turns/segments)
    depth: int = 3           # 1..5  (drives sources/facts + explanation detail)
    languages: list[str] = ["en-IN"]  # M4: render an episode per language (en-IN = bypass)
    angle: str = "balanced"  # balanced | mechanism | current | controversy | practical | mythbusting | beginner
    focus_questions: list[str] = []
    custom_angle: str = ""
    tone: str = "conversational"  # conversational | serious | energetic | calm | investigative
    style: str = "curious_expert"  # curious_expert | debate | storytelling | classroom | news_analysis
    custom_style: str = ""


class SearchQuery(BaseModel):
    id: str  # Q1..Qn
    intent: str
    query: str
    rationale: str = ""
    priority: int = 1


class QueryPlan(BaseModel):
    topic: str
    queries: list[SearchQuery]


class Source(BaseModel):
    id: str  # S1..Sn
    url: str
    title: str = ""
    text: str = ""
    highlights: list[str] = []
    origin: str = "exa"
    query_ids: list[str] = []
    query_intents: list[str] = []
    search_rank: int = 999


class SourceCorpus(BaseModel):
    sources: list[Source]


class Fact(BaseModel):
    id: str  # F1..Fm
    claim: str
    source_ids: list[str] = []
    source_quotes: list[str] = []
    fact_type: str = "background"  # mechanism | finding | stat | caveat | counterclaim | example | misconception | background
    story_role: str = "explain"    # explain | illustrate | challenge | context | transition
    quality_score: float = 0.0
    quality_notes: list[str] = []
    # M2b tension annotation (drives evidence-driven challenge)
    evidence_strength: str = "moderate"  # weak | moderate | strong
    conflicts_with: list[str] = []       # ids of facts this genuinely contradicts
    caveats: list[str] = []
    tension_type: str = "none"           # empirical | interpretive | normative | none


class FactSheet(BaseModel):
    facts: list[Fact]


class Persona(BaseModel):
    role: str  # "host" | "expert"
    name: str
    background: str
    gender: str = ""  # "male" | "female" (drives voice selection)
    voice: str  # Bulbul speaker id


class Cast(BaseModel):
    host: Persona
    expert: Persona


class Segment(BaseModel):
    id: str  # SEG1..
    goal: str
    fact_ids: list[str] = []
    listener_question: str = ""
    terms_to_define: list[str] = []


class Outline(BaseModel):
    opening_hook: str = ""
    segments: list[Segment]
    closing: str = ""


class Turn(BaseModel):
    idx: int
    speaker: str  # "host" | "expert"
    text: str  # canonical, verified, cited — never mutated by the humanizer
    move: str = ""
    cited_fact_ids: list[str] = []
    verified: bool = True  # set by the M2a grounding gate (expert turns only)
    spoken: str = ""       # humanized delivery text used for TTS (falls back to text)
    pace: float = 1.0      # TTS pace 0.9..1.15 (humanizer, Lever C)


class DeliveryPhrase(BaseModel):
    text: str
    pace: float = 1.0
    pause_after_ms: int = 120


class TurnDelivery(BaseModel):
    turn_idx: int
    speaker: str
    delivery_text: str = ""
    phrases: list[DeliveryPhrase] = Field(default_factory=list)


class DeliveryPlan(BaseModel):
    language: str = "en-IN"
    turns: list[TurnDelivery] = Field(default_factory=list)


class Script(BaseModel):
    turns: list[Turn]


class Episode(BaseModel):
    language: str = "en-IN"  # M4: which language this episode was rendered in
    audio_path: str
    transcript: list[Turn]
    deliveries: list[str] = []  # per-turn spoken/translated delivery text (for the transcript)
    delivery_plan: list[TurnDelivery] = Field(default_factory=list)
    sources: list[Source] = []  # sources cited across the episode
