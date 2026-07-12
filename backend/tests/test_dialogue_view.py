from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.agents.director import Beat
from app.artifacts import Cast, Fact, Persona, Segment, Turn
from app.stages.dialogue import (
    _can_close_segment,
    _fact_card,
    _outro,
    _repair_focus,
    _repair_instruction,
    _repair_speaker_sequence,
    _should_stop_body_after_segment,
    _view,
)


class DummyRun:
    def log(self, **kw):
        pass


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

    def test_fact_card_includes_claim_and_private_evidence(self):
        fact = Fact(
            id="F1",
            claim="The draft model proposes several tokens.",
            source_quotes=["a lightweight draft model proposes a block of candidate tokens"],
            fact_type="mechanism",
            story_role="explain",
        )

        card = _fact_card(fact)

        self.assertIn("F1 [mechanism/explain] CLAIM: The draft model proposes several tokens.", card)
        self.assertIn(
            'EVIDENCE: "a lightweight draft model proposes a block of candidate tokens"',
            card,
        )

    def test_repair_instruction_uses_evidence_cards_as_boundary(self):
        text = _repair_instruction(["target model verifies", "extra unsupported detail"])

        self.assertIn("Rewrite the previous Expert turn using ONLY the FACTS YOU MAY USE", text)
        self.assertIn("Treat each EVIDENCE line as the boundary", text)
        self.assertIn("target model verifies", text)
        self.assertIn("extra unsupported detail", text)

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
            min_total_turns=14,
            target_total_turns=18,
            max_turns_per_segment=5,
            max_total_turns=20,
        )

        self.assertTrue(_can_close_segment(4, 4, 0, 4, settings))
        self.assertTrue(_can_close_segment(4, 8, 1, 4, settings))
        self.assertTrue(_can_close_segment(4, 12, 2, 4, settings))
        self.assertTrue(_can_close_segment(4, 14, 2, 4, settings))
        self.assertTrue(_can_close_segment(4, 15, 3, 4, settings))

    def test_body_can_stop_after_minimum_when_segment_closed(self):
        settings = SimpleNamespace(
            min_total_turns=14,
            target_total_turns=18,
            max_total_turns=20,
        )

        self.assertFalse(_should_stop_body_after_segment(1, 4, 13, settings, True))
        self.assertTrue(_should_stop_body_after_segment(2, 4, 14, settings, True))
        self.assertFalse(_should_stop_body_after_segment(2, 4, 14, settings, False))
        self.assertTrue(_should_stop_body_after_segment(1, 4, 18, settings, False))
        self.assertTrue(_should_stop_body_after_segment(0, 4, 20, settings, False))

    def test_outro_bridges_with_host_after_expert_body_turn(self):
        cast = Cast(
            host=Persona(role="host", name="Alex", background="host", voice="aditya"),
            expert=Persona(role="expert", name="Dr. Rao", background="expert", voice="shubh"),
        )
        recent = [Turn(idx=0, speaker="expert", text="last expert point", move="explain")]
        outline = SimpleNamespace(closing="close well")

        with patch(
            "app.stages.dialogue.speaker.framing_turn",
            side_effect=["host bridge", "expert recap", "host close"],
        ) as framing:
            turns = _outro(object(), cast, outline, recent, DummyRun())

        self.assertEqual([turn.speaker for turn in turns], ["host", "expert", "host"])
        self.assertEqual([turn.text for turn in turns], ["host bridge", "expert recap", "host close"])
        self.assertEqual([call.args[1] for call in framing.call_args_list], ["host", "expert", "host"])

    def test_outro_does_not_repeat_host_when_body_already_ended_on_host(self):
        cast = Cast(
            host=Persona(role="host", name="Alex", background="host", voice="aditya"),
            expert=Persona(role="expert", name="Dr. Rao", background="expert", voice="shubh"),
        )
        recent = [Turn(idx=0, speaker="host", text="last host bridge", move="react")]
        outline = SimpleNamespace(closing="close well")

        with patch(
            "app.stages.dialogue.speaker.framing_turn",
            side_effect=["expert recap", "host close"],
        ) as framing:
            turns = _outro(object(), cast, outline, recent, DummyRun())

        self.assertEqual([turn.speaker for turn in turns], ["expert", "host"])
        self.assertEqual([call.args[1] for call in framing.call_args_list], ["expert", "host"])


if __name__ == "__main__":
    unittest.main()
