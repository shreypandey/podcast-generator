from __future__ import annotations

import tempfile
import unittest

from app import config, db, jobs


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


if __name__ == "__main__":
    unittest.main()
