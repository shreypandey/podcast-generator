from __future__ import annotations

import json
import os
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import config, db
from app.main import app


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_db = config.DATABASE_PATH
        self.old_runs = config.RUNS_DIR
        config.DATABASE_PATH = f"{self.tmp.name}/app.db"
        config.RUNS_DIR = f"{self.tmp.name}/runs"
        db.init_db()
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()
        config.DATABASE_PATH = self.old_db
        config.RUNS_DIR = self.old_runs
        self.tmp.cleanup()

    def test_health(self):
        res = self.client.get("/api/health")

        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json(), {"status": "healthy"})

    def test_create_run_returns_accepted_shape_without_running_pipeline(self):
        with patch("app.main.jobs.create_run", return_value={"run_id": "R1", "status": "queued"}):
            res = self.client.post("/api/runs", json={
                "topic": "test topic",
                "length": "short",
                "depth": 1,
                "languages": ["en-IN"],
            })

        self.assertEqual(res.status_code, 202)
        self.assertEqual(res.json()["run_id"], "R1")
        self.assertEqual(res.json()["status_url"], "/api/runs/R1")

    def test_create_run_forwards_steering_fields(self):
        with patch("app.main.jobs.create_run", return_value={"run_id": "R1", "status": "queued"}) as create:
            res = self.client.post("/api/runs", json={
                "topic": "test topic",
                "angle": "myth-busting",
                "focus_questions": ["Does it change DNA?"],
                "custom_angle": "use consensus sources",
                "tone": "investigative",
                "style": "news-analysis",
                "custom_style": "crisp",
            })

        self.assertEqual(res.status_code, 202)
        kwargs = create.call_args.kwargs
        self.assertEqual(kwargs["angle"], "myth-busting")
        self.assertEqual(kwargs["focus_questions"], ["Does it change DNA?"])
        self.assertEqual(kwargs["custom_angle"], "use consensus sources")
        self.assertEqual(kwargs["tone"], "investigative")
        self.assertEqual(kwargs["style"], "news-analysis")
        self.assertEqual(kwargs["custom_style"], "crisp")

    def test_get_run_includes_language_and_artifact_state(self):
        db.insert_run("R1", "test topic", "short", 1, ["en-IN", "hi-IN"])

        res = self.client.get("/api/runs/R1")

        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertEqual(body["languages"]["requested"], ["en-IN", "hi-IN"])
        self.assertEqual(body["languages"]["ready"], [])
        self.assertIsNone(body["artifacts"]["audio_url"])

    def test_audio_not_ready_returns_structured_409(self):
        db.insert_run("R1", "test topic", "short", 1, ["en-IN"])

        res = self.client.get("/api/runs/R1/audio?lang=en-IN")

        self.assertEqual(res.status_code, 409)
        self.assertEqual(res.json()["error"]["code"], "audio_not_ready")

    def test_transcript_response_includes_spoken_verified_and_citation_quotes(self):
        db.insert_run("R1", "test topic", "short", 1, ["en-IN"])
        self._write("R1", "cast", {
            "host": {"name": "Host A", "background": "host"},
            "expert": {"name": "Expert B", "background": "expert"},
        })
        self._write("R1", "source", {
            "sources": [{"id": "S1", "title": "Source 1", "url": "https://example.com"}],
        })
        self._write("R1", "factsheet", {
            "facts": [{"id": "F1", "claim": "A claim.", "source_ids": ["S1"],
                       "source_quotes": ["exact supporting quote"]}],
        })
        self._write("R1", "script", {
            "turns": [
                {"idx": 0, "speaker": "expert", "text": "A claim.", "spoken": "",
                 "move": "explain", "cited_fact_ids": ["F1"], "verified": False},
            ],
        })
        self._write("R1", "episode_en-IN", {
            "language": "en-IN",
            "audio_path": "episode_en-IN.wav",
            "transcript": [],
            "deliveries": ["A spoken claim."],
            "sources": [],
        })

        res = self.client.get("/api/runs/R1/transcript?lang=en-IN")

        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertEqual(body["turns"][0]["spoken"], "A spoken claim.")
        self.assertFalse(body["turns"][0]["verified"])
        self.assertEqual(body["turns"][0]["citation_numbers"], [1])
        self.assertEqual(body["citations"][0]["quote"], "exact supporting quote")

    def _write(self, run_id: str, name: str, value: dict):
        run_dir = os.path.join(config.RUNS_DIR, run_id)
        os.makedirs(run_dir, exist_ok=True)
        with open(os.path.join(run_dir, f"{name}.json"), "w") as f:
            json.dump(value, f)


if __name__ == "__main__":
    unittest.main()
