"""
Engine configuration for multi-venue architecture.

One config = one venue (one broker, one OMS stack).
Use EngineFactory.create_engine(config) to build an isolated BacktestEngine or LiveEngine.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Tuple

from run.config import RunMode


BrokerName = Literal["DHAN", "DELTA"]

# Allowed trading hours: list of (start_time, end_time) as "HH:MM" in UTC (or configurable timezone).
# E.g. [("09:15", "15:30")] for India NSE.
TradingHoursType = List[Tuple[str, str]]


@dataclass
class EngineConfig:
    """
    Config for a single-venue engine. All OMS components will be built
    from this config and remain isolated from other engines.
    """

    broker_name: BrokerName
    run_mode: RunMode
    strategy_name: str
    symbols: List[str]
    enabled: bool = True

    # Engine identity (for logging and reports)
    engine_id: Optional[str] = None

    # Capital bucket (per-engine; no shared capital)
    capital: Optional[float] = None
    risk_per_trade_percent: Optional[float] = None

    # Risk limits (optional)
    daily_max_loss: Optional[float] = None

    # Backtest params (used when run_mode == BACKTEST)
    backtest: Optional[Dict[str, Any]] = None

    # Live/paper params (used when run_mode in (PAPER, LIVE))
    live: Optional[Dict[str, Any]] = None

    # Venue-specific options (optional overrides)
    delta_testnet: bool = True
    delta_india: bool = False

    # Paths (defaults; override for tests)
    base_dir: Optional[Path] = None

    # ---------- Production safeguards (live only; no change to BacktestEngine) ----------
    # Order state consistency: run verify_open_orders_with_broker every N minutes (0 = disabled).
    order_state_check_interval_min: int = 0
    # Broker circuit breaker: after this many consecutive broker failures, trigger kill switch.
    circuit_breaker_threshold: int = 5
    # Time-of-day guard: only allow entry within these windows. Exits always allowed. "HH:MM" UTC.
    allowed_trading_hours: Optional[TradingHoursType] = None
    # Slippage monitor: log high_slippage_warning when |fill_price - expected_price| / expected_price > this (e.g. 0.005 = 0.5%).
    slippage_threshold_pct: Optional[float] = None
    # Memory guard: pause new entries when process memory usage exceeds this percent (0 = disabled).
    memory_threshold_percent: Optional[float] = None
    # Strategy timeout: if strategy evaluation exceeds this many seconds, log and skip order placement.
    strategy_timeout_seconds: Optional[float] = None
    # Latency: pause entries if total_latency_ms > this for N consecutive cycles.
    latency_critical_ms: float = 150.0
    latency_critical_cycles: int = 3
    # Symbol-level failure: pause only this symbol after this many consecutive errors.
    symbol_error_threshold: int = 5

    def __post_init__(self):
        if self.base_dir is None:
            self.base_dir = Path(__file__).resolve().parents[1]
        if self.backtest is None:
            self.backtest = {}
        if self.live is None:
            self.live = {}
        if self.engine_id is None:
            self.engine_id = f"{self.broker_name}_{self.strategy_name}".lower()

    @property
    def dependencies_dir(self) -> Path:
        return self.base_dir / "Dependencies"


# ---------------------------------------------------------------------------
# Example configs: Dhan (India) and Delta (Crypto)
# ---------------------------------------------------------------------------

def example_dhan_live_config() -> EngineConfig:
    """Example: Dhan live engine for India markets (NIFTY, equities) with capital."""
    return EngineConfig(
        broker_name="DHAN",
        run_mode=RunMode.LIVE,
        strategy_name="LEAPS_RSI",
        symbols=["NIFTY"],
        enabled=True,
        engine_id="dhan_leaps_rsi",
        capital=200_000.0,
        risk_per_trade_percent=0.5,
        backtest={
            "start_date": "2023-10-19",
            "end_date": "2024-02-28",
            "timeframe": "60",
            "exchange": "INDEX",
            "sector": "YES",
        },
        live={
            "exchange": "INDEX",
            "sector": "YES",
            "rsi": "YES",
        },
    )


def example_dhan_backtest_config() -> EngineConfig:
    """Example: Dhan backtest only."""
    return EngineConfig(
        broker_name="DHAN",
        run_mode=RunMode.BACKTEST,
        strategy_name="INSIDE_BAR",
        symbols=["INFY", "ITC"],
        enabled=True,
        backtest={
            "start_date": "2023-01-01",
            "end_date": "2024-12-31",
            "timeframe": "5",
            "exchange": "NSE",
            "sector": "NO",
        },
        live={"exchange": "NSE", "sector": "NO", "rsi": "NO"},
    )


def example_delta_live_config() -> EngineConfig:
    """Example: Delta live engine for crypto (BTCUSD, etc.) with capital bucket."""
    return EngineConfig(
        broker_name="DELTA",
        run_mode=RunMode.LIVE,
        strategy_name="FuturesEMAHighLow",
        symbols=["BTCUSD"],
        enabled=True,
        engine_id="delta_futures_ema",
        capital=200_000.0,
        risk_per_trade_percent=1.0,
        delta_testnet=True,
        delta_india=False,
        backtest={
            "start_date": "2024-03-20",
            "end_date": "2025-03-30",
            "timeframe": "60",
            "exchange": "INDEX",
            "sector": "YES",
        },
        live={
            "exchange": "INDEX",
            "sector": "YES",
            "rsi": "NO",
        },
    )


def example_delta_backtest_config() -> EngineConfig:
    """Example: Delta backtest only."""
    return EngineConfig(
        broker_name="DELTA",
        run_mode=RunMode.BACKTEST,
        strategy_name="FuturesEMAHighLow",
        symbols=["BTCUSD"],
        enabled=True,
        delta_testnet=True,
        delta_india=False,
        backtest={
            "start_date": "2024-03-20",
            "end_date": "2025-03-30",
            "timeframe": "60",
            "exchange": "INDEX",
            "sector": "YES",
        },
        live={"exchange": "INDEX", "sector": "YES", "rsi": "NO"},
    )
