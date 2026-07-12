from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.agents import director
from app.artifacts import Fact, FactSheet


class DummyRun:
    def log(self, **kw):
        pass


def fact(fid: str, fact_type: str, score: float) -> Fact:
    return Fact(id=fid, claim=f"{fid} claim", fact_type=fact_type, quality_score=score)


class DirectorCoverageTests(unittest.TestCase):
    def test_beat_prompt_keeps_podcast_host_clarifier_behavior(self):
        self.assertIn("smart but non-specialist listener", director.BEAT_SYSTEM)
        self.assertIn("previous Expert turn used jargon", director.BEAT_SYSTEM)
        self.assertIn("what does that mean in everyday terms", director.BEAT_SYSTEM)
        self.assertIn("concrete example", director.BEAT_SYSTEM)

    def test_plan_outline_repairs_missing_high_value_facts(self):
        factsheet = FactSheet(facts=[
            fact("F1", "caveat", 0.88),
            fact("F2", "mechanism", 0.82),
            fact("F3", "background", 0.3),
        ])
        response = {
            "opening_hook": "hook",
            "closing": "close",
            "segments": [
                {"goal": "first", "fact_ids": ["F404"]},
                {"goal": "second", "fact_ids": ["F3"]},
            ],
        }
        settings = SimpleNamespace(max_total_turns=10, depth=3, max_segments=2)

        with patch("app.adapters.sarvam_llm.complete_json", return_value=response):
            outline = director.plan_outline(object(), "topic", factsheet, settings, DummyRun())

        assigned = [fid for segment in outline.segments for fid in segment.fact_ids]
        self.assertNotIn("F404", assigned)
        self.assertIn("F1", assigned)
        self.assertIn("F2", assigned)
        self.assertIn("F3", assigned)

    def test_plan_outline_prioritizes_mechanism_before_caveat_but_keeps_caveat(self):
        factsheet = FactSheet(facts=[
            fact("F1", "background", 0.4),
            fact("F2", "mechanism", 0.7),
            fact("F3", "caveat", 0.65),
            fact("F4", "finding", 0.75),
            fact("F5", "stat", 0.72),
        ])
        response = {
            "segments": [
                {"goal": "only", "fact_ids": ["F1", "F2", "F3", "F4", "F5"]},
            ],
        }
        settings = SimpleNamespace(max_total_turns=6, depth=3, max_segments=1)

        with patch("app.adapters.sarvam_llm.complete_json", return_value=response):
            outline = director.plan_outline(object(), "topic", factsheet, settings, DummyRun())

        self.assertEqual(outline.segments[0].fact_ids[0], "F2")
        self.assertIn("F3", outline.segments[0].fact_ids)

    def test_plan_outline_adds_one_caveat_when_llm_omits_caveats(self):
        factsheet = FactSheet(facts=[
            fact("F1", "mechanism", 0.9),
            fact("F2", "mechanism", 0.8),
            fact("F3", "mechanism", 0.7),
            fact("F4", "mechanism", 0.6),
            fact("F5", "mechanism", 0.5),
            fact("F6", "mechanism", 0.4),
            fact("F7", "caveat", 0.3),
        ])
        response = {
            "segments": [
                {"goal": "only", "fact_ids": ["F1", "F2", "F3", "F4", "F5", "F6"]},
            ],
        }
        settings = SimpleNamespace(max_total_turns=4, depth=3, max_segments=1)

        with patch("app.adapters.sarvam_llm.complete_json", return_value=response):
            outline = director.plan_outline(object(), "topic", factsheet, settings, DummyRun())

        self.assertIn("F7", outline.segments[0].fact_ids)

    def test_plan_outline_pads_to_configured_segment_count(self):
        factsheet = FactSheet(facts=[
            fact("F1", "mechanism", 0.9),
            fact("F2", "finding", 0.8),
            fact("F3", "example", 0.7),
            fact("F4", "caveat", 0.6),
            fact("F5", "background", 0.5),
        ])
        response = {
            "segments": [
                {"goal": "only", "fact_ids": ["F1"]},
            ],
        }
        settings = SimpleNamespace(max_total_turns=18, depth=4, max_segments=4)

        with patch("app.adapters.sarvam_llm.complete_json", return_value=response):
            outline = director.plan_outline(object(), "topic", factsheet, settings, DummyRun())

        self.assertEqual(len(outline.segments), 4)
        self.assertTrue(all(segment.fact_ids for segment in outline.segments))

    def test_plan_outline_parses_listener_ladder_fields(self):
        factsheet = FactSheet(facts=[
            fact("F1", "mechanism", 0.9),
            fact("F2", "example", 0.8),
        ])
        response = {
            "segments": [
                {
                    "goal": "plain setup",
                    "listener_question": "What is the basic object?",
                    "terms_to_define": ["dense term", "dense term"],
                    "fact_ids": ["F1", "F2"],
                },
            ],
        }
        settings = SimpleNamespace(max_total_turns=8, depth=3, max_segments=1)

        with patch("app.adapters.sarvam_llm.complete_json", return_value=response):
            outline = director.plan_outline(object(), "topic", factsheet, settings, DummyRun())

        self.assertEqual(outline.segments[0].listener_question, "What is the basic object?")
        self.assertEqual(outline.segments[0].terms_to_define, ["dense term"])


if __name__ == "__main__":
    unittest.main()
