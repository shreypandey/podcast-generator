from __future__ import annotations

import json
import os
import tempfile
import unittest
import wave
from pathlib import Path

from app import config
from app import evals


class EvalHarnessTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_runs = config.RUNS_DIR
        config.RUNS_DIR = f"{self.tmp.name}/runs"
        os.makedirs(config.RUNS_DIR, exist_ok=True)

    def tearDown(self):
        config.RUNS_DIR = self.old_runs
        self.tmp.cleanup()

    def test_native_script_stats_detects_devanagari_vs_latin(self):
        native = evals._native_script_stats("यह हिंदी वाक्य है", "hi-IN")
        latin = evals._native_script_stats("yeh hindi sentence hai", "hi-IN")

        self.assertGreater(native["native_ratio"], 0.8)
        self.assertGreater(latin["latin_ratio"], 0.8)

    def test_analyze_english_run_scores_artifacts_and_role_warnings(self):
        run_id = "R1"
        run_dir = Path(config.RUNS_DIR) / run_id
        run_dir.mkdir(parents=True)
        self._write(run_dir, "brief", {"topic": "topic", "angle": "balanced"})
        self._write(run_dir, "query_plan", {"queries": [{"id": "Q1", "intent": "core_explainer"}]})
        self._write(run_dir, "source", {"sources": [
            {"id": "S1", "url": "https://example.com/1", "query_intents": ["core_explainer"]},
            {"id": "S2", "url": "https://example.com/2", "query_intents": ["caveat_critique"]},
            {"id": "S3", "url": "https://example.com/3", "query_intents": ["recent_current"]},
            {"id": "S4", "url": "https://example.com/4", "query_intents": ["example_case"]},
        ]})
        self._write(run_dir, "factsheet", {"facts": [
            {"id": "F1", "claim": "A supported mechanism.", "source_ids": ["S1"], "fact_type": "mechanism"},
            {"id": "F2", "claim": "A supported caveat.", "source_ids": ["S2"], "fact_type": "caveat"},
            {"id": "F3", "claim": "Another fact.", "source_ids": ["S3"], "fact_type": "finding"},
            {"id": "F4", "claim": "An example.", "source_ids": ["S4"], "fact_type": "example"},
            {"id": "F5", "claim": "Extra.", "source_ids": ["S1"], "fact_type": "stat"},
            {"id": "F6", "claim": "Extra.", "source_ids": ["S2"], "fact_type": "finding"},
            {"id": "F7", "claim": "Extra.", "source_ids": ["S3"], "fact_type": "mechanism"},
            {"id": "F8", "claim": "Extra.", "source_ids": ["S4"], "fact_type": "background"},
        ]})
        self._write(run_dir, "cast", {"host": {"name": "Host"}, "expert": {"name": "Expert"}})
        self._write(run_dir, "outline", {"segments": []})
        self._write(run_dir, "script", {"turns": [
            {"idx": 0, "speaker": "host", "move": "intro", "text": "Welcome.", "cited_fact_ids": []},
            {"idx": 1, "speaker": "expert", "move": "explain", "text": "A supported mechanism.", "cited_fact_ids": ["F1"], "verified": True},
            {"idx": 2, "speaker": "host", "move": "challenge", "text": "But what about the caveat?", "cited_fact_ids": ["F2"], "verified": True},
            {"idx": 3, "speaker": "expert", "move": "explain", "text": "This answer asks a question?", "cited_fact_ids": ["F2"], "verified": False},
        ]})
        self._write(run_dir, "episode_en-IN", {"language": "en-IN", "deliveries": ["a", "b", "c", "d"]})
        self._write(run_dir, "manifest", {"events": []})
        (run_dir / "transcript_en-IN.md").write_text("**Expert:** text [1]\n", encoding="utf-8")
        self._write_wav(run_dir / "episode_en-IN.wav")

        row = evals.analyze_english_run({
            "topic_id": "topic",
            "topic": "topic",
            "run_id": run_id,
            "english_status": "succeeded",
            "angle": "balanced",
        })

        self.assertIn("host has cited facts", row["warnings"])
        self.assertIn("expert asks questions", row["warnings"])
        self.assertIn("unverified turns present", row["warnings"])
        self.assertLess(row["score"], 100)

    def _write(self, run_dir: Path, name: str, value: dict):
        (run_dir / f"{name}.json").write_text(json.dumps(value), encoding="utf-8")

    def _write_wav(self, path: Path):
        with wave.open(str(path), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(22050)
            wav.writeframes(b"\x00\x00" * 22050)


if __name__ == "__main__":
    unittest.main()
