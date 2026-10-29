from __future__ import annotations

import json
from pathlib import Path

from tradingbot.ops.frontend_data import _decisions_payload, _validation_payload


def test_decisions_payload_reads_latest_snapshot(tmp_path: Path) -> None:
    decisions = tmp_path / "artifacts" / "decisions"
    decisions.mkdir(parents=True)
    (decisions / "latest.json").write_text(
        json.dumps(
            {
                "generated_at": "2026-10-29T00:00:00+00:00",
                "lanes": [
                    {
                        "lane": "Trend",
                        "decisions": [{"asset": "BTCUSDT", "decision": "HOLD"}],
                        "recent_orders": [],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    payload = _decisions_payload(tmp_path)

    assert payload["generated_at"] == "2026-10-29T00:00:00+00:00"
    assert payload["lanes"][0]["lane"] == "Trend"


def test_decisions_payload_missing_file(tmp_path: Path) -> None:
    assert _decisions_payload(tmp_path) == {}



def test_validation_payload_preserves_zero_pbo(tmp_path: Path) -> None:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    report = {
        "generated_at": "2026-10-28T00:00:00+00:00",
        "code_commit": "abc1234",
        "data": {
            "rows": 20_987,
            "n_assets": 9,
            "start": "2020-01-01 00:00:00+00:00",
            "end": "2026-10-27 00:00:00+00:00",
            "sha256": "deadbeef",
        },
        "method": {"train_days": 900, "test_days": 365},
        "strategies": [
            {
                "strategy": "trend",
                "folds": 3,
                "trials": 72,
                "dsr": 0.0,
                "pbo": 0.0,
                "oos_sharpe": 0.45,
                "oos_cagr": 0.062,
                "oos_max_dd": -0.206,
                "passed": False,
            }
        ],
        "sensitivity": [
            {
                "strategy": "trend",
                "folds": 7,
                "trials": 168,
                "dsr": 0.014,
                "pbo": 0.248,
                "oos_sharpe": 0.67,
                "oos_cagr": 0.096,
                "oos_max_dd": -0.182,
                "passed": False,
            }
        ],
        "passing": [],
        "verdict": "NO STRATEGY PASSES",
    }
    (artifacts / "validation_report.json").write_text(
        json.dumps(report), encoding="utf-8"
    )

    payload = _validation_payload(tmp_path)

    assert payload["data"]["rows"] == 20_987
    assert payload["strategies"][0]["pbo"] == 0.0
    assert payload["strategies"][0]["passed"] is False
    assert payload["sensitivity"][0]["strategy"] == "trend"
    assert payload["verdict"] == "NO STRATEGY PASSES"


def test_validation_payload_missing_file(tmp_path: Path) -> None:
    assert _validation_payload(tmp_path) == {}
