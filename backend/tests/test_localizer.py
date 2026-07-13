from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.agents import localizer
from app.artifacts import Cast, Persona, Turn


class DummyRun:
    def __init__(self):
        self.events = []

    def log(self, **kw):
        self.events.append(kw)


class LocalizerTests(unittest.TestCase):
    def test_prompt_requests_native_podcast_localization(self):
        turn = Turn(
            idx=0,
            speaker="host",
            text="I'm excited to start with the basics. What is an mRNA vaccine?",
            move="ask",
        )
        cast = Cast(
            host=Persona(role="host", name="Clara Vance", background="host", voice="priya"),
            expert=Persona(role="expert", name="Dr. Ben Carter", background="expert", voice="aditya"),
        )
        run = DummyRun()

        with patch("app.adapters.sarvam_llm.complete_json",
                   return_value={"spoken": "मुझे खुशी है कि हम बुनियाद से शुरू कर रहे हैं। एम-आर-एन-ए वैक्सीन क्या होती है?", "pace": 0.96}) as complete:
            spoken, pace = localizer.localize_turn(object(), turn, [], "hi-IN", cast, run)

        system = complete.call_args.args[1]
        user = complete.call_args.args[2]
        self.assertIn("publishable spoken Hindi", system)
        self.assertIn("Avoid code-mixing", system)
        self.assertIn("Clara Vance", user)
        self.assertIn("Dr. Ben Carter", user)
        self.assertIn("FINAL ENGLISH TURN TO LOCALIZE:", user)
        self.assertIn("बुनियाद", spoken)
        self.assertEqual(pace, 1.0)

    def test_rejects_romanized_output(self):
        turn = Turn(idx=0, speaker="host", text="What is an mRNA vaccine?", move="ask")
        cast = Cast(
            host=Persona(role="host", name="Clara", background="host", voice="priya"),
            expert=Persona(role="expert", name="Dr. Carter", background="expert", voice="aditya"),
        )

        with patch("app.adapters.sarvam_llm.complete_json",
                   return_value={"spoken": "Toh doctor, mRNA vaccine kya hoti hai?", "pace": 1.0}):
            with self.assertRaises(localizer.LocalizationError):
                localizer.localize_turn(object(), turn, [], "hi-IN", cast, DummyRun())

    def test_localizes_hindi_acronyms_deterministically(self):
        turn = Turn(idx=0, speaker="host", text="What is an mRNA vaccine?", move="ask")
        cast = Cast(
            host=Persona(role="host", name="Clara", background="host", voice="priya"),
            expert=Persona(role="expert", name="Dr. Carter", background="expert", voice="aditya"),
        )

        with patch("app.adapters.sarvam_llm.complete_json",
                   return_value={"spoken": "mRNA वैक्सीन क्या होती है?", "pace": 1.0}):
            spoken, _ = localizer.localize_turn(object(), turn, [], "hi-IN", cast, DummyRun())

        self.assertEqual(spoken, "एम-आर-एन-ए वैक्सीन क्या होती है?")

    def test_prompt_includes_recent_english_context(self):
        turn = Turn(idx=1, speaker="expert", text="Exactly. It gives cells instructions.", move="answer")
        prior = [Turn(idx=0, speaker="host", text="What does it do?", move="ask")]
        cast = Cast(
            host=Persona(role="host", name="Clara", background="host", voice="priya"),
            expert=Persona(role="expert", name="Dr. Carter", background="expert", voice="aditya"),
        )

        with patch("app.adapters.sarvam_llm.complete_json",
                   return_value={"spoken": "बिलकुल। यह कोशिकाओं को निर्देश देता है।", "pace": 1.0}) as complete:
            localizer.localize_turn(object(), turn, prior, "hi-IN", cast, DummyRun())

        user = complete.call_args.args[2]
        self.assertIn("RECENT ENGLISH CONTEXT:", user)
        self.assertIn("HOST: What does it do?", user)
        self.assertIn("FINAL ENGLISH TURN TO LOCALIZE:", user)
        self.assertIn("Exactly. It gives cells instructions.", user)

    def test_logs_code_mix_warning_without_rejecting_native_output(self):
        turn = Turn(idx=0, speaker="expert", text="I'm excited to explain it.", move="answer")
        cast = Cast(
            host=Persona(role="host", name="Clara", background="host", voice="priya"),
            expert=Persona(role="expert", name="Dr. Carter", background="expert", voice="aditya"),
        )
        run = DummyRun()

        with patch("app.adapters.sarvam_llm.complete_json",
                   return_value={"spoken": "मैं excited हूँ कि इसे समझा सकूं।", "pace": 1.0}):
            spoken, _ = localizer.localize_turn(object(), turn, [], "hi-IN", cast, run)

        self.assertIn("excited", spoken)
        self.assertTrue(any(event.get("kind") == "code_mix_warning" for event in run.events))


if __name__ == "__main__":
    unittest.main()
