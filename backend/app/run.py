"""CLI entrypoint:  uv run python -m app.run "your topic" [--length short|medium|long] [--depth 1-5]"""
from __future__ import annotations

import argparse

from app.orchestrator import run_pipeline


def _split_focus(values: list[str] | None) -> list[str]:
    questions: list[str] = []
    for value in values or []:
        for item in str(value).split(","):
            text = item.strip()
            if text:
                questions.append(text)
    return questions


def main() -> None:
    p = argparse.ArgumentParser(prog="app.run", description="Generate a grounded two-host podcast.")
    p.add_argument("topic", nargs="+", help="the episode topic")
    p.add_argument("--length", choices=["short", "medium", "long"], default="medium",
                   help="episode length (turns/segments); default medium")
    p.add_argument("--depth", type=int, choices=[1, 2, 3, 4, 5], default=3,
                   help="depth/detail (sources, facts, explanation detail); default 3")
    p.add_argument("--langs", default="en-IN",
                   help="comma-separated Bulbul language codes to render, e.g. en-IN,hi-IN,ta-IN")
    p.add_argument("--angle", default="balanced",
                   choices=["balanced", "mechanism", "current", "controversy", "practical",
                            "mythbusting", "beginner"],
                   help="content angle/focus preset; default balanced")
    p.add_argument("--focus", action="append", default=[],
                   help="focus question; repeat or comma-separate multiple questions")
    p.add_argument("--custom-angle", default="",
                   help="short custom content guidance; grounding still wins")
    p.add_argument("--tone", default="conversational",
                   choices=["conversational", "serious", "energetic", "calm", "investigative"],
                   help="delivery tone preset; default conversational")
    p.add_argument("--style", default="curious_expert",
                   choices=["curious_expert", "debate", "storytelling", "classroom", "news_analysis"],
                   help="conversation style preset; default curious_expert")
    p.add_argument("--custom-style", default="",
                   help="short custom style guidance; role and grounding rules still win")
    args = p.parse_args()
    languages = [c.strip() for c in args.langs.split(",") if c.strip()] or ["en-IN"]
    run_pipeline(" ".join(args.topic).strip(), length=args.length, depth=args.depth,
                 languages=languages, angle=args.angle, focus_questions=_split_focus(args.focus),
                 custom_angle=args.custom_angle, tone=args.tone, style=args.style,
                 custom_style=args.custom_style)


if __name__ == "__main__":
    main()
