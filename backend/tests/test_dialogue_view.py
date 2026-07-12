from __future__ import annotations

import unittest
from types import SimpleNamespace

from app.artifacts import Fact, Segment
from app.stages.dialogue import _repair_focus, _view


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


if __name__ == "__main__":
    unittest.main()
