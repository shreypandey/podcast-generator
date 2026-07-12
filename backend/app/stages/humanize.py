"""Humanize stage: post-generation, parallel per-turn. Adds Turn.spoken + Turn.pace.

Each turn is humanized from a 3-turn window of CLEAN text (2 prior + target), so calls are
independent and run in parallel (no sequential dependency on the humanized output)."""
from __future__ import annotations

import concurrent.futures

from app import config
from app.agents import humanizer
from app.artifacts import Script


def run(client, script: Script, run, settings=None) -> Script:
    turns = script.turns

    def work(i: int):
        window = turns[max(0, i - 2):i + 1]  # clean text only
        return i, humanizer.humanize_turn(client, window, run, settings)

    if not turns:
        return script
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(config.HUMANIZE_MAX_WORKERS, len(turns))) as ex:
        for fut in concurrent.futures.as_completed([ex.submit(work, i) for i in range(len(turns))]):
            i, (spoken, pace) = fut.result()
            turns[i].spoken = spoken
            turns[i].pace = pace
    return script
