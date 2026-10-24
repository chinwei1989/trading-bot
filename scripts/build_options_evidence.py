"""Build the read-only options evidence JSON and Markdown report."""

from __future__ import annotations

from tradingbot.ops.options_evidence import write_options_evidence


def main() -> int:
    json_path, md_path = write_options_evidence()
    print(f"json: {json_path}")
    print(f"markdown: {md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
