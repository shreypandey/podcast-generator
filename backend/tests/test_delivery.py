from __future__ import annotations

import os
import tempfile
import unittest
from unittest.mock import patch

from app.artifacts import Cast, Persona, Script, Turn
from app.stages import delivery, render


class DummyRun:
    def __init__(self, path: str):
        self.dir = path
        self.artifacts = {}
        self.events = []

    def save_artifact(self, name, model):
        self.artifacts[name] = model

    def log(self, **kw):
        self.events.append(kw)


class DeliveryPlannerTests(unittest.TestCase):
    def test_splits_dense_turn_and_keeps_delivery_text(self):
        text = (
            "The simple version is this: attention lets the model compare words across the "
            "sentence, then it gives stronger weight to the words that matter for the next "
            "prediction."
        )
        turn = Turn(idx=3, speaker="expert", text=text, move="explain", pace=1.0)

        plan = delivery.plan_turn_delivery(turn, text, 1.0)

        self.assertGreater(len(plan.phrases), 1)
        self.assertEqual(plan.delivery_text, text)
        self.assertTrue(all(phrase.text for phrase in plan.phrases))
        self.assertLessEqual(plan.phrases[0].pace, 0.94)
        self.assertGreaterEqual(plan.phrases[0].pause_after_ms, 400)

    def test_host_question_is_slightly_quicker_than_expert_definition(self):
        host = Turn(idx=4, speaker="host", text="Wait, what does that mean?", move="react", pace=1.0)
        expert = Turn(
            idx=5,
            speaker="expert",
            text="In plain language, a token is a small chunk of text.",
            move="explain",
            pace=1.0,
        )

        host_plan = delivery.plan_turn_delivery(host, host.text, 1.0)
        expert_plan = delivery.plan_turn_delivery(expert, expert.text, 1.0)

        self.assertGreater(host_plan.phrases[0].pace, expert_plan.phrases[0].pace)


class PhraseRenderTests(unittest.TestCase):
    def test_render_uses_phrase_plan_and_writes_artifact(self):
        script = Script(turns=[
            Turn(idx=0, speaker="host", text="Wait, what does that mean?", move="react", pace=1.0),
            Turn(
                idx=1,
                speaker="expert",
                text="The simple version is this: attention chooses the earlier words that matter.",
                move="explain",
                spoken="The simple version is this: attention chooses the earlier words that matter.",
                pace=1.0,
            ),
        ])
        cast = Cast(
            host=Persona(role="host", name="Host", background="host", voice="aditya"),
            expert=Persona(role="expert", name="Expert", background="expert", voice="shubh"),
        )
        calls = []

        def fake_synth(_client, text, speaker, _run, pace=None, lang=None):
            calls.append({"text": text, "speaker": speaker, "pace": pace, "lang": lang})
            return [f"audio:{len(calls)}"]

        def fake_combine(timeline, out_path):
            self.assertEqual(len(timeline), 2)
            self.assertGreater(sum(len(turn) for turn in timeline), 2)
            with open(out_path, "wb") as f:
                f.write(b"wav")
            return out_path

        with tempfile.TemporaryDirectory() as tmp:
            run = DummyRun(tmp)
            with patch("app.adapters.sarvam_tts.synth", side_effect=fake_synth), \
                    patch("app.adapters.sarvam_tts.combine_phrase_timeline_to_wav",
                          side_effect=fake_combine):
                episodes = render.run(object(), script, cast, run, ["en-IN"])

            self.assertTrue(os.path.exists(os.path.join(tmp, "episode_en-IN.wav")))
            self.assertIn("delivery_plan_en-IN", run.artifacts)
            self.assertEqual(len(episodes[0].delivery_plan), 2)
            self.assertGreater(len(calls), len(script.turns))

    def test_render_can_use_llm_localization_for_non_english(self):
        script = Script(turns=[
            Turn(idx=0, speaker="host", text="What is an mRNA vaccine?", move="ask", pace=1.0),
        ])
        cast = Cast(
            host=Persona(role="host", name="Host", background="host", voice="aditya"),
            expert=Persona(role="expert", name="Expert", background="expert", voice="shubh"),
        )

        def fake_synth(_client, text, speaker, _run, pace=None, lang=None):
            self.assertIn("वैक्सीन", text)
            self.assertEqual(lang, "hi-IN")
            return ["audio"]

        def fake_combine(_timeline, out_path):
            with open(out_path, "wb") as f:
                f.write(b"wav")
            return out_path

        with tempfile.TemporaryDirectory() as tmp:
            run = DummyRun(tmp)
            with patch("app.config.LOCALIZATION_MODE", "llm"), \
                    patch("app.agents.localizer.localize_turn",
                          return_value=("एम-आर-एन-ए वैक्सीन क्या होती है?", 0.95)) as localize, \
                    patch("app.adapters.sarvam_translate.translate") as translate, \
                    patch("app.adapters.sarvam_tts.synth", side_effect=fake_synth), \
                    patch("app.adapters.sarvam_tts.combine_phrase_timeline_to_wav",
                          side_effect=fake_combine):
                episodes = render.run(object(), script, cast, run, ["hi-IN"])

            localize.assert_called_once()
            translate.assert_not_called()
            self.assertEqual(episodes[0].deliveries, ["एम-आर-एन-ए वैक्सीन क्या होती है?"])

    def test_llm_localization_receives_previous_english_turn(self):
        script = Script(turns=[
            Turn(idx=0, speaker="host", text="What is an mRNA vaccine?", move="ask", pace=1.0),
            Turn(idx=1, speaker="expert", text="It gives cells instructions.", move="answer", pace=1.0),
        ])
        cast = Cast(
            host=Persona(role="host", name="Host", background="host", voice="aditya"),
            expert=Persona(role="expert", name="Expert", background="expert", voice="shubh"),
        )

        def fake_localize(_client, target, prior, _lang, _cast, _run, _settings=None):
            if target.idx == 0:
                self.assertEqual(prior, [])
                return "एम-आर-एन-ए वैक्सीन क्या होती है?", 0.95
            self.assertEqual(prior[-1].text, "What is an mRNA vaccine?")
            return "यह कोशिकाओं को निर्देश देती है।", 0.94

        def fake_synth(_client, _text, _speaker, _run, pace=None, lang=None):
            return ["audio"]

        def fake_combine(_timeline, out_path):
            with open(out_path, "wb") as f:
                f.write(b"wav")
            return out_path

        with tempfile.TemporaryDirectory() as tmp:
            run = DummyRun(tmp)
            with patch("app.config.LOCALIZATION_MODE", "llm"), \
                    patch("app.agents.localizer.localize_turn",
                          side_effect=fake_localize) as localize, \
                    patch("app.adapters.sarvam_tts.synth", side_effect=fake_synth), \
                    patch("app.adapters.sarvam_tts.combine_phrase_timeline_to_wav",
                          side_effect=fake_combine):
                episodes = render.run(object(), script, cast, run, ["hi-IN"])

            self.assertEqual(localize.call_count, 2)
            self.assertEqual(episodes[0].deliveries, [
                "एम-आर-एन-ए वैक्सीन क्या होती है?",
                "यह कोशिकाओं को निर्देश देती है।",
            ])


if __name__ == "__main__":
    unittest.main()
