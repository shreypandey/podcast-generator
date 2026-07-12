"""Planning stage: casting (topic-derived personas) + outline."""
from __future__ import annotations

from app.agents import director
from app.artifacts import Cast, FactSheet, Outline


def run(client, topic: str, factsheet: FactSheet, settings, run) -> tuple[Cast, Outline]:
    cast = director.cast(client, topic, factsheet, run)
    outline = director.plan_outline(client, topic, factsheet, settings, run)
    return cast, outline
