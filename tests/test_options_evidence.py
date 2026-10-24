from __future__ import annotations

import json
from pathlib import Path

from tradingbot.ops.options_evidence import (
    build_options_evidence,
    write_options_evidence,
)


def _write(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_options_evidence_summarizes_paper_squad_and_replay(tmp_path: Path) -> None:
    ai = tmp_path / "artifacts" / "ai_options_30m"
    rows = [
        {
            "timestamp": "2026-10-24T00:00:00+00:00",
            "regime": "risk_off",
            "confidence": 0.0,
            "equity": 10_000.0,
            "cash": 10_000.0,
            "n_orders": 0,
            "n_fills": 0,
            "positions": 0,
            "directions": {"BTC": "flat", "ETH": "flat"},
        },
        {
            "timestamp": "2026-10-24T00:30:00+00:00",
            "regime": "risk_off",
            "confidence": 0.0,
            "equity": 10_000.0,
            "cash": 10_000.0,
            "n_orders": 0,
            "n_fills": 0,
            "positions": 0,
            "directions": {"BTC": "flat", "ETH": "flat"},
        },
    ]
    (ai / "performance.jsonl").parent.mkdir(parents=True, exist_ok=True)
    (ai / "performance.jsonl").write_text(
        "\n".join(json.dumps(row) for row in rows) + "\n",
        encoding="utf-8",
    )
    decisions = [
        {
            "as_of": "2026-10-24T00:00:00+00:00",
            "status": "ok",
            "regime": "risk_off",
            "confidence": 0.0,
            "directions": {"BTC": "flat", "ETH": "flat"},
            "equity": 10_000.0,
            "cash": 10_000.0,
            "dry_run": False,
        },
        {
            "as_of": "2026-10-24T00:30:00+00:00",
            "status": "ok",
            "regime": "risk_off",
            "confidence": 0.0,
            "directions": {"BTC": "flat", "ETH": "flat"},
            "equity": 10_000.0,
            "cash": 10_000.0,
            "dry_run": False,
        },
    ]
    (ai / "decisions.jsonl").write_text(
        "\n".join(json.dumps(row) for row in decisions) + "\n",
        encoding="utf-8",
    )

    run = ai / "squad" / "run-1"
    for filename, stage, regime, choices in (
        ("01_macro.json", "macro", "risk_off", {}),
        ("05_risk.json", "risk", "risk_off", {"BTC": "veto", "ETH": "approve"}),
        (
            "06_execution.json",
            "execution",
            "stressed",
            {"BTC": "block", "ETH": "allow"},
        ),
        ("08_chair.json", "chair", "risk_off", {"BTC": "flat", "ETH": "flat"}),
    ):
        _write(
            run / filename,
            {
                "stage": stage,
                "regime": regime,
                "as_of": "2026-10-24T00:30:00+00:00",
                "choices": choices,
            },
        )
    _write(run / "manifest.json", {"agents": ["macro", "risk", "execution", "chair"]})

    _write(
        tmp_path
        / "artifacts"
        / "options_tardis"
        / "tardis_replay_2026-10-01.json",
        {
            "chain_date": "2026-10-01",
            "snapshots": 47,
            "underlying_bars": 2_928,
            "signal_source": "Binance public 30m klines",
            "total_fills": 5,
            "total_return": -0.0032,
            "max_drawdown": -0.0038,
            "total_fees": 0.11,
            "limitations": "one day only",
        },
    )

    evidence = build_options_evidence(tmp_path)
    assert evidence["paper"]["paper_days"] == 1
    assert evidence["paper"]["cycles"] == 2
    assert evidence["paper"]["expected_cycles"] == 2
    assert evidence["paper"]["cycle_coverage"] == 1.0
    assert evidence["paper"]["flat_cycles"] == 2
    assert evidence["paper"]["risk_off_cycles"] == 2
    assert evidence["paper"]["fills"] == 0
    assert evidence["squad"]["runs"] == 1
    assert evidence["squad"]["runs_with_risk_veto"] == 1
    assert evidence["squad"]["runs_with_execution_block"] == 1
    assert evidence["squad"]["risk_veto_assets"] == 1
    assert evidence["squad"]["execution_block_assets"] == 1
    assert evidence["squad"]["chair_flat_runs"] == 1
    assert evidence["replay"]["snapshots"] == 47
    assert evidence["status"] == "insufficient"

    json_path, md_path = write_options_evidence(tmp_path)
    assert json_path.exists()
    assert md_path.exists()
    assert "Options Evidence" in md_path.read_text(encoding="utf-8")
