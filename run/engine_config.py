"""
Engine configuration for multi-venue architecture.

One config = one venue (one broker, one OMS stack).
Use EngineFactory.create_engine(config) to build an isolated BacktestEngine or LiveEngine.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

from run.config import RunMode


BrokerName = Literal["DHAN", "DELTA"]


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

    # Backtest params (used when run_mode == BACKTEST)
    backtest: Optional[Dict[str, Any]] = None

    # Live/paper params (used when run_mode in (PAPER, LIVE))
    live: Optional[Dict[str, Any]] = None

    # Venue-specific options (optional overrides)
    # Dhan: no extra required
    # Delta:
    delta_testnet: bool = True
    delta_india: bool = False

    # Paths (defaults; override for tests)
    base_dir: Optional[Path] = None

    def __post_init__(self):
        if self.base_dir is None:
            self.base_dir = Path(__file__).resolve().parents[1]
        if self.backtest is None:
            self.backtest = {}
        if self.live is None:
            self.live = {}

    @property
    def dependencies_dir(self) -> Path:
        return self.base_dir / "Dependencies"


# ---------------------------------------------------------------------------
# Example configs: Dhan (India) and Delta (Crypto)
# ---------------------------------------------------------------------------

def example_dhan_live_config() -> EngineConfig:
    """Example: Dhan live engine for India markets (NIFTY, equities)."""
    return EngineConfig(
        broker_name="DHAN",
        run_mode=RunMode.LIVE,
        strategy_name="LEAPS_RSI",
        symbols=["NIFTY"],
        enabled=True,
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
    """Example: Delta live engine for crypto (BTCUSD, etc.)."""
    return EngineConfig(
        broker_name="DELTA",
        run_mode=RunMode.LIVE,
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
