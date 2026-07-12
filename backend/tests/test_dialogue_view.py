from __future__ import annotations

import unittest
from types import SimpleNamespace

from app.agents.director import Beat
from app.artifacts import Fact, Segment, Turn
from app.stages.dialogue import _can_close_segment, _repair_focus, _repair_speaker_sequence, _view


class DialogueViewTests(unittest.TestCase):
    def test_view_includes_fact_type_and_story_role_labels(self):
        fact = Fact(
            id="F1",
            claim="mRNA is translated by ribosomes.",
            source_ids=["S1"],
            source_quotes=["ribosomes read mRNA instructions inside the cell"],
            fact_type="mechanism",
            story_role="explain",
        )
        segment = Segment(id="SEG1", goal="Explain the mechanism.", fact_ids=["F1"])

        text = _view(
            "how mRNA vaccines work",
            segment,
            {"F1": fact},
            recent_turns=[],
            coverage={},
            recent_beats=[],
            challenges_left=2,
        )

        self.assertIn("F1 [mechanism/explain] score=0.00: mRNA is translated by ribosomes.", text)
        self.assertIn('evidence: "ribosomes read mRNA instructions inside the cell"', text)

    def test_view_trims_long_evidence_quote(self):
        fact = Fact(
            id="F1",
            claim="mRNA is translated by ribosomes.",
            source_ids=["S1"],
            source_quotes=[" ".join(["quote"] * 80)],
            fact_type="mechanism",
            story_role="explain",
        )
        segment = Segment(id="SEG1", goal="Explain the mechanism.", fact_ids=["F1"])

        text = _view(
            "how mRNA vaccines work",
            segment,
            {"F1": fact},
            recent_turns=[],
            coverage={},
            recent_beats=[],
            challenges_left=2,
        )

        evidence_line = next(line for line in text.splitlines() if "evidence:" in line)
        self.assertLessEqual(len(evidence_line), 236)
        self.assertIn("...", evidence_line)

    def test_view_includes_listener_ladder_fields(self):
        fact = Fact(id="F1", claim="basic claim")
        segment = Segment(
            id="SEG1",
            goal="Build the plain mental model.",
            fact_ids=["F1"],
            listener_question="What should I understand before the mechanism?",
            terms_to_define=["technical term"],
        )

        text = _view(
            "topic",
            segment,
            {"F1": fact},
            recent_turns=[],
            coverage={},
            recent_beats=[],
            challenges_left=2,
        )

        self.assertIn("LISTENER QUESTION TO ANSWER BEFORE ADVANCING", text)
        self.assertIn("What should I understand before the mechanism?", text)
        self.assertIn("TERMS TO DEFINE BEFORE USING AS SHORTHAND: technical term", text)
        self.assertIn("LEARNING LADDER RULE", text)

    def test_repair_focus_assigns_best_fact_to_expert_explain(self):
        facts = {
            "F1": Fact(id="F1", claim="lower score", quality_score=0.4, fact_type="mechanism"),
            "F2": Fact(id="F2", claim="higher score", quality_score=0.8, fact_type="mechanism"),
        }
        beat = SimpleNamespace(speaker="expert", move="explain")

        focus = _repair_focus(beat, [], ["F1", "F2"], facts, coverage={}, challenges_left=2)

        self.assertEqual(focus, ["F2"])

    def test_repair_focus_keeps_host_factless(self):
        facts = {"F1": Fact(id="F1", claim="claim", quality_score=0.8)}
        beat = SimpleNamespace(speaker="host", move="react")

        focus = _repair_focus(beat, ["F1"], ["F1"], facts, coverage={}, challenges_left=2)

        self.assertEqual(focus, [])

    def test_repair_focus_replaces_used_low_value_fact_with_better_unused_fact(self):
        facts = {
            "F1": Fact(id="F1", claim="used", quality_score=0.4, fact_type="background"),
            "F2": Fact(id="F2", claim="unused", quality_score=0.7, fact_type="mechanism"),
        }
        beat = SimpleNamespace(speaker="expert", move="explain")

        focus = _repair_focus(beat, ["F1"], ["F1", "F2"], facts, coverage={"F1": 1}, challenges_left=2)

        self.assertEqual(focus, ["F2"])

    def test_repair_focus_prefers_mechanism_over_higher_scored_caveat_for_explain(self):
        facts = {
            "F1": Fact(id="F1", claim="caveat", quality_score=0.9, fact_type="caveat"),
            "F2": Fact(id="F2", claim="mechanism", quality_score=0.7, fact_type="mechanism"),
        }
        beat = SimpleNamespace(speaker="expert", move="explain")

        focus = _repair_focus(beat, [], ["F1", "F2"], facts, coverage={}, challenges_left=2)

        self.assertEqual(focus, ["F2"])

    def test_repair_focus_uses_caveat_for_challenge(self):
        facts = {
            "F1": Fact(id="F1", claim="caveat", quality_score=0.9, fact_type="caveat"),
            "F2": Fact(id="F2", claim="mechanism", quality_score=0.7, fact_type="mechanism"),
        }
        beat = SimpleNamespace(speaker="expert", move="challenge")

        focus = _repair_focus(beat, [], ["F1", "F2"], facts, coverage={}, challenges_left=2)

        self.assertEqual(focus, ["F1"])

    def test_speaker_sequence_opens_body_with_host(self):
        beat = Beat(speaker="expert", move="explain", fact_focus=["F1"], intent="explain", segment_status="continue")
        recent = [Turn(idx=0, speaker="host", text="intro", move="intro"),
                  Turn(idx=1, speaker="expert", text="intro", move="intro")]

        repaired = _repair_speaker_sequence(beat, recent, body_count=0)

        self.assertEqual(repaired.speaker, "host")
        self.assertEqual(repaired.fact_focus, [])
        self.assertEqual(repaired.segment_status, "continue")

    def test_speaker_sequence_replaces_repeated_expert_with_host(self):
        beat = Beat(speaker="expert", move="explain", fact_focus=["F1"], intent="explain", segment_status="continue")
        recent = [Turn(idx=2, speaker="expert", text="previous", move="explain")]

        repaired = _repair_speaker_sequence(beat, recent, body_count=3)

        self.assertEqual(repaired.speaker, "host")
        self.assertEqual(repaired.move, "react")
        self.assertEqual(repaired.fact_focus, [])

    def test_speaker_sequence_replaces_repeated_host_with_expert(self):
        beat = Beat(speaker="host", move="connect", fact_focus=[], intent="connect", segment_status="close")
        recent = [Turn(idx=2, speaker="host", text="previous", move="react")]

        repaired = _repair_speaker_sequence(beat, recent, body_count=3)

        self.assertEqual(repaired.speaker, "expert")
        self.assertEqual(repaired.move, "explain")
        self.assertEqual(repaired.segment_status, "close")

    def test_segment_close_preserves_remaining_turn_budget(self):
        settings = SimpleNamespace(
            min_turns_per_segment=4,
            max_turns_per_segment=5,
            max_total_turns=18,
        )

        self.assertTrue(_can_close_segment(4, 4, 0, 4, settings))
        self.assertTrue(_can_close_segment(4, 8, 1, 4, settings))
        self.assertFalse(_can_close_segment(4, 12, 2, 4, settings))
        self.assertTrue(_can_close_segment(5, 13, 2, 4, settings))
        self.assertFalse(_can_close_segment(4, 17, 3, 4, settings))
        self.assertTrue(_can_close_segment(5, 18, 3, 4, settings))


if __name__ == "__main__":
    unittest.main()
