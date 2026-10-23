"""Command-line interface for data, backtests, validation, and paper trading."""

from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path

import polars as pl
from dotenv import load_dotenv

from tradingbot.ai.evaluation import build_scorecard, format_scorecard, write_scorecard
from tradingbot.ai.pipeline import read_ai_report, run_ai_cycle
from tradingbot.backtest.engine import run_backtest
from tradingbot.backtest.metrics import compute_metrics
from tradingbot.backtest.replay import paper_replay
from tradingbot.backtest.validation import (
    breakout_param_grid,
    meta_param_grid,
    reversal_param_grid,
    trend_param_grid,
    walk_forward,
    xsmom_param_grid,
)
from tradingbot.config import AppConfig, load_config
from tradingbot.data.store import load_bars, validate_bars
from tradingbot.data.universe import load_bars_with_universe
from tradingbot.execution.factory import build_broker
from tradingbot.execution.orders import (
    OrderJournal,
    execute_orders,
    latest_weights,
    plan_orders,
    reconcile,
)
from tradingbot.execution.paper import PaperBroker
from tradingbot.ops.evaluation import build_report, print_summary, write_report
from tradingbot.ops.heartbeat import read_heartbeat
from tradingbot.ops.live_gate import build_live_gate, write_gate
from tradingbot.ops.runner import run_forever
from tradingbot.portfolio.risk import assert_safe, enforce_limits
from tradingbot.strategies import build_strategy

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")


def _path(config: AppConfig, value: Path) -> Path:
    return value if value.is_absolute() else ROOT / value


def _load_market_bars(config: AppConfig, bars_path: Path) -> pl.DataFrame:
    universe = _path(config, config.data.universe_path) if config.data.universe_path else None
    return load_bars_with_universe(bars_path, universe)


def _print_metrics(name: str, metrics: dict[str, float]) -> None:
    print(f"\n{name}")
    print("-" * len(name))
    keys = [
        "final_equity",
        "total_return",
        "cagr",
        "vol",
        "sharpe",
        "sortino",
        "max_dd",
        "calmar",
        "hit_rate",
        "profit_factor",
        "turnover_annual",
        "gross_exposure_avg",
        "net_exposure_avg",
        "n_days",
    ]
    for key in keys:
        if key in metrics:
            value = metrics[key]
            if key in {"final_equity", "n_days"}:
                print(f"{key:>18}: {value:,.2f}")
            elif key in {"turnover_annual", "gross_exposure_avg", "net_exposure_avg"}:
                print(f"{key:>18}: {value:,.3f}")
            else:
                print(f"{key:>18}: {value:,.4f}")


def _save_chart(daily: pl.DataFrame, path: Path, title: str) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    eq = daily["equity"].to_list()
    ts = daily["timestamp"].to_list()
    peak = []
    best = 0.0
    for value in eq:
        best = max(best, value)
        peak.append(value / best - 1.0 if best else 0.0)
    fig, (ax1, ax2) = plt.subplots(
        2, 1, figsize=(11, 7), sharex=True, gridspec_kw={"height_ratios": [3, 1]}
    )
    ax1.plot(ts, eq, color="#1f77b4", lw=1.6)
    ax1.set_title(title)
    ax1.set_ylabel("Equity")
    ax1.grid(alpha=0.3)
    ax2.fill_between(ts, peak, 0, color="#d62728", alpha=0.4)
    ax2.set_ylabel("Drawdown")
    ax2.grid(alpha=0.3)
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=140)
    plt.close(fig)


def cmd_download(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    if config.data.source == "binance":
        from tradingbot.data.binance import download_many

        download_many(config.data, ROOT)
    elif config.data.source == "alpaca":
        from tradingbot.data.alpaca import download_alpaca

        download_alpaca(config.data, ROOT)
    else:
        from tradingbot.data.yahoo import download_yahoo

        download_yahoo(config.data, ROOT)
    return 0


def cmd_download_macro(args: argparse.Namespace) -> int:
    from tradingbot.data.fred import download_macro

    config = load_config(args.config)
    download_macro(
        start=args.start,
        path=_path(config, Path("data/normalized/macro.parquet")),
    )
    return 0


def _load_strategy_config(args: argparse.Namespace) -> AppConfig:
    config = load_config(args.config)
    if getattr(args, "strategy", None):
        config.strategy.name = args.strategy
    return config


def cmd_backtest(args: argparse.Namespace) -> int:
    config = _load_strategy_config(args)
    bars_path = _path(config, config.data.bars_path)
    if not bars_path.exists():
        raise SystemExit(f"missing {bars_path}; run `download` first")
    bars = _load_market_bars(config, bars_path)
    strategy = build_strategy(config.strategy, config.backtest.periods_per_year)
    result = strategy.generate_weights(bars)
    weights = enforce_limits(result.weights, config.risk)
    assert_safe(
        weights,
        config.risk,
        kill_file=_path(config, config.risk.kill_switch_file),
    )
    bt = run_backtest(bars, weights, config.backtest)

    out_dir = _path(config, config.backtest.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = f"backtest_{config.strategy.name}"
    bt.daily.write_csv(out_dir / f"{stem}_daily.csv")
    weights.write_parquet(out_dir / f"{stem}_weights.parquet")
    (out_dir / f"{stem}_metrics.json").write_text(
        json.dumps(bt.metrics, indent=2, default=str), encoding="utf-8"
    )
    _save_chart(bt.daily, out_dir / f"{stem}.png", f"{config.strategy.name} backtest")
    _print_metrics(f"{config.strategy.name} backtest", bt.metrics)
    print(f"\nSaved: {out_dir / stem}_daily.csv, .png, _metrics.json")
    return 0


def cmd_paper_replay(args: argparse.Namespace) -> int:
    config = _load_strategy_config(args)
    bars_path = _path(config, config.data.bars_path)
    if not bars_path.exists():
        raise SystemExit(f"missing {bars_path}; run `download` first")
    bars = _load_market_bars(config, bars_path)
    result = paper_replay(config, bars)
    print("\nPaper-broker replay vs vectorized backtest")
    print("-------------------------------------------")
    keys = ["final_equity", "cagr", "vol", "sharpe", "sortino", "max_dd", "turnover_annual"]
    print(f"{'metric':<20}{'paper replay':>16}{'backtest':>16}")
    for key in keys:
        print(
            f"{key:<20}{result.metrics.get(key, 0.0):>16.4f}"
            f"{result.backtest.metrics.get(key, 0.0):>16.4f}"
        )
    print(f"{'fills':<20}{result.fills:>16d}")

    out_dir = _path(config, config.backtest.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = f"paper_replay_{config.strategy.name}"
    result.daily.write_csv(out_dir / f"{stem}_daily.csv")
    (out_dir / f"{stem}_metrics.json").write_text(
        json.dumps(
            {"paper_replay": result.metrics, "backtest": result.backtest.metrics},
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )
    print(f"\nSaved: {out_dir / f'{stem}_daily.csv'} and _metrics.json")
    return 0


def cmd_walkforward(args: argparse.Namespace) -> int:
    config = _load_strategy_config(args)
    bars_path = _path(config, config.data.bars_path)
    if not bars_path.exists():
        raise SystemExit(f"missing {bars_path}; run `download` first")
    bars = _load_market_bars(config, bars_path)
    grids = {
        "trend": trend_param_grid,
        "xsmom": xsmom_param_grid,
        "breakout": breakout_param_grid,
        "reversal": reversal_param_grid,
        "meta": meta_param_grid,
    }
    if config.strategy.name not in grids:
        raise SystemExit(f"walk-forward is not configured for {config.strategy.name}")
    grid = grids[config.strategy.name]()
    result = walk_forward(
        bars,
        config.strategy,
        config.backtest,
        grid,
        train_days=args.train_days,
        test_days=args.test_days,
        step_days=args.step_days,
        warmup_days=args.warmup_days,
        periods_per_year=config.backtest.periods_per_year,
    )
    print(f"\nWalk-forward folds ({len(result.folds)}):")
    for i, fold in enumerate(result.folds, 1):
        print(
            f"  {i}: train {fold.train_start.date()}..{fold.train_end.date()} "
            f"test {fold.test_start.date()}..{fold.test_end.date()} "
            f"trainSR={fold.train_sharpe:.2f} testSR={fold.test_sharpe:.2f} "
            f"testRet={fold.test_return:.2%} maxDD={fold.test_max_dd:.2%} "
            f"params={fold.best_params}"
        )
    _print_metrics(
        "OOS (concatenated best folds)",
        compute_metrics(
            result.oos_returns,
            periods_per_year=config.backtest.periods_per_year,
            turnover=result.oos_turnover,
            gross_exposure=result.oos_gross_exposure,
            net_exposure=result.oos_net_exposure,
        ),
    )
    print(f"\nTrials: {len(result.trial_sharpes)}")
    print(f"DSR: {result.dsr:.4f}")
    print(f"PBO: {result.pbo:.4f}")

    out_dir = _path(config, config.backtest.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "folds": [
            {
                **{k: str(v) for k, v in vars(fold).items() if k != "best_params"},
                "best_params": fold.best_params,
            }
            for fold in result.folds
        ],
        "dsr": result.dsr,
        "pbo": result.pbo,
        "n_trials": len(result.trial_sharpes),
        "oos_metrics": compute_metrics(
            result.oos_returns,
            periods_per_year=config.backtest.periods_per_year,
            turnover=result.oos_turnover,
            gross_exposure=result.oos_gross_exposure,
            net_exposure=result.oos_net_exposure,
        ),
    }
    (out_dir / f"walkforward_{config.strategy.name}.json").write_text(
        json.dumps(payload, indent=2, default=str), encoding="utf-8"
    )
    print(f"\nSaved: {out_dir / f'walkforward_{config.strategy.name}.json'}")
    return 0


def cmd_paper(args: argparse.Namespace) -> int:
    config = _load_strategy_config(args)
    bars_path = _path(config, config.data.bars_path)
    if not bars_path.exists():
        raise SystemExit(f"missing {bars_path}; run `download` first")
    bars = _load_market_bars(config, bars_path)
    if config.data.interval == "1d":
        bars = bars.filter(pl.col("timestamp").dt.date() < datetime.now(UTC).date())
    strategy = build_strategy(config.strategy, config.backtest.periods_per_year)
    signal = strategy.generate_weights(bars)
    weights = enforce_limits(signal.weights, config.risk)
    assert_safe(weights, config.risk, kill_file=_path(config, config.risk.kill_switch_file))

    latest = latest_weights(weights)
    if latest.is_empty():
        print("No target weights; nothing to do.")
        return 0
    last_prices = (
        bars.sort("timestamp").group_by("asset").tail(1).select(["asset", "close"]).rows()
    )
    prices = {asset: float(close) for asset, close in last_prices}
    long_short = {
        "trend": config.strategy.trend.long_short,
        "xsmom": config.strategy.xsmom.long_short,
        "breakout": config.strategy.breakout.long_short,
        "reversal": config.strategy.reversal.long_short,
    }
    allow_short = any(long_short.values())
    broker = PaperBroker(
        cash=config.broker.initial_cash,
        prices=prices,
        commission_bps=config.backtest.cost_bps,
        slippage_bps=config.backtest.slippage_bps,
        allow_short=allow_short,
    )
    state_path = _path(config, config.broker.state_path)
    if not args.reset and broker.load_state(state_path):
        print(f"Loaded paper state: {state_path}")
    account = broker.get_account()
    orders = plan_orders(
        latest,
        account.equity,
        prices,
        broker.get_positions(),
        min_notional=config.broker.min_notional,
        allow_short=allow_short,
    )
    journal = OrderJournal(_path(config, config.broker.journal_path))
    results = execute_orders(broker, orders, journal)
    print(f"\nPaper rebalance at {str(latest['timestamp'].max())[:10]}")
    print(f"Equity: {account.equity:,.2f} | Cash: {account.cash:,.2f}")
    for fill in results:
        print(
            f"  {fill.side:<4} {fill.asset:<12} qty={fill.filled_qty:.8f} "
            f"@ {(fill.avg_price or 0.0):,.4f} status={fill.status}"
        )
    if not results:
        print("  No orders (within min notional or no target weights).")
    print("\nPositions:")
    for asset, pos in broker.get_positions().items():
        print(f"  {asset:<12} qty={pos.qty:.8f} value={pos.market_value:,.2f}")
    print("\nReconciliation:")
    rec = reconcile(latest, account.equity, prices, broker.get_positions())
    print(rec)
    broker.save_state(state_path)
    print(f"Saved paper state: {state_path}")
    journal.close()
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    bars_path = _path(config, config.data.bars_path)
    if not bars_path.exists():
        raise SystemExit(f"missing {bars_path}")
    report = validate_bars(load_bars(bars_path))
    for key, value in report.items():
        print(f"{key}: {value}")
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    print("Config:")
    print(f"  strategy: {config.strategy.name}")
    print(f"  data: {config.data.source} {config.data.market} {config.data.interval}")
    print(f"  bars: {_path(config, config.data.bars_path)}")
    print(f"  broker: {config.broker.name} paper={config.broker.paper}")
    print(f"  agent: {config.agent.provider} {config.agent.model}")
    print("Keys present:")
    for key in [
        "ALPACA_API_KEY",
        "ALPACA_SECRET_KEY",
        "FRED_API_KEY",
        "CRYPTO_API_KEY",
        "TYPESAFE_API_KEY",
        "AI_API_KEY",
    ]:
        print(f"  {key}: {'yes' if os.getenv(key) else 'no'}")
    bars_path = _path(config, config.data.bars_path)
    if bars_path.exists():
        print("Data:")
        for key, value in validate_bars(load_bars(bars_path)).items():
            print(f"  {key}: {value}")
    else:
        print(f"  missing: {bars_path}")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    return run_forever(
        args.config,
        mode=args.mode,
        interval_seconds=args.interval,
        confirm_live=args.confirm_live,
        once=args.once,
        reset=args.reset,
        strategy_override=args.strategy,
        root=ROOT,
    )


def cmd_ai_run(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    if args.provider:
        config.agent.provider = args.provider
    try:
        result = run_ai_cycle(
            config,
            root=ROOT,
            reset=args.reset,
            dry_run=args.dry_run,
            provider_override=args.provider,
        )
    except Exception as exc:
        print(f"AI pipeline failed: {type(exc).__name__}: {exc}")
        return 1
    print(
        f"[ai] status={result.status} provider={result.provider} "
        f"model={result.model} fallback={result.fallback} "
        f"equity={result.equity:,.2f} cash={result.cash:,.2f} "
        f"orders={len(result.orders)} fills={len(result.fills)}"
    )
    if result.decision:
        print(
            f"  regime={result.decision.regime} "
            f"confidence={result.decision.confidence:.1%}"
        )
    if result.alerts:
        print("  alerts:")
        for alert in result.alerts:
            print(f"    - {alert}")
    if result.report_path:
        print(f"  report: {result.report_path}")
    if result.audit_path:
        print(f"  audit: {result.audit_path}")
    return 0 if result.status in {"ok", "dry_run"} else 1


def cmd_ai_evaluate(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    scorecard = build_scorecard(config, ROOT)
    json_path, md_path = write_scorecard(scorecard, ROOT)
    print(f"AI scorecard: {format_scorecard(scorecard)}")
    for note in scorecard.get("notes", []):
        print(f"  note: {note}")
    print(f"Saved: {json_path}")
    print(f"Saved: {md_path}")
    return 0


def cmd_ai_status(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    report = read_ai_report(ROOT)
    print(f"AI config: {args.config}")
    print(f"  provider: {config.agent.provider}")
    print(f"  model: {config.agent.model}")
    print(f"  paper_only: {config.agent.paper_only}")
    if report is None:
        print("  no AI report yet")
        return 0
    print(json.dumps(report, indent=2, default=str))
    return 0


def cmd_live(args: argparse.Namespace) -> int:
    if not args.confirm_live:
        raise SystemExit("refusing live trading: pass --confirm-live (and LIVE_TRADING=YES)")
    return run_forever(
        args.config,
        mode="live",
        interval_seconds=60,
        confirm_live=True,
        once=True,
        strategy_override=args.strategy,
        root=ROOT,
    )


def cmd_live_gate(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    gate = build_live_gate(config, root=ROOT, include_ai=args.include_ai)
    json_path, md_path = write_gate(gate, ROOT)
    print(f"Live gate: {gate['status']}")
    for check in gate["checks"]:
        mark = "PASS" if check["passed"] else "FAIL"
        print(f"  [{mark}] {check['name']}: {check['detail']}")
    print(f"Saved: {json_path}")
    print(f"Saved: {md_path}")
    return 0 if gate["status"] == "GO" else 1


def cmd_kill(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    kill = _path(config, config.risk.kill_switch_file)
    kill.parent.mkdir(parents=True, exist_ok=True)
    kill.write_text("manual kill", encoding="utf-8")
    print(f"kill switch active: {kill}")
    return 0


def cmd_resume(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    kill = _path(config, config.risk.kill_switch_file)
    if kill.exists():
        kill.unlink()
        print(f"kill switch removed: {kill}")
    else:
        print("kill switch was not active")
    return 0


def cmd_flatten(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    live = config.broker.name != "paper" and not config.broker.paper
    if live:
        if not args.confirm_live:
            raise SystemExit("refusing to flatten a live account without --confirm-live")
        if os.getenv("LIVE_TRADING") != "YES":
            raise SystemExit("refusing live flatten: LIVE_TRADING=YES is not set")
        if config.broker.name == "ccxt" and config.broker.sandbox:
            raise SystemExit("refusing live flatten: broker.sandbox is true")
        broker = build_broker(config, force_paper=False, allow_short=config.broker.allow_short)
        broker.flatten()
        print("live account flatten request sent")
        return 0

    bars_path = _path(config, config.data.bars_path)
    if not bars_path.exists():
        raise SystemExit(f"missing {bars_path}")
    bars = _load_market_bars(config, bars_path)
    last = bars.sort("timestamp").group_by("asset").tail(1)
    prices = {r["asset"]: float(r["close"]) for r in last.iter_rows(named=True)}
    broker = build_broker(config, force_paper=True, allow_short=True)
    if not isinstance(broker, PaperBroker):
        raise SystemExit("expected a paper broker")
    broker.set_prices(prices)
    state = _path(config, config.broker.state_path)
    broker.load_state(state)
    broker.flatten()
    broker.save_state(state)
    print(f"paper positions flattened; state: {state}")
    return 0


def cmd_carry_walkforward(args: argparse.Namespace) -> int:
    from tradingbot.backtest.carry import (
        carry_param_grid,
        load_carry_inputs,
        walk_forward_carry,
    )

    spot, perp, funding = load_carry_inputs(
        args.spot_config,
        args.perp_config,
        args.funding,
        root=ROOT,
    )
    result = walk_forward_carry(
        spot,
        perp,
        funding,
        carry_param_grid(),
        train_days=args.train_days,
        test_days=args.test_days,
        step_days=args.step_days,
        warmup_days=args.warmup_days,
    )
    print(f"\nCarry walk-forward folds ({len(result.folds)}):")
    for i, fold in enumerate(result.folds, 1):
        test_metrics = fold.get("test_metrics")
        test_sharpe = (
            float(test_metrics.get("sharpe", 0.0))
            if isinstance(test_metrics, dict)
            else 0.0
        )
        print(
            f"  {i}: train {str(fold['train_start'])[:10]}..{str(fold['train_end'])[:10]} "
            f"test {str(fold['test_start'])[:10]}..{str(fold['test_end'])[:10]} "
            f"params={fold['best_params']} testSharpe={test_sharpe:.2f}"
        )
    _print_metrics("Carry OOS", result.oos_metrics)
    print(f"\nTrials: {len(result.trial_sharpes)}")
    print(f"DSR: {result.dsr:.4f}")
    print(f"PBO: {result.pbo:.4f}")
    out = Path(args.output_dir)
    out = out if out.is_absolute() else ROOT / out
    out.mkdir(parents=True, exist_ok=True)
    path = out / "carry_walkforward.json"
    path.write_text(
        json.dumps(
            {
                "folds": result.folds,
                "oos_metrics": result.oos_metrics,
                "dsr": result.dsr,
                "pbo": result.pbo,
                "n_trials": len(result.trial_sharpes),
            },
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )
    print(f"\nSaved: {path}")
    return 0


def cmd_carry_backtest(args: argparse.Namespace) -> int:
    from tradingbot.backtest.carry import (
        CarryParams,
        load_carry_inputs,
        run_carry,
        save_carry,
    )

    spot, perp, funding = load_carry_inputs(
        args.spot_config,
        args.perp_config,
        args.funding,
        root=ROOT,
    )
    params = CarryParams(
        lookback_days=args.lookback_days,
        rebalance_days=args.rebalance_days,
        min_funding_apr=args.min_funding_apr,
        top_n=args.top_n,
        max_weight=args.max_weight,
        max_gross=args.max_gross,
        spot_cost_bps=args.spot_cost_bps,
        perp_cost_bps=args.perp_cost_bps,
    )
    result = run_carry(spot, perp, funding, params, initial_capital=args.initial_capital)
    print("\nCarry backtest")
    print("--------------")
    for key in [
        "final_equity",
        "total_return",
        "cagr",
        "vol",
        "sharpe",
        "max_dd",
        "turnover_annual",
        "gross_exposure_avg",
        "avg_funding_annualized",
        "avg_basis_annualized",
    ]:
        print(f"{key:>22}: {result.metrics.get(key, 0.0):,.4f}")
    out = Path(args.output_dir)
    out = out if out.is_absolute() else ROOT / out
    daily, weights, metrics = save_carry(result, out)
    _save_chart(result.daily, out / "carry.png", "Funding carry research")
    print(f"\nSaved: {daily}, {weights}, {metrics}")
    return 0


def cmd_download_funding(args: argparse.Namespace) -> int:
    from tradingbot.data.funding import download_funding

    symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
    if not symbols:
        raise SystemExit("--symbols must contain at least one symbol")
    download_funding(symbols, args.start, args.end, Path(args.output))
    return 0


def cmd_funding_summary(args: argparse.Namespace) -> int:
    from tradingbot.data.funding import funding_summary

    summary = funding_summary(args.path)
    print(summary)
    return 0


def cmd_universe_audit(args: argparse.Namespace) -> int:
    from tradingbot.data.universe import audit_spans, load_spans

    config = load_config(args.config)
    bars_path = _path(config, config.data.bars_path)
    if not bars_path.exists():
        raise SystemExit(f"missing {bars_path}")
    report = audit_spans(load_bars(bars_path))
    print(json.dumps(report, indent=2, default=str))
    if config.data.universe_path:
        spans_path = _path(config, config.data.universe_path)
        print(f"universe file: {spans_path}")
        if spans_path.exists():
            print(load_spans(spans_path))
    return 0


def cmd_universe_build(args: argparse.Namespace) -> int:
    from tradingbot.data.universe import save_spans, spans_from_bars

    config = load_config(args.config)
    bars_path = _path(config, config.data.bars_path)
    if not bars_path.exists():
        raise SystemExit(f"missing {bars_path}")
    out = _path(config, Path(args.output))
    spans = spans_from_bars(load_bars(bars_path))
    save_spans(spans, out)
    print(spans)
    print(f"Saved: {out}")
    return 0


def cmd_health(args: argparse.Namespace) -> int:
    from tradingbot.ops.campaign_health import (
        build_health,
        format_health,
        notify_health,
        write_health,
    )

    report = build_health(ROOT, max_age_hours=args.max_age_hours)
    json_path, md_path = write_health(report, ROOT)
    print(format_health(report))
    print(f"Saved: {json_path}")
    print(f"Saved: {md_path}")
    if args.notify:
        notify_health(report)
    return 0 if report["status"] == "OK" else 1


def cmd_evaluate(args: argparse.Namespace) -> int:
    config = _load_strategy_config(args)
    report = build_report(config, config.strategy.name, ROOT)
    md_path, json_path = write_report(report, ROOT)
    print_summary(report)
    print(f"Saved: {md_path}")
    print(f"Saved: {json_path}")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    heartbeat = _path(config, config.broker.heartbeat_path)
    payload = read_heartbeat(heartbeat)
    print(f"heartbeat: {heartbeat}")
    if payload:
        print(json.dumps(payload, indent=2, default=str))
    else:
        print("  no heartbeat yet")
    state = _path(config, config.broker.state_path)
    if state.exists():
        print(f"paper state: {state}")
        print(state.read_text(encoding="utf-8"))
    kill = _path(config, config.risk.kill_switch_file)
    print(f"kill switch: {'ACTIVE' if kill.exists() else 'inactive'}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Crypto + US equity systematic trading bot")
    parser.add_argument("--config", default="config/base.yaml")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("download", help="download configured bars")
    p.set_defaults(func=cmd_download)

    p = sub.add_parser("download-macro", help="download FRED macro series")
    p.add_argument("--start", default="2000-01-01")
    p.set_defaults(func=cmd_download_macro)

    p = sub.add_parser("backtest", help="run a full-sample backtest")
    p.add_argument("--strategy", choices=["trend", "xsmom", "breakout", "reversal", "meta"], default=None)
    p.set_defaults(func=cmd_backtest)

    p = sub.add_parser("paper-replay", help="replay history through the paper broker")
    p.add_argument("--strategy", choices=["trend", "xsmom", "breakout", "reversal", "meta"], default=None)
    p.set_defaults(func=cmd_paper_replay)

    p = sub.add_parser("walkforward", help="walk-forward validation + DSR/PBO")
    p.add_argument("--strategy", choices=["trend", "xsmom", "breakout", "reversal", "meta"], default=None)
    p.add_argument("--train-days", type=int, default=900)
    p.add_argument("--test-days", type=int, default=365)
    p.add_argument("--step-days", type=int, default=365)
    p.add_argument("--warmup-days", type=int, default=260)
    p.set_defaults(func=cmd_walkforward)

    p = sub.add_parser("paper", help="simulate one rebalance against the paper broker")
    p.add_argument("--strategy", choices=["trend", "xsmom", "breakout", "reversal", "meta"], default=None)
    p.add_argument("--reset", action="store_true", help="discard saved paper state")
    p.set_defaults(func=cmd_paper)

    p = sub.add_parser("run", help="run one cycle or a scheduled paper/preview/live loop")
    p.add_argument("--mode", choices=["paper", "preview", "live"], default="paper")
    p.add_argument("--interval", type=int, default=3600, help="seconds between cycles")
    p.add_argument("--once", action="store_true", help="run one cycle and exit")
    p.add_argument("--reset", action="store_true", help="reset paper state before the first cycle")
    p.add_argument("--confirm-live", action="store_true")
    p.add_argument("--strategy", choices=["trend", "xsmom", "breakout", "reversal", "meta"], default=None)
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("ai-run", help="run the separate AI-agent paper pipeline")
    p.add_argument("--reset", action="store_true", help="archive AI paper state and start fresh")
    p.add_argument("--dry-run", action="store_true", help="decide and report without orders")
    p.add_argument(
        "--provider",
        choices=["jev", "openai_compatible", "deterministic"],
        default=None,
        help="override the configured decision provider",
    )
    p.set_defaults(func=cmd_ai_run)

    p = sub.add_parser("ai-status", help="show the latest AI-agent report")
    p.set_defaults(func=cmd_ai_status)

    p = sub.add_parser("ai-evaluate", help="build the AI-agent paper scorecard")
    p.set_defaults(func=cmd_ai_evaluate)

    p = sub.add_parser("live", help="run one gated live cycle")
    p.add_argument("--confirm-live", action="store_true")
    p.add_argument("--strategy", choices=["trend", "xsmom", "breakout", "reversal", "meta"], default=None)
    p.set_defaults(func=cmd_live)

    p = sub.add_parser("live-gate", help="evaluate hard evidence and environment gates")
    p.add_argument("--include-ai", action="store_true", help="also evaluate the AI scorecard")
    p.set_defaults(func=cmd_live_gate)

    p = sub.add_parser("kill", help="activate the local kill switch")
    p.set_defaults(func=cmd_kill)

    p = sub.add_parser("resume", help="remove the local kill switch")
    p.set_defaults(func=cmd_resume)

    p = sub.add_parser("flatten", help="flatten paper or live positions")
    p.add_argument("--confirm-live", action="store_true")
    p.set_defaults(func=cmd_flatten)

    p = sub.add_parser("carry-walkforward", help="walk-forward validation for the carry research lane")
    p.add_argument("--spot-config", default="config/base.yaml")
    p.add_argument("--perp-config", default="config/futures.yaml")
    p.add_argument("--funding", default="data/normalized/funding.parquet")
    p.add_argument("--output-dir", default="artifacts/carry")
    p.add_argument("--train-days", type=int, default=730)
    p.add_argument("--test-days", type=int, default=365)
    p.add_argument("--step-days", type=int, default=365)
    p.add_argument("--warmup-days", type=int, default=60)
    p.set_defaults(func=cmd_carry_walkforward)

    p = sub.add_parser("carry-backtest", help="run the two-leg funding/basis carry research backtest")
    p.add_argument("--spot-config", default="config/base.yaml")
    p.add_argument("--perp-config", default="config/futures.yaml")
    p.add_argument("--funding", default="data/normalized/funding.parquet")
    p.add_argument("--output-dir", default="artifacts/carry")
    p.add_argument("--initial-capital", type=float, default=10_000.0)
    p.add_argument("--lookback-days", type=int, default=14)
    p.add_argument("--rebalance-days", type=int, default=7)
    p.add_argument("--min-funding-apr", type=float, default=0.05)
    p.add_argument("--top-n", type=int, default=5)
    p.add_argument("--max-weight", type=float, default=0.20)
    p.add_argument("--max-gross", type=float, default=0.80)
    p.add_argument("--spot-cost-bps", type=float, default=10.0)
    p.add_argument("--perp-cost-bps", type=float, default=10.0)
    p.set_defaults(func=cmd_carry_backtest)

    p = sub.add_parser("download-funding", help="download public Binance perpetual funding history")
    p.add_argument("--symbols", default="BTCUSDT,ETHUSDT,SOLUSDT")
    p.add_argument("--start", default="2020-01-01")
    p.add_argument("--end", default=None)
    p.add_argument("--output", default="data/normalized/funding.parquet")
    p.set_defaults(func=cmd_download_funding)

    p = sub.add_parser("funding-summary", help="summarize a funding-rate parquet file")
    p.add_argument("--path", default="data/normalized/funding.parquet")
    p.set_defaults(func=cmd_funding_summary)

    p = sub.add_parser("universe-audit", help="show listing spans and PIT universe status")
    p.set_defaults(func=cmd_universe_audit)

    p = sub.add_parser("universe-build", help="build a PIT span file from current bars")
    p.add_argument("--output", default="config/pit_universe_crypto.csv")
    p.set_defaults(func=cmd_universe_build)

    p = sub.add_parser("health", help="check that every paper campaign wrote a fresh row")
    p.add_argument("--max-age-hours", type=float, default=26.0)
    p.add_argument("--notify", action="store_true", help="send a Telegram alert if degraded")
    p.set_defaults(func=cmd_health)

    p = sub.add_parser("evaluate", help="build live-vs-backtest/TCA/drift report")
    p.add_argument("--strategy", choices=["trend", "xsmom", "breakout", "reversal", "meta"], default=None)
    p.set_defaults(func=cmd_evaluate)

    p = sub.add_parser("status", help="show heartbeat, paper state, kill switch")
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("validate-data", help="run data-quality checks")
    p.set_defaults(func=cmd_validate)

    p = sub.add_parser("check", help="print environment/data/config status")
    p.set_defaults(func=cmd_check)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
