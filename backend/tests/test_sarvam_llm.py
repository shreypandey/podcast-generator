from __future__ import annotations

import unittest

from app.adapters import sarvam_llm


class DummyRun:
    def __init__(self):
        self.events = []

    def log(self, **kw):
        self.events.append(kw)


class _Message:
    def __init__(self, content: str):
        self.content = content


class _Choice:
    def __init__(self, content: str, finish_reason: str):
        self.message = _Message(content)
        self.finish_reason = finish_reason


class _Response:
    def __init__(self, content: str, finish_reason: str):
        self.choices = [_Choice(content, finish_reason)]
        self.usage = None


class _Completions:
    def __init__(self, responses: list[_Response]):
        self.responses = responses
        self.calls = []

    def __call__(self, **kw):
        self.calls.append(kw)
        if not self.responses:
            raise AssertionError("unexpected extra call")
        return self.responses.pop(0)


class _Chat:
    def __init__(self, completions: _Completions):
        self.completions = completions


class _Client:
    def __init__(self, responses: list[_Response]):
        self.chat = _Chat(_Completions(responses))


class SarvamLlmRetryTests(unittest.TestCase):
    def test_complete_json_uses_five_length_retries(self):
        responses = [
            _Response("", "length"),
            _Response("", "length"),
            _Response("", "length"),
            _Response("", "length"),
            _Response("", "length"),
            _Response('{"ok": true}', "stop"),
        ]
        client = _Client(responses)
        run = DummyRun()

        data = sarvam_llm.complete_json(client, "system", "user", run, stage="test")

        self.assertEqual(data, {"ok": True})
        self.assertEqual(len(client.chat.completions.calls), 6)
        self.assertEqual([event["attempt"] for event in run.events], [1, 2, 3, 4, 5, 6])
        self.assertEqual(
            [call["reasoning_effort"] for call in client.chat.completions.calls],
            ["low", "low", "low", "low", None, None],
        )
        self.assertEqual(
            [event["reasoning_effort"] for event in run.events],
            ["low", "low", "low", "low", None, None],
        )

    def test_complete_json_raises_after_five_empty_retries(self):
        responses = [_Response("", "length") for _ in range(6)]
        client = _Client(responses)

        with self.assertRaisesRegex(ValueError, "after 5 retries"):
            sarvam_llm.complete_json(client, "system", "user", DummyRun(), stage="test")

        self.assertEqual(len(client.chat.completions.calls), 6)


if __name__ == "__main__":
    unittest.main()
