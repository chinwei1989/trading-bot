"""Typed application configuration loaded from YAML."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml  # type: ignore[import-untyped]
from pydantic import BaseModel, Field, field_validator

from tradingbot.options.account import OptionLimits


class DataConfig(BaseModel):
    source: Literal["binance", "alpaca", "yahoo"] = "binance"
    market: Literal["spot", "futures"] = "spot"
    interval: str = "1d"
    symbols: list[str] = Field(
        default_factory=lambda: [
            "BTCUSDT",
            "ETHUSDT",
            "BNBUSDT",
            "SOLUSDT",
            "XRPUSDT",
            "ADAUSDT",
            "DOGEUSDT",
            "LINKUSDT",
        ]
    )
    start: str = "2020-01"
    end: str | None = None
    bars_path: Path = Path("data/normalized/bars.parquet")
    universe_path: Path | None = None
    raw_dir: Path = Path("data/raw")
    use_cache: bool = True
    verify_checksums: bool = True
    include_recent: bool = True
    recent_limit: int = 30

    @field_validator("symbols")
    @classmethod
    def _non_empty(cls, value: list[str]) -> list[str]:
        if not value:
            raise ValueError("symbols must not be empty")
        return list(dict.fromkeys(value))


class TrendParams(BaseModel):
    lookback: int = 200
    vol_window: int = 60
    target_vol: float = 0.15
    max_weight: float = 0.25
    long_short: bool = False
    rebalance: Literal["H", "D", "W", "M"] = "W"
    max_gross: float = 1.0
    vol_target: bool = True


class XsmomParams(BaseModel):
    lookback: int = 60
    skip: int = 7
    top_quantile: float = 0.30
    bottom_quantile: float = 0.30
    long_short: bool = True
    max_weight: float = 0.15
    rebalance: Literal["H", "D", "W", "M"] = "W"
    max_gross: float = 1.0
    vol_target: bool = True
    target_vol: float = 0.20
    vol_window: int = 30
    min_assets: int = 5


class BreakoutParams(BaseModel):
    lookback: int = 55
    exit_lookback: int = 20
    atr_window: int = 20
    atr_stop: float = 2.0
    risk_per_trade: float = 0.02
    vol_window: int = 60
    target_vol: float = 0.15
    max_weight: float = 0.20
    long_short: bool = False
    rebalance: Literal["H", "D", "W", "M"] = "W"
    max_gross: float = 1.0
    vol_target: bool = True
    volume_filter: bool = True
    volume_window: int = 20
    volume_multiplier: float = 1.0


class ReversalParams(BaseModel):
    lookback: int = 20
    entry_z: float = 2.0
    exit_z: float = 0.0
    rsi_window: int = 2
    rsi_entry: float = 5.0
    rsi_exit: float = 60.0
    regime_lookback: int = 200
    regime_filter: bool = True
    vol_window: int = 20
    target_vol: float = 0.10
    max_weight: float = 0.10
    long_short: bool = False
    rebalance: Literal["H", "D", "W", "M"] = "D"
    max_gross: float = 0.50
    vol_target: bool = True


class MetaParams(BaseModel):
    sleeves: dict[str, float] = Field(
        default_factory=lambda: {
            "trend": 0.40,
            "breakout": 0.30,
            "reversal": 0.15,
            "xsmom": 0.15,
        }
    )
    lookback: int = 90
    min_history: int = 30
    rebalance: Literal["H", "W", "M"] = "W"
    max_sleeve_weight: float = 0.60
    max_asset_weight: float = 0.25
    max_gross: float = 0.80
    target_vol: float = 0.12
    vol_window: int = 60
    vol_target: bool = True
    correlation_penalty: bool = True
    no_trade_band: float = 0.0
    max_asset_vol: float | None = None


class CombinedParams(BaseModel):
    trend_weight: float = 0.60
    xsmom_weight: float = 0.40
    target_vol: float = 0.15
    vol_window: int = 60
    max_gross: float = 1.0


class StrategyConfig(BaseModel):
    name: Literal["trend", "xsmom", "combined", "breakout", "reversal", "meta"] = "trend"
    trend: TrendParams = Field(default_factory=TrendParams)
    xsmom: XsmomParams = Field(default_factory=XsmomParams)
    breakout: BreakoutParams = Field(default_factory=BreakoutParams)
    reversal: ReversalParams = Field(default_factory=ReversalParams)
    combined: CombinedParams = Field(default_factory=CombinedParams)
    meta: MetaParams = Field(default_factory=MetaParams)


class BacktestConfig(BaseModel):
    initial_capital: float = 10_000.0
    cost_bps: float = 5.0
    slippage_bps: float = 5.0
    periods_per_year: int = 365
    execution_lag: int = 1
    risk_free_rate: float = 0.0
    output_dir: Path = Path("artifacts")


class RiskConfig(BaseModel):
    max_gross: float = 1.0
    max_net: float = 1.0
    max_asset_weight: float = 0.25
    max_drawdown: float = 0.30
    min_cash_weight: float = 0.0
    kill_switch_file: Path = Path("artifacts/KILL")
    state_path: Path = Path("artifacts/risk_state.json")
    auto_kill_on_drawdown: bool = True


class AgentPolicyConfig(BaseModel):
    max_gross: float = 0.80
    max_asset_weight: float = 0.20
    min_cash_weight: float = 0.20
    max_turnover: float = 0.50
    min_confidence: float = 0.55
    target_vol: float = 0.15
    risk_off_gross: float = 0.25
    allow_short: bool = False


class AgentConfig(BaseModel):
    enabled: bool = False
    provider: Literal["jev", "squad", "openai_compatible", "deterministic"] = (
        "deterministic"
    )
    model: str = "jev-latest"
    artifacts_dir: Path = Path("artifacts/ai")
    endpoint: str = "https://api.typesafe.ai/v1/systemone"
    api_key_env: str = "TYPESAFE_API_KEY"
    timeout_seconds: float = 30.0
    max_retries: int = 2
    temperature: float = 0.0
    max_tokens: int = 1200
    fallback: Literal["none", "deterministic"] = "none"
    paper_only: bool = True
    include_macro: bool = True
    include_sentiment: bool = True
    policy: AgentPolicyConfig = Field(default_factory=AgentPolicyConfig)


class SwingOptionsConfig(BaseModel):
    min_dte: int = 21
    max_dte: int = 45
    exit_dte: int = 7
    target_delta_min: float = 0.40
    target_delta_max: float = 0.60
    max_spread_pct: float = 0.05
    min_open_interest: int = 100
    profit_target_pct: float = 0.50
    stop_loss_pct: float = 0.50
    max_holding_days: int = 20
    max_contracts: int = 1
    max_premium_per_trade_pct: float = 0.02
    max_total_premium_pct: float = 0.05
    min_cash_pct: float = 0.20
    max_open_legs: int = 2
    max_legs_per_underlying: int = 1
    fee_bps: float = 3.0

    def to_option_limits(self) -> OptionLimits:
        return OptionLimits(
            max_premium_per_trade_pct=self.max_premium_per_trade_pct,
            max_total_premium_pct=self.max_total_premium_pct,
            min_cash_pct=self.min_cash_pct,
            max_open_legs=self.max_open_legs,
            max_legs_per_underlying=self.max_legs_per_underlying,
            min_dte=self.min_dte,
            max_dte=self.max_dte,
            exit_dte=self.exit_dte,
            target_delta_min=self.target_delta_min,
            target_delta_max=self.target_delta_max,
            max_spread_pct=self.max_spread_pct,
            min_open_interest=self.min_open_interest,
            fee_bps=self.fee_bps,
            min_contracts=1,
        )


class BrokerConfig(BaseModel):
    name: Literal["paper", "alpaca", "ccxt"] = "paper"
    paper: bool = True
    exchange: str = "kraken"
    sandbox: bool = True
    quote_currency: str = "USDT"
    allow_short: bool = False
    initial_cash: float = 10_000.0
    min_notional: float = 10.0
    max_child_notional: float | None = None
    max_children: int = 5
    journal_path: Path = Path("artifacts/orders.sqlite")
    order_state_path: Path = Path("artifacts/order_state.sqlite")
    state_path: Path = Path("artifacts/paper_state.json")
    heartbeat_path: Path = Path("artifacts/heartbeat.json")
    performance_path: Path = Path("artifacts/performance.jsonl")


class AppConfig(BaseModel):
    data: DataConfig = Field(default_factory=DataConfig)
    strategy: StrategyConfig = Field(default_factory=StrategyConfig)
    backtest: BacktestConfig = Field(default_factory=BacktestConfig)
    risk: RiskConfig = Field(default_factory=RiskConfig)
    broker: BrokerConfig = Field(default_factory=BrokerConfig)
    agent: AgentConfig = Field(default_factory=AgentConfig)
    swing: SwingOptionsConfig = Field(default_factory=SwingOptionsConfig)
    seed: int = 7


def load_config(path: str | Path = "config/base.yaml") -> AppConfig:
    """Load a YAML config; missing sections fall back to defaults."""
    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(f"config not found: {config_path}")
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    return AppConfig.model_validate(raw)


def resolve_path(root: Path, value: Path) -> Path:
    """Resolve a config path relative to the repository root."""
    return value if value.is_absolute() else root / value
