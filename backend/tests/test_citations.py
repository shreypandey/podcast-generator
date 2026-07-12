from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.artifacts import Cast, Fact, Persona, Script, Source, Turn
from app.stages import citations


class CitationTranscriptTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "transcript.md"
        self.cast = Cast(
            host=Persona(role="host", name="Host A", background="host", voice="priya"),
            expert=Persona(role="expert", name="Expert B", background="expert", voice="aditya"),
        )
        self.script = Script(turns=[
            Turn(idx=0, speaker="host", text="Welcome.", move="intro"),
            Turn(idx=1, speaker="expert", text="A claim.", move="explain",
                 cited_fact_ids=["F1"], verified=False),
        ])
        self.facts = {"F1": Fact(id="F1", claim="A claim.", source_ids=["S1"])}
        self.sources = {"S1": Source(id="S1", title="Source 1", url="https://example.com")}

    def tearDown(self):
        self.tmp.cleanup()

    def test_public_transcript_hides_citations_sources_and_flags(self):
        citations.write_transcript_md(
            str(self.path), "Topic", self.cast, self.script, self.facts, self.sources,
            include_citations=False, include_sources=False, include_verification_flags=False,
        )

        text = self.path.read_text()

        self.assertIn("**Expert B:** A claim.", text)
        self.assertNotIn("[1]", text)
        self.assertNotIn("_unverified_", text)
        self.assertNotIn("## Sources", text)

    def test_evidence_transcript_keeps_citations_sources_and_flags(self):
        citations.write_transcript_md(str(self.path), "Topic", self.cast, self.script,
                                      self.facts, self.sources)

        text = self.path.read_text()

        self.assertIn("**Expert B:** A claim. [1]  _(unverified)_", text)
        self.assertIn("## Sources", text)
        self.assertIn("[Source 1](https://example.com)", text)


if __name__ == "__main__":
    unittest.main()
