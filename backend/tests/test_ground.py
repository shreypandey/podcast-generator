from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.artifacts import Fact, Source, SourceCorpus
from app.stages import ground
from app.stages.ground import _reduce_facts, _score_facts


def fact(source_id: str, n: int, fact_type: str = "background") -> Fact:
    return Fact(id="", claim=f"{source_id} claim {n}", source_ids=[source_id], fact_type=fact_type)


def quoted_fact(source_id: str, claim: str, fact_type: str = "finding") -> Fact:
    return Fact(id="", claim=claim, source_ids=[source_id], fact_type=fact_type,
                source_quotes=[claim])


class GroundReduceTests(unittest.TestCase):
    def test_reduce_keeps_later_sources_before_filling_budget(self):
        corpus = SourceCorpus(sources=[
            Source(id="S1", url="https://one.test", query_intents=["core_explainer"]),
            Source(id="S2", url="https://two.test", query_intents=["primary_official"]),
            Source(id="S3", url="https://three.test", query_intents=["caveat_critique"]),
            Source(id="S4", url="https://four.test", query_intents=["recent_current"]),
        ])
        facts = (
            [fact("S1", i) for i in range(1, 7)]
            + [fact("S2", i) for i in range(1, 4)]
            + [fact("S3", i) for i in range(1, 3)]
            + [fact("S4", i) for i in range(1, 3)]
        )

        reduced = _reduce_facts(facts, corpus, max_facts=6)
        source_ids = [f.source_ids[0] for f in reduced]

        self.assertIn("S3", source_ids)
        self.assertIn("S4", source_ids)
        self.assertEqual(len(reduced), 6)
        self.assertGreaterEqual(len(set(source_ids)), 4)

    def test_reduce_prioritizes_caveat_and_recent_second_pass(self):
        corpus = SourceCorpus(sources=[
            Source(id="S1", url="https://one.test", query_intents=["core_explainer"]),
            Source(id="S2", url="https://two.test", query_intents=["primary_official"]),
            Source(id="S3", url="https://three.test", query_intents=["caveat_critique"]),
            Source(id="S4", url="https://four.test", query_intents=["recent_current"]),
        ])
        facts = [fact(sid, i) for sid in ("S1", "S2", "S3", "S4") for i in range(1, 4)]

        reduced = _reduce_facts(facts, corpus, max_facts=6)
        source_ids = [f.source_ids[0] for f in reduced]

        self.assertEqual(source_ids[:4], ["S1", "S2", "S3", "S4"])
        self.assertEqual(source_ids[4:6], ["S3", "S4"])

    def test_reduce_uses_best_fact_per_source_before_filling(self):
        corpus = SourceCorpus(sources=[
            Source(id="S1", url="https://one.test", query_intents=["core_explainer"]),
            Source(id="S2", url="https://two.test", query_intents=["caveat_critique"]),
            Source(id="S3", url="https://three.test", query_intents=["recent_current"]),
        ])
        facts = [
            fact("S1", 1, "background"),
            fact("S1", 2, "caveat"),
            fact("S2", 1, "background"),
            fact("S2", 2, "background"),
            fact("S3", 1, "background"),
            fact("S3", 2, "background"),
        ]

        reduced = _reduce_facts(facts, corpus, max_facts=4)

        self.assertEqual([f.source_ids[0] for f in reduced[:3]], ["S1", "S2", "S3"])
        self.assertEqual(reduced[0].source_ids[0], "S1")
        self.assertEqual(reduced[0].fact_type, "caveat")

    def test_score_boosts_quoted_substantive_fact_over_background(self):
        corpus = SourceCorpus(sources=[
            Source(id="S1", url="https://www.cdc.gov/example", query_intents=["primary_official"], search_rank=1),
        ])
        mechanism = quoted_fact("S1", "mRNA vaccines instruct cells to make spike protein.", "mechanism")
        background = Fact(id="", claim="This article provides information.", source_ids=["S1"],
                          fact_type="background", source_quotes=["This article provides information."])

        _score_facts([mechanism, background], corpus)

        self.assertGreater(mechanism.quality_score, background.quality_score)
        self.assertIn("quoted evidence", mechanism.quality_notes)

    def test_score_boosts_credible_source_domain(self):
        credible = SourceCorpus(sources=[
            Source(id="S1", url="https://www.nih.gov/news", query_intents=["primary_official"], search_rank=1),
        ])
        unclear = SourceCorpus(sources=[
            Source(id="S1", url="https://random-blog.example/post", query_intents=["primary_official"], search_rank=1),
        ])
        credible_fact = quoted_fact("S1", "Researchers identified a measurable immune response.", "finding")
        unclear_fact = quoted_fact("S1", "Researchers identified a measurable immune response.", "finding")

        _score_facts([credible_fact], credible)
        _score_facts([unclear_fact], unclear)

        self.assertGreater(credible_fact.quality_score, unclear_fact.quality_score)
        self.assertIn("credible source domain", credible_fact.quality_notes)

    def test_score_does_not_treat_foreign_edu_subdomain_as_credible_by_substring(self):
        corpus = SourceCorpus(sources=[
            Source(id="S1", url="https://www.qwe.edu.pl/tutorial",
                   query_intents=["core_explainer"], search_rank=1),
        ])
        fact = quoted_fact("S1", "Speculative decoding uses a draft model.", "mechanism")

        _score_facts([fact], corpus)

        self.assertIn("unscored source domain", fact.quality_notes)
        self.assertNotIn("credible source domain", fact.quality_notes)

    def test_score_calibration_does_not_saturate_authoritative_facts(self):
        corpus = SourceCorpus(sources=[
            Source(id="S1", url="https://www.cdc.gov/example",
                   query_intents=["primary_official"], search_rank=1),
        ])
        mechanism = quoted_fact("S1", "mRNA vaccines instruct cells to make spike protein.", "mechanism")
        caveat = quoted_fact("S1", "It takes a few weeks for immune cells to develop.", "caveat")

        _score_facts([mechanism, caveat], corpus)

        self.assertLess(mechanism.quality_score, 1.0)
        self.assertLess(caveat.quality_score, 1.0)
        self.assertGreater(caveat.quality_score, mechanism.quality_score)

    def test_score_penalizes_generic_methodology_claims(self):
        corpus = SourceCorpus(sources=[
            Source(id="S1", url="https://www.nih.gov/news", query_intents=["primary_official"], search_rank=1),
        ])
        useful = quoted_fact("S1", "The vaccine induced neutralizing antibody responses in participants.", "finding")
        generic = quoted_fact("S1", "This study used PubMed to search for articles.", "finding")

        _score_facts([useful, generic], corpus)

        self.assertGreater(useful.quality_score, generic.quality_score)
        self.assertTrue(any("generic" in note for note in generic.quality_notes))

    def test_score_penalizes_near_duplicate_claims(self):
        corpus = SourceCorpus(sources=[
            Source(id="S1", url="https://random-blog.example/post", query_intents=["core_explainer"], search_rank=5),
        ])
        first = quoted_fact("S1", "mRNA vaccines instruct cells to make spike protein.", "mechanism")
        duplicate = quoted_fact("S1", "mRNA vaccines instruct cells to make spike protein.", "mechanism")

        _score_facts([first, duplicate], corpus)

        self.assertGreater(first.quality_score, duplicate.quality_score)
        self.assertIn("near-duplicate claim", duplicate.quality_notes)

    def test_reduce_keeps_source_coverage_before_quality_fill(self):
        corpus = SourceCorpus(sources=[
            Source(id="S1", url="https://one.test"),
            Source(id="S2", url="https://two.test"),
        ])
        high_quality = quoted_fact("S1", "A high quality caveat exists.", "caveat")
        high_quality.quality_score = 1.0
        low_quality = quoted_fact("S2", "A lower quality background claim exists.", "background")
        low_quality.quality_score = 0.1
        extra = quoted_fact("S1", "Another high quality mechanism exists.", "mechanism")
        extra.quality_score = 0.9

        reduced = _reduce_facts([high_quality, extra, low_quality], corpus, max_facts=2)

        self.assertEqual([f.source_ids[0] for f in reduced], ["S1", "S2"])

    def test_reduce_quality_fill_prefers_higher_score(self):
        corpus = SourceCorpus(sources=[
            Source(id="S1", url="https://one.test"),
            Source(id="S2", url="https://two.test"),
        ])
        s1_first = quoted_fact("S1", "Source one coverage fact.", "background")
        s1_first.quality_score = 0.9
        s2_first = quoted_fact("S2", "Source two coverage fact.", "background")
        s2_first.quality_score = 0.85
        low_extra = quoted_fact("S1", "Low quality extra.", "background")
        low_extra.quality_score = 0.3
        high_extra = quoted_fact("S2", "High quality caveat.", "caveat")
        high_extra.quality_score = 0.6

        reduced = _reduce_facts([s1_first, low_extra, s2_first, high_extra], corpus, max_facts=3)

        self.assertIs(reduced[2], high_extra)


class DummyRun:
    def __init__(self):
        self.events = []

    def log(self, **kw):
        self.events.append(kw)


class GroundRunTests(unittest.TestCase):
    def test_parallel_grounding_preserves_source_order(self):
        corpus = SourceCorpus(sources=[
            Source(id="S1", url="https://one.test"),
            Source(id="S2", url="https://two.test"),
            Source(id="S3", url="https://three.test"),
        ])

        def fake_extract(_client, source, _run):
            return [fact(source.id, 1)]

        with patch("app.agents.grounder.extract_facts", side_effect=fake_extract), \
                patch("app.agents.grounder.annotate_tension", side_effect=lambda _client, fs, _run: fs):
            factsheet = ground.run(object(), corpus, SimpleNamespace(max_facts=10), DummyRun())

        self.assertEqual([f.source_ids[0] for f in factsheet.facts], ["S1", "S2", "S3"])
        self.assertEqual([f.id for f in factsheet.facts], ["F1", "F2", "F3"])

    def test_parallel_grounding_tolerates_one_source_failure(self):
        corpus = SourceCorpus(sources=[
            Source(id="S1", url="https://one.test"),
            Source(id="S2", url="https://two.test"),
        ])
        run = DummyRun()

        def fake_extract(_client, source, _run):
            if source.id == "S1":
                raise RuntimeError("boom")
            return [fact(source.id, 1)]

        with patch("app.agents.grounder.extract_facts", side_effect=fake_extract), \
                patch("app.agents.grounder.annotate_tension", side_effect=lambda _client, fs, _run: fs):
            factsheet = ground.run(object(), corpus, SimpleNamespace(max_facts=10), run)

        self.assertEqual([f.source_ids[0] for f in factsheet.facts], ["S2"])
        self.assertTrue(any(e.get("kind") == "source_error" and e.get("source_id") == "S1"
                            for e in run.events))


if __name__ == "__main__":
    unittest.main()
