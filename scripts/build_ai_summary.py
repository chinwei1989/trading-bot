"""Generate a concise Jev-classified gist of the current paper book."""

from __future__ import annotations

from pathlib import Path

from tradingbot.ops.ai_summary import build_ai_state_summary

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    result = build_ai_state_summary(ROOT)
    print(f"AI gist: {result['headline']}")
    print(result["summary"])
    for bullet in result["bullets"]:
        print(f"- {bullet}")
    print(f"Model: {result['model']} · created: {result['created_at']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
