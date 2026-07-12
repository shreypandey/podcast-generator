from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.agents import query_planner
from app.artifacts import Brief, QueryPlan, SearchQuery
from app.stages import research


class DummyRun:
    def __init__(self):
        self.events = []

    def log(self, **kw):
        self.events.append(kw)


class FakeExa:
    def __init__(self, results_by_query):
        self.results_by_query = results_by_query

    def search_and_contents(self, query, **kwargs):
        if query == "FAIL":
            raise RuntimeError("search failed")
        results = self.results_by_query.get(query, [])
        return SimpleNamespace(results=results[:kwargs.get("num_results", len(results))])


def result(url, title="", text="text", highlights=None):
    return SimpleNamespace(url=url, title=title, text=text, highlights=highlights or [])


def settings(num_sources=2, num_queries=2):
    return SimpleNamespace(
        num_sources=num_sources,
        max_grounding_sources=num_sources,
        num_queries=num_queries,
    )


class QueryPlannerTests(unittest.TestCase):
    def test_planner_falls_back_when_llm_fails(self):
        run = DummyRun()
        with patch("app.adapters.sarvam_llm.complete_json", side_effect=RuntimeError("bad json")):
            plan = query_planner.plan_queries(object(), "green hydrogen", 3, run)

        self.assertEqual([q.id for q in plan.queries], ["Q1", "Q2", "Q3"])
        self.assertEqual([q.intent for q in plan.queries],
                         ["core_explainer", "primary_official", "caveat_critique"])
        self.assertTrue(any(e.get("kind") == "fallback" for e in run.events))


class ResearchTests(unittest.TestCase):
    def test_dedupe_merges_duplicate_url_and_preserves_query_provenance(self):
        plan = QueryPlan(topic="topic", queries=[
            SearchQuery(id="Q1", intent="core_explainer", query="q1", priority=1),
            SearchQuery(id="Q2", intent="primary_official", query="q2", priority=2),
        ])
        exa = FakeExa({
            "q1": [result("https://example.com/a?utm=1", "A", "short")],
            "q2": [result("https://example.com/a", "A2", "longer text")],
        })

        with patch("app.agents.query_planner.plan_queries", return_value=plan):
            _, corpus = research.run(exa, object(), Brief(topic="topic"), settings(2, 2), DummyRun())

        self.assertEqual(len(corpus.sources), 1)
        self.assertEqual(corpus.sources[0].url, "https://example.com/a")
        self.assertEqual(corpus.sources[0].text, "longer text")
        self.assertEqual(corpus.sources[0].query_ids, ["Q1", "Q2"])
        self.assertEqual(corpus.sources[0].query_intents, ["core_explainer", "primary_official"])

    def test_ranking_prioritizes_query_diversity_before_extra_results(self):
        plan = QueryPlan(topic="topic", queries=[
            SearchQuery(id="Q1", intent="core_explainer", query="q1", priority=1),
            SearchQuery(id="Q2", intent="primary_official", query="q2", priority=2),
        ])
        exa = FakeExa({
            "q1": [
                result("https://example.com/q1-first"),
                result("https://example.com/q1-second"),
            ],
            "q2": [result("https://example.com/q2-first")],
        })

        with patch("app.agents.query_planner.plan_queries", return_value=plan):
            _, corpus = research.run(exa, object(), Brief(topic="topic"), settings(2, 2), DummyRun())

        self.assertEqual([s.url for s in corpus.sources], [
            "https://example.com/q1-first",
            "https://example.com/q2-first",
        ])
        self.assertEqual([s.id for s in corpus.sources], ["S1", "S2"])

    def test_final_source_count_matches_settings_after_overfetch(self):
        plan = QueryPlan(topic="topic", queries=[
            SearchQuery(id="Q1", intent="core_explainer", query="q1", priority=1),
            SearchQuery(id="Q2", intent="primary_official", query="q2", priority=2),
            SearchQuery(id="Q3", intent="caveat_critique", query="q3", priority=3),
            SearchQuery(id="Q4", intent="recent_current", query="q4", priority=4),
        ])
        exa = FakeExa({
            "q1": [result("https://example.com/1a"), result("https://example.com/1b")],
            "q2": [result("https://example.com/2a"), result("https://example.com/2b")],
            "q3": [result("https://example.com/3a"), result("https://example.com/3b")],
            "q4": [result("https://example.com/4a"), result("https://example.com/4b")],
        })

        with patch("app.agents.query_planner.plan_queries", return_value=plan):
            _, corpus = research.run(exa, object(), Brief(topic="topic"), settings(3, 4), DummyRun())

        self.assertEqual(len(corpus.sources), 3)
        self.assertEqual([s.id for s in corpus.sources], ["S1", "S2", "S3"])


if __name__ == "__main__":
    unittest.main()
