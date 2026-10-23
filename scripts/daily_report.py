"""Generate the daily evaluation report for one strategy/config."""

from __future__ import annotations

import argparse
from pathlib import Path

from tradingbot.config import load_config
from tradingbot.ops.evaluation import build_report, print_summary, write_report

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config/base.yaml")
    parser.add_argument(
        "--strategy",
        choices=["trend", "xsmom", "breakout", "reversal", "meta"],
        default=None,
    )
    args = parser.parse_args()

    config = load_config(ROOT / args.config if not Path(args.config).is_absolute() else args.config)
    if args.strategy:
        config.strategy.name = args.strategy
    report = build_report(config, config.strategy.name, ROOT)
    md_path, json_path = write_report(report, ROOT)
    print_summary(report)
    print(f"Saved: {md_path}")
    print(f"Saved: {json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
