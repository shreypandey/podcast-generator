from __future__ import annotations

import json
import os
import tempfile
import unittest
import wave

from app import config, db, jobs
from app.artifacts import Episode


class JobRunnerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_db = config.DATABASE_PATH
        self.old_runs = config.RUNS_DIR
        config.DATABASE_PATH = f"{self.tmp.name}/app.db"
        config.RUNS_DIR = f"{self.tmp.name}/runs"
        db.init_db()

    def tearDown(self):
        config.DATABASE_PATH = self.old_db
        config.RUNS_DIR = self.old_runs
        self.tmp.cleanup()

    def test_run_job_succeeds_and_stores_pipeline_events(self):
        run = jobs.create_run("test topic", length="short", depth=1,
                              languages=["en-IN"], enqueue=False)

        def fake_pipeline(_topic, **kwargs):
            kwargs["event_sink"]({"stage": "research", "kind": "fake", "sources_found": 2})
            return "episode.wav"

        final = jobs.run_job(run["run_id"], pipeline=fake_pipeline)
        events = db.list_events(run["run_id"])

        self.assertEqual(final["status"], "succeeded")
        self.assertTrue(any(e["kind"] == "fake" and e["stage"] == "research" for e in events))
        self.assertTrue(any(e["kind"] == "run.succeeded" for e in events))

    def test_steering_is_normalized_and_forwarded_to_pipeline(self):
        run = jobs.create_run(
            "test topic",
            angle="myth-busting",
            focus_questions=["  Does it change DNA?  "],
            custom_angle="  use consensus sources  ",
            tone="ENERGETIC",
            style="news-analysis",
            custom_style="  crisp  ",
            enqueue=False,
        )
        captured = {}

        def fake_pipeline(_topic, **kwargs):
            captured.update(kwargs)
            return "episode.wav"

        final = jobs.run_job(run["run_id"], pipeline=fake_pipeline)

        self.assertEqual(final["status"], "succeeded")
        self.assertEqual(run["steering"]["angle"], "mythbusting")
        self.assertEqual(run["steering"]["focus_questions"], ["Does it change DNA?"])
        self.assertEqual(run["steering"]["custom_angle"], "use consensus sources")
        self.assertEqual(run["steering"]["tone"], "energetic")
        self.assertEqual(run["steering"]["style"], "news_analysis")
        self.assertEqual(run["steering"]["custom_style"], "crisp")
        self.assertEqual(captured["angle"], "mythbusting")
        self.assertEqual(captured["style"], "news_analysis")

    def test_run_job_marks_failure_without_raising(self):
        run = jobs.create_run("test topic", enqueue=False)

        def fake_pipeline(_topic, **_kwargs):
            raise RuntimeError("boom")

        final = jobs.run_job(run["run_id"], pipeline=fake_pipeline)

        self.assertEqual(final["status"], "failed")
        self.assertIn("boom", final["error"])

    def test_cancel_before_run_marks_canceled(self):
        run = jobs.create_run("test topic", enqueue=False)
        db.request_cancel(run["run_id"])

        final = jobs.run_job(run["run_id"], pipeline=lambda *_args, **_kwargs: "never")

        self.assertEqual(final["status"], "canceled")

    def test_language_validation_rejects_unknown_code(self):
        with self.assertRaises(ValueError):
            jobs.create_run("test topic", languages=["xx-YY"], enqueue=False)

    def test_executor_parallelism_tracks_config(self):
        self.assertEqual(jobs._executor._max_workers, config.MAX_CONCURRENT_JOBS)

    def test_request_language_render_appends_metadata_and_writes_episode(self):
        db.insert_run("R1", "test topic", "short", 1, ["en-IN"])
        self._write_render_artifacts("R1")

        def fake_renderer(_client, script, _cast, run, languages, _settings):
            episodes = []
            for lang in languages:
                audio_path = os.path.join(run.dir, f"episode_{lang}.wav")
                self._write_wav(audio_path)
                episodes.append(Episode(language=lang, audio_path=audio_path,
                                        transcript=script.turns, deliveries=["spoken"]))
            return episodes

        result = jobs.request_language_render(
            "R1",
            ["hi-IN"],
            enqueue=False,
            client_factory=lambda: object(),
            renderer=fake_renderer,
        )

        self.assertEqual(result["queued"], ["hi-IN"])
        self.assertEqual(db.get_run("R1")["languages"], ["en-IN", "hi-IN"])
        self.assertTrue(jobs.is_language_ready("R1", "hi-IN"))
        events = db.list_events("R1")
        self.assertTrue(any(e["kind"] == "language_render.succeeded" for e in events))

    def test_request_language_render_skips_ready_language(self):
        db.insert_run("R1", "test topic", "short", 1, ["en-IN"])
        self._write_render_artifacts("R1")
        self._write("R1", "episode_hi-IN", {
            "language": "hi-IN",
            "audio_path": os.path.join(config.RUNS_DIR, "R1", "episode_hi-IN.wav"),
            "transcript": [],
            "deliveries": [],
            "sources": [],
        })
        self._write_wav(os.path.join(config.RUNS_DIR, "R1", "episode_hi-IN.wav"))

        result = jobs.request_language_render("R1", ["hi-IN"], enqueue=False)

        self.assertEqual(result["queued"], [])
        self.assertEqual(db.get_run("R1")["languages"], ["en-IN", "hi-IN"])

    def test_request_language_render_requires_base_artifacts(self):
        db.insert_run("R1", "test topic", "short", 1, ["en-IN"])

        with self.assertRaises(jobs.RenderArtifactsNotReady):
            jobs.request_language_render("R1", ["hi-IN"], enqueue=False)

        self.assertEqual(db.get_run("R1")["languages"], ["en-IN"])

    def _write_render_artifacts(self, run_id: str):
        self._write(run_id, "brief", {
            "topic": "test topic",
            "length": "short",
            "depth": 1,
            "languages": ["en-IN"],
        })
        self._write(run_id, "script", {
            "turns": [
                {"idx": 0, "speaker": "host", "text": "Hello", "move": "intro",
                 "cited_fact_ids": [], "verified": True, "spoken": "Hello", "pace": 1.0},
            ],
        })
        self._write(run_id, "cast", {
            "host": {"role": "host", "name": "Host A", "background": "host", "voice": "priya"},
            "expert": {"role": "expert", "name": "Expert B", "background": "expert", "voice": "aditya"},
        })
        self._write(run_id, "factsheet", {"facts": []})
        self._write(run_id, "source", {"sources": []})
        self._write(run_id, "manifest", {"run_id": run_id, "events": []})

    def _write(self, run_id: str, name: str, value: dict):
        run_dir = os.path.join(config.RUNS_DIR, run_id)
        os.makedirs(run_dir, exist_ok=True)
        with open(os.path.join(run_dir, f"{name}.json"), "w") as f:
            json.dump(value, f)

    def _write_wav(self, path: str):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with wave.open(path, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(8000)
            wav.writeframes(b"\x00\x00" * 8)


if __name__ == "__main__":
    unittest.main()
