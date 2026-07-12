from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app import config
from app.agents import humanizer, query_planner, speaker
from app.artifacts import Brief, Fact, FactSheet, Persona, Segment, Turn
from app.run import _split_focus
from app.stages.dialogue import _repair_focus, _view


class DummyRun:
    def log(self, **kw):
        pass


class SteeringConfigTests(unittest.TestCase):
    def test_resolve_settings_normalizes_presets_and_custom_text(self):
        brief = Brief(
            topic="topic",
            angle="myth-busting",
            focus_questions=["  what is false?  ", "what is false?", "x" * 300],
            custom_angle="  keep it about public myths  ",
            tone="ENERGETIC",
            style="news-analysis",
            custom_style="  crisp but not hype  ",
        )

        settings = config.resolve_settings(brief)

        self.assertEqual(settings.angle, "mythbusting")
        self.assertEqual(settings.focus_questions[:2], ["what is false?", "x" * 160])
        self.assertEqual(settings.custom_angle, "keep it about public myths")
        self.assertEqual(settings.tone, "energetic")
        self.assertEqual(settings.style, "news_analysis")
        self.assertEqual(settings.custom_style, "crisp but not hype")

    def test_invalid_presets_fall_back(self):
        settings = config.resolve_settings(Brief(topic="topic", angle="bad", tone="bad", style="bad"))

        self.assertEqual(settings.angle, "balanced")
        self.assertEqual(settings.tone, "conversational")
        self.assertEqual(settings.style, "curious_expert")

    def test_cli_focus_split_supports_repeat_and_commas(self):
        self.assertEqual(_split_focus(["first, second", "third"]), ["first", "second", "third"])


class SteeringQueryPlannerTests(unittest.TestCase):
    def test_fallback_plan_uses_mythbusting_specialized_queries(self):
        settings = SimpleNamespace(angle="mythbusting", focus_questions=["Does it change DNA?"])

        plan = query_planner.fallback_plan("mRNA vaccines", 3, settings)

        queries = [q.query.lower() for q in plan.queries]
        self.assertIn("myths misconceptions fact check", queries[0])
        self.assertTrue(any("does it change dna" in query for query in queries))

    def test_query_planner_prompt_includes_steering(self):
        settings = SimpleNamespace(
            angle="controversy",
            focus_questions=["What is actually disputed?"],
            custom_angle="avoid generic safety claims",
        )
        response = {"queries": [
            {"intent": "caveat_critique", "query": "topic controversy evidence", "priority": 1},
        ]}

        with patch("app.adapters.sarvam_llm.complete_json", return_value=response) as complete:
            query_planner.plan_queries(object(), "topic", 1, DummyRun(), settings)

        user = complete.call_args.args[2]
        self.assertIn("ANGLE: controversy", user)
        self.assertIn("What is actually disputed?", user)
        self.assertIn("avoid generic safety claims", user)


class SteeringDialogueTests(unittest.TestCase):
    def test_mythbusting_focus_prefers_misconception_fact(self):
        facts = {
            "F1": Fact(id="F1", claim="mechanism", quality_score=0.9, fact_type="mechanism"),
            "F2": Fact(id="F2", claim="misconception", quality_score=0.7, fact_type="misconception"),
        }
        beat = SimpleNamespace(speaker="expert", move="explain")
        settings = SimpleNamespace(angle="mythbusting")

        focus = _repair_focus(beat, [], ["F1", "F2"], facts, coverage={}, challenges_left=2, settings=settings)

        self.assertEqual(focus, ["F2"])

    def test_view_includes_angle_and_style_steering(self):
        fact = Fact(id="F1", claim="claim", fact_type="mechanism")
        segment = Segment(id="SEG1", goal="goal", fact_ids=["F1"])
        settings = SimpleNamespace(angle="mechanism", tone="calm", style="classroom")

        text = _view("topic", segment, {"F1": fact}, [], {}, [], 2, settings)

        self.assertIn("STEERING:", text)
        self.assertIn("ANGLE: mechanism", text)
        self.assertIn("TONE: calm", text)
        self.assertIn("STYLE: classroom", text)


class SteeringStyleTests(unittest.TestCase):
    def test_speaker_prompt_includes_style_guide(self):
        persona = Persona(role="expert", name="Dr. Rao", background="scientist", voice="aditya")
        beat = SimpleNamespace(move="explain", intent="explain clearly")
        settings = SimpleNamespace(tone="serious", style="news_analysis", custom_style="no jokes")

        with patch("app.adapters.sarvam_llm.complete_json", return_value={"text": "ok"}) as complete:
            speaker.generate(object(), "expert", persona, beat, ["fact"], [], DummyRun(), settings=settings)

        user = complete.call_args.args[2]
        self.assertIn("STYLE GUIDE:", user)
        self.assertIn("TONE: serious", user)
        self.assertIn("STYLE: news_analysis", user)
        self.assertIn("no jokes", user)

    def test_humanizer_prompt_includes_style_guide(self):
        turn = Turn(idx=0, speaker="host", text="This is the turn.")
        settings = SimpleNamespace(tone="energetic", style="storytelling")

        with patch("app.adapters.sarvam_llm.complete_json",
                   return_value={"spoken": "So, this is the turn.", "pace": 1.05}) as complete:
            spoken, pace = humanizer.humanize_turn(object(), [turn], DummyRun(), settings)

        user = complete.call_args.args[2]
        self.assertIn("STYLE GUIDE:", user)
        self.assertIn("TONE: energetic", user)
        self.assertIn("STYLE: storytelling", user)
        self.assertEqual(spoken, "So, this is the turn.")
        self.assertEqual(pace, 1.05)


if __name__ == "__main__":
    unittest.main()
