from __future__ import annotations

import unittest
from unittest.mock import patch

from app.agents import grounder
from app.artifacts import Fact, FactSheet, Source


class DummyRun:
    def log(self, **kw):
        pass


class GrounderExtractionTests(unittest.TestCase):
    def test_extracts_new_style_fact_labels(self):
        source = Source(id="S1", url="https://example.com", text="source text")
        response = {
            "facts": [
                {"claim": "mRNA is translated by ribosomes.", "fact_type": "mechanism",
                 "story_role": "explain",
                 "source_quotes": ["ribosomes read the mRNA instructions"]},
            ]
        }

        with patch("app.adapters.sarvam_llm.complete_json", return_value=response):
            facts = grounder.extract_facts(object(), source, DummyRun())

        self.assertEqual(len(facts), 1)
        self.assertEqual(facts[0].claim, "mRNA is translated by ribosomes.")
        self.assertEqual(facts[0].source_quotes, ["ribosomes read the mRNA instructions"])
        self.assertEqual(facts[0].fact_type, "mechanism")
        self.assertEqual(facts[0].story_role, "explain")

    def test_extracts_at_most_two_trimmed_quotes(self):
        source = Source(id="S1", url="https://example.com", text="source text")
        long_quote = " ".join(["word"] * 100)
        response = {
            "facts": [
                {"claim": "A supported claim.", "fact_type": "finding",
                 "story_role": "explain",
                 "source_quotes": ["", " first quote ", "   ", long_quote, "third quote"]},
            ]
        }

        with patch("app.adapters.sarvam_llm.complete_json", return_value=response):
            facts = grounder.extract_facts(object(), source, DummyRun())

        self.assertEqual(len(facts[0].source_quotes), 2)
        self.assertEqual(facts[0].source_quotes[0], "first quote")
        self.assertLessEqual(len(facts[0].source_quotes[1]), 300)
        self.assertTrue(facts[0].source_quotes[1].endswith("..."))

    def test_new_style_fact_without_quotes_is_dropped(self):
        source = Source(id="S1", url="https://example.com", text="source text")
        response = {
            "facts": [
                {"claim": "A quote-less claim.", "fact_type": "finding",
                 "story_role": "explain", "source_quotes": []},
            ]
        }

        with patch("app.adapters.sarvam_llm.complete_json", return_value=response):
            facts = grounder.extract_facts(object(), source, DummyRun())

        self.assertEqual(facts, [])

    def test_old_style_claims_fallback(self):
        source = Source(id="S1", url="https://example.com", text="source text")

        with patch("app.adapters.sarvam_llm.complete_json", return_value={"claims": ["A supported claim."]}):
            facts = grounder.extract_facts(object(), source, DummyRun())

        self.assertEqual(len(facts), 1)
        self.assertEqual(facts[0].claim, "A supported claim.")
        self.assertEqual(facts[0].source_quotes, [])
        self.assertEqual(facts[0].fact_type, "background")
        self.assertEqual(facts[0].story_role, "explain")

    def test_invalid_labels_normalize_to_safe_defaults(self):
        source = Source(id="S1", url="https://example.com", text="source text")
        response = {
            "facts": [
                {"claim": "A limitation exists.", "fact_type": "limitation",
                 "story_role": "debate", "source_quotes": ["limitation quote"]},
                {"claim": "A caveat exists.", "fact_type": "caveat",
                 "story_role": "debate", "source_quotes": ["caveat quote"]},
            ]
        }

        with patch("app.adapters.sarvam_llm.complete_json", return_value=response):
            facts = grounder.extract_facts(object(), source, DummyRun())

        self.assertEqual((facts[0].fact_type, facts[0].story_role), ("background", "context"))
        self.assertEqual((facts[1].fact_type, facts[1].story_role), ("caveat", "challenge"))

    def test_caveat_and_counterclaim_force_challenge_role(self):
        source = Source(id="S1", url="https://example.com", text="source text")
        response = {
            "facts": [
                {"claim": "A caveat exists.", "fact_type": "caveat",
                 "story_role": "context", "source_quotes": ["caveat quote"]},
                {"claim": "A counterclaim exists.", "fact_type": "counterclaim",
                 "story_role": "explain", "source_quotes": ["counterclaim quote"]},
            ]
        }

        with patch("app.adapters.sarvam_llm.complete_json", return_value=response):
            facts = grounder.extract_facts(object(), source, DummyRun())

        self.assertEqual([f.story_role for f in facts], ["challenge", "challenge"])


class GrounderVerificationTests(unittest.TestCase):
    def test_verify_turn_includes_quote_evidence(self):
        factsheet = FactSheet(facts=[
            Fact(
                id="F1",
                claim="mRNA vaccines instruct cells to make spike protein.",
                source_quotes=["mRNA created in a laboratory teaches cells how to make a protein"],
                fact_type="mechanism",
                story_role="explain",
                quality_score=0.81,
            )
        ])

        with patch("app.adapters.sarvam_llm.complete_json",
                   return_value={"supported": True, "unsupported_claims": []}) as complete:
            ok, unsupported = grounder.verify_turn(object(), "The vaccine gives cells instructions.",
                                                   factsheet, DummyRun())

        self.assertTrue(ok)
        self.assertEqual(unsupported, [])
        system = complete.call_args.args[1]
        user = complete.call_args.args[2]
        self.assertIn("quote as controlling", system)
        self.assertIn("F1 [mechanism/explain] score=0.81", user)
        self.assertIn('quote: "mRNA created in a laboratory teaches cells how to make a protein"', user)

    def test_verify_turn_returns_unsupported_claims(self):
        factsheet = FactSheet(facts=[
            Fact(id="F1", claim="A supported claim.", source_quotes=["A supported claim."]),
        ])

        with patch("app.adapters.sarvam_llm.complete_json",
                   return_value={"supported": False, "unsupported_claims": ["extra detail"]}):
            ok, unsupported = grounder.verify_turn(object(), "A supported claim plus extra detail.",
                                                   factsheet, DummyRun())

        self.assertFalse(ok)
        self.assertEqual(unsupported, ["extra detail"])

    def test_verify_turn_can_limit_to_cited_fact_ids(self):
        factsheet = FactSheet(facts=[
            Fact(id="F1", claim="First claim.", source_quotes=["First quote."]),
            Fact(id="F2", claim="Second claim.", source_quotes=["Second quote."]),
        ])

        with patch("app.adapters.sarvam_llm.complete_json",
                   return_value={"supported": True, "unsupported_claims": []}) as complete:
            grounder.verify_turn(object(), "Second claim.", factsheet, DummyRun(), cited_fact_ids=["F2"])

        user = complete.call_args.args[2]
        self.assertNotIn("F1", user)
        self.assertIn("F2", user)

    def test_verify_turn_empty_cited_fact_ids_does_not_expand_to_all_facts(self):
        factsheet = FactSheet(facts=[
            Fact(id="F1", claim="First claim.", source_quotes=["First quote."]),
        ])

        with patch("app.adapters.sarvam_llm.complete_json",
                   return_value={"supported": True, "unsupported_claims": []}) as complete:
            grounder.verify_turn(object(), "General framing.", factsheet, DummyRun(),
                                 cited_fact_ids=[])

        user = complete.call_args.args[2]
        self.assertIn("KNOWN FACTS:\n  (none)", user)
        self.assertNotIn("F1", user)

    def test_verify_turn_accepts_and_flags_verifier_failure(self):
        factsheet = FactSheet(facts=[
            Fact(id="F1", claim="A supported claim.", source_quotes=["A supported claim."]),
        ])

        with patch("app.adapters.sarvam_llm.complete_json", side_effect=ValueError("empty")):
            ok, unsupported = grounder.verify_turn(object(), "A supported claim.", factsheet, DummyRun())

        self.assertFalse(ok)
        self.assertIn("verifier error", unsupported[0])


class GrounderAnnotationTests(unittest.TestCase):
    def test_annotate_tension_falls_back_on_bad_json(self):
        factsheet = FactSheet(facts=[
            Fact(id="F1", claim="A supported claim."),
            Fact(id="F2", claim="Another supported claim."),
        ])

        with patch("app.adapters.sarvam_llm.complete_json", side_effect=ValueError("bad json")):
            out = grounder.annotate_tension(object(), factsheet, DummyRun())

        self.assertEqual(out.facts[0].evidence_strength, "moderate")
        self.assertEqual(out.facts[0].conflicts_with, [])
        self.assertEqual(out.facts[0].tension_type, "none")


if __name__ == "__main__":
    unittest.main()
