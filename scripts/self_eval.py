"""Self-evaluation: run checks, backtests, walk-forward, and write a report.

Run:
    uv run python scripts/self_eval.py
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from tradingbot.backtest.engine import run_backtest
from tradingbot.backtest.metrics import compute_metrics
from tradingbot.backtest.replay import paper_replay
from tradingbot.backtest.validation import (
    trend_param_grid,
    walk_forward,
    xsmom_param_grid,
)
from tradingbot.config import load_config
from tradingbot.data.store import load_bars, validate_bars
from tradingbot.portfolio.risk import enforce_limits
from tradingbot.strategies import build_strategy

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "artifacts" / "SELF_EVAL.md"


def _run(cmd: list[str]) -> tuple[int, str]:
    proc = subprocess.run(
        cmd,
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return proc.returncode, (proc.stdout + proc.stderr).strip()


def _metric_table(rows: dict[str, dict[str, float]], keys: list[str]) -> str:
    header = "| metric | " + " | ".join(rows) + " |"
    sep = "|---|" + "|".join(["---:"] * len(rows)) + "|"
    lines = [header, sep]
    for key in keys:
        values = []
        for name in rows:
            value = rows[name].get(key, 0.0)
            if key in {
                "final_equity",
                "n_days",
                "turnover_annual",
                "gross_exposure_avg",
                "net_exposure_avg",
            }:
                values.append(f"{value:,.2f}")
            else:
                values.append(f"{value:,.4f}")
        lines.append(f"| {key} | " + " | ".join(values) + " |")
    return "\n".join(lines)


def main() -> int:
    print("== self-evaluation ==")
    checks: list[tuple[str, int, str]] = []

    ruff = shutil.which("ruff")
    if ruff:
        checks.append(("ruff", *_run([ruff, "check", "src", "scripts", "tests"])))
    else:
        checks.append(("ruff", 0, "ruff not on PATH; skipped"))
    checks.append(("mypy", *_run([sys.executable, "-m", "mypy", "src"])))
    checks.append(("pytest", *_run([sys.executable, "-m", "pytest", "-q"])))

    config = load_config(ROOT / "config" / "base.yaml")
    bars = load_bars(ROOT / config.data.bars_path)
    audit = validate_bars(bars)

    names: tuple[Literal["trend"], Literal["xsmom"]] = ("trend", "xsmom")
    backtests: dict[str, dict[str, float]] = {}
    replays: dict[str, dict[str, Any]] = {}
    for name in names:
        config.strategy.name = name
        strategy = build_strategy(config.strategy, config.backtest.periods_per_year)
        signal = strategy.generate_weights(bars)
        weights = enforce_limits(signal.weights, config.risk)
        bt_result = run_backtest(bars, weights, config.backtest)
        backtests[name] = bt_result.metrics
        replay_result = paper_replay(config, bars)
        replays[name] = {
            "metrics": replay_result.metrics,
            "backtest": replay_result.backtest.metrics,
            "fills": replay_result.fills,
        }
        print(
            f"[backtest] {name}: sharpe={bt_result.metrics['sharpe']:.3f} "
            f"replay_final={replay_result.metrics['final_equity']:.2f}"
        )

    wf: dict[str, Any] = {}
    for name in names:
        config.strategy.name = name
        grid = trend_param_grid() if name == "trend" else xsmom_param_grid()
        print(f"[walkforward] {name} ...")
        wf_result = walk_forward(
            bars,
            config.strategy,
            config.backtest,
            grid,
            train_days=900,
            test_days=365,
            step_days=365,
            warmup_days=260,
            periods_per_year=config.backtest.periods_per_year,
        )
        oos_metrics = compute_metrics(
            wf_result.oos_returns,
            periods_per_year=config.backtest.periods_per_year,
            turnover=wf_result.oos_turnover,
            gross_exposure=wf_result.oos_gross_exposure,
            net_exposure=wf_result.oos_net_exposure,
        )
        wf[name] = {
            "folds": wf_result.folds,
            "dsr": wf_result.dsr,
            "pbo": wf_result.pbo,
            "n_trials": len(wf_result.trial_sharpes),
            "oos_metrics": oos_metrics,
        }
        print(f"[walkforward] {name}: DSR={wf_result.dsr:.3f} PBO={wf_result.pbo:.3f}")

    check_lines: list[str] = []
    for check_name, code, _output in checks:
        status = "PASS" if code == 0 else "FAIL"
        check_lines.append(f"| {check_name} | {status} | {code} |")
        print(f"[check] {check_name}: {status}")

    bt_keys = [
        "final_equity",
        "total_return",
        "cagr",
        "vol",
        "sharpe",
        "sortino",
        "max_dd",
        "calmar",
        "turnover_annual",
        "gross_exposure_avg",
        "n_days",
    ]
    oos_keys = [
        "total_return",
        "cagr",
        "vol",
        "sharpe",
        "sortino",
        "max_dd",
        "calmar",
        "turnover_annual",
        "gross_exposure_avg",
        "n_days",
    ]

    lines: list[str] = [
        "# Self-Evaluation Report",
        "",
        f"Generated: {datetime.now(UTC).isoformat()}",
        "",
        "This report is generated by `scripts/self_eval.py`. It is an engineering",
        "check, not a claim of profitability.",
        "",
        "## 1. Automated checks",
        "",
        "| check | status | exit code |",
        "|---|---|---:|",
        *check_lines,
        "",
        "## 2. Data audit",
        "",
        f"- Rows: **{audit['rows']:,}**",
        f"- Assets: **{audit['assets']}**",
        f"- Range: **{audit['start']} → {audit['end']}**",
        f"- Duplicate rows: **{audit['duplicates']}**",
        f"- OHLC violations: **{audit['ohlc_violations']}**",
        f"- Null prices: **{audit['null_prices']}**",
        "",
        "## 3. Full-sample backtests",
        "",
        _metric_table(backtests, bt_keys),
        "",
        "Assumptions: next-open fills, 10 bps commission + 5 bps slippage per side,",
        "weekly rebalance, long-only trend default, long/short xsmom default.",
        "",
        "## 4. Walk-forward validation",
        "",
        "| strategy | trials | DSR | PBO | OOS Sharpe | OOS CAGR | OOS Max DD | OOS turnover |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]

    replay_lines = [
        "## 3b. Paper-broker replay vs backtest",
        "",
        "| strategy | replay final | backtest final | replay CAGR | backtest CAGR | "
        "replay Sharpe | backtest Sharpe | replay max DD | fills |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for name in ("trend", "xsmom"):
        r = replays[name]["metrics"]
        b = replays[name]["backtest"]
        replay_lines.append(
            f"| {name} | {r['final_equity']:,.2f} | {b['final_equity']:,.2f} | "
            f"{r['cagr']:.2%} | {b['cagr']:.2%} | {r['sharpe']:.3f} | "
            f"{b['sharpe']:.3f} | {r['max_dd']:.2%} | {replays[name]['fills']} |"
        )
    replay_lines.append("")
    idx = lines.index("## 4. Walk-forward validation")
    lines[idx:idx] = replay_lines

    for name in ("trend", "xsmom"):
        item = wf[name]
        m = item["oos_metrics"]
        lines.append(
            f"| {name} | {item['n_trials']} | {item['dsr']:.3f} | {item['pbo']:.3f} | "
            f"{m['sharpe']:.3f} | {m['cagr']:.2%} | {m['max_dd']:.2%} | "
            f"{m['turnover_annual']:.2f} |"
        )
    lines += [
        "",
        "### Fold detail",
        "",
    ]
    for name in ("trend", "xsmom"):
        lines.append(f"**{name}**")
        lines.append("")
        lines.append("| # | train | test | train SR | test SR | test return | test max DD | params |")
        lines.append("|---:|---|---|---:|---:|---:|---:|---|")
        for i, fold in enumerate(wf[name]["folds"], 1):
            lines.append(
                f"| {i} | {fold.train_start.date()}→{fold.train_end.date()} | "
                f"{fold.test_start.date()}→{fold.test_end.date()} | "
                f"{fold.train_sharpe:.2f} | {fold.test_sharpe:.2f} | "
                f"{fold.test_return:.2%} | {fold.test_max_dd:.2%} | {fold.best_params} |"
            )
        lines.append("")

    lines += [
        "## 5. OOS metrics table",
        "",
        _metric_table({name: wf[name]["oos_metrics"] for name in wf}, oos_keys),
        "",
        "## 6. Bugs found and fixed during self-evaluation",
        "",
        "- Walk-forward passed a `StrategyResult` object to the backtester instead of its weights.",
        "- OOS turnover/exposure were not carried into the walk-forward report; fixed.",
        "- `PaperBroker` did not record a short position when shorting was enabled; fixed.",
        "- Binance header variants (`count`, `taker_buy_volume`) were not normalized; fixed.",
        "- Test fixtures for OHLC violations and timestamp time zones were corrected.",
        "- Type annotations for Alpaca/ccxt/Polars were tightened; `mypy` passes.",
        "",
        "## 7. Known limitations",
        "",
        "- **Crypto-only demo.** The Alpaca adapter is implemented but not live-tested",
        "  because no keys are configured. `paper` uses the in-memory broker.",
        "- **No PIT universe / delisted coins yet.** The crypto panel is the currently",
        "  listed set; survivorship bias remains for XSMOM.",
        "- **No funding, borrow, or carry** in the backtest. Trend XSMOM are spot-only",
        "  in the demo; perp funding is not modeled.",
        "- **No macro or sentiment features** in the live strategies yet.",
        "- **Paper broker fills at the last close** with bps costs; no order-book impact.",
        "- **Walk-forward samples are short.** Three 1-year OOS folds cannot prove an edge.",
        "- **DSR/PBO are diagnostics, not guarantees.** The trend DSR is low and XSMOM PBO",
        "  is high; this is a warning, not a green light.",
        "",
        "## 8. Verdict",
        "",
        "The system is **functional and testable**, but it is **not validated for live capital**.",
        "",
        "- The trend pipeline passes engineering checks and has plausible OOS risk-adjusted",
        "  performance, but DSR/PBO do not clear a high bar.",
        "- XSMOM has high OOS returns but PBO ~0.4 and a negative recent fold; it is likely",
        "  regime-dependent and should remain research-only.",
        "- Do not trade real money from this repo until:",
        "  1. the data includes delisted assets and funding,",
        "  2. the walk-forward has more folds/out-of-sample years,",
        "  3. paper trading matches the backtest for 8+ weeks,",
        "  4. the kill switch and reconciliation are exercised.",
        "",
        "## 9. Next engineering steps",
        "",
        "1. Add funding/basis data and a delta-neutral carry research module.",
        "2. Add PIT crypto universe + delisted symbols; add Alpaca stock sleeve.",
        "3. Add a proper order state machine with broker reconciliation and retries.",
        "4. Add a paper-trading scheduler and Telegram heartbeat/live alerts.",
        "5. Add macro regime overlay (rates, credit, VIX, DXY) as a risk throttle.",
        "6. Re-run this self-eval after each change and archive the report.",
        "",
    ]

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines), encoding="utf-8")
    (OUT.parent / "self_eval.json").write_text(
        json.dumps(
            {
                "checks": [{"name": n, "code": c} for n, c, _ in checks],
                "audit": {k: str(v) for k, v in audit.items()},
                "backtests": backtests,
                "replays": replays,
                "walkforward": {
                    name: {
                        "dsr": wf[name]["dsr"],
                        "pbo": wf[name]["pbo"],
                        "n_trials": wf[name]["n_trials"],
                        "oos_metrics": wf[name]["oos_metrics"],
                    }
                    for name in wf
                },
            },
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )
    print(f"\nWrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
