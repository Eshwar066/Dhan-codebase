"""
Engine configuration for multi-venue architecture.

One config = one venue (one broker, one OMS stack).
Use EngineFactory.create_engine(config) to build an isolated BacktestEngine or LiveEngine.

Call ``configure_process_logging`` early (see ``run.main`` / ``EngineFactory.create_engine``)
so ``logging.getLogger(__name__)`` loggers emit to stderr with a consistent format.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Tuple, Union

from run.config import (
    DEFAULT_LIBRARY_LOG_LEVEL,
    DEFAULT_ROOT_LOG_LEVEL,
    RunMode,
)


BrokerName = Literal["DHAN", "DELTA"]

_logging_configured = False

_NOISY_LIBRARY_LOGGERS = (
    "urllib3",
    "urllib3.connectionpool",
    "requests",
    "requests.packages.urllib3",
    "websocket",
)


def resolve_log_level(value: Optional[Union[str, int]]) -> int:
    if value is None:
        return logging.INFO
    if isinstance(value, int):
        return int(value)
    s = str(value).strip().upper()
    if s.isdigit():
        return int(s)
    return getattr(logging, s, logging.INFO)

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
    strategy_names: Optional[List[str]] = None
    symbols: Optional[List[str]] = (
        None  # None = derive from universe (e.g. IPOBreakout)
    )
    enabled: bool = True

    # Engine identity (for logging and reports)
    engine_id: Optional[str] = None
    market_exchange: Optional[str] = None

    # Capital bucket (per-engine; no shared capital)
    capital: Optional[float] = None
    risk_per_trade_percent: Optional[float] = None

    # Risk limits (optional)
    daily_max_loss: Optional[float] = None
    max_open_positions: Optional[int] = None
    max_portfolio_exposure: Optional[float] = None
    cooldown_seconds: Optional[int] = None
    order_qty_lots: Optional[int] = None

    # Option shorting: if False, do not use broker's check_short_option_margin (e.g. futures-only).
    check_short_option_margin_enabled: Optional[bool] = None

    # Feed health: warn/pause when no data for this many seconds (live only).
    feed_stale_seconds: Optional[float] = None

    # Backtest params (used when run_mode == BACKTEST)
    backtest: Optional[Dict[str, Any]] = None

    # Live/paper params (used when run_mode in (PAPER, LIVE))
    live: Optional[Dict[str, Any]] = None

    # Venue-specific options (optional overrides)
    delta_testnet: bool = True
    delta_india: bool = True
    # Delta Exchange: leverage to set per product (e.g. 10 for 10x). Applied at engine start for config.symbols.
    delta_leverage: Optional[int] = None

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

    # Stdlib logging: env ALGO_LOG_LEVEL / ALGO_LIBRARY_LOG_LEVEL override when set.
    root_log_level: str = DEFAULT_ROOT_LOG_LEVEL
    library_log_level: str = DEFAULT_LIBRARY_LOG_LEVEL

    # Telegram alerts (e.g. for Delta): order placed, broker errors, slippage. Optional.
    telegram_bot_token: Optional[str] = None
    telegram_chat_id: Optional[str] = None
    account_routing: Optional[Dict[str, Any]] = None
    oms_rate_limit_per_sec: float = 5.0
    intent_queue_maxsize: int = 1000
    account_queue_maxsize: int = 500
    queue_overflow_policy: str = "drop_newest"
    oms_retry_max_attempts: int = 3
    oms_retry_base_delay_seconds: float = 0.25
    oms_token_bucket_capacity: int = 5
    worker_watchdog_interval_seconds: float = 5.0
    max_active_account_symbol_keys: int = 200
    account_circuit_breaker_threshold: int = 5
    feed_stall_seconds: float = 60.0

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


def configure_process_logging(
    config: Optional[EngineConfig] = None,
    *,
    force: bool = False,
) -> None:
    """
    Attach a StreamHandler to the root logger and set levels so module loggers
    (e.g. ``core.strategies.deltaMktMixins``) print INFO+ to stderr by default.

    Env ``ALGO_LOG_LEVEL`` and ``ALGO_LIBRARY_LOG_LEVEL`` override config when non-empty.
    Idempotent unless ``force=True``.
    """
    global _logging_configured
    if _logging_configured and not force:
        return

    env_root = os.environ.get("ALGO_LOG_LEVEL", "").strip()
    env_lib = os.environ.get("ALGO_LIBRARY_LOG_LEVEL", "").strip()

    root_level = resolve_log_level(
        env_root or (config.root_log_level if config else DEFAULT_ROOT_LOG_LEVEL)
    )
    lib_level = resolve_log_level(
        env_lib or (config.library_log_level if config else DEFAULT_LIBRARY_LOG_LEVEL)
    )

    fmt = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
    logging.basicConfig(
        level=root_level,
        format=fmt,
        datefmt="%Y-%m-%d %H:%M:%S",
        force=force or not _logging_configured,
    )

    for name in _NOISY_LIBRARY_LOGGERS:
        logging.getLogger(name).setLevel(lib_level)

    logging.getLogger(__name__).debug(
        "process logging: root=%s noisy_libs=%s",
        logging.getLevelName(root_level),
        logging.getLevelName(lib_level),
    )
    _logging_configured = True


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
        delta_india=True,
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
        delta_india=True,
        backtest={
            "start_date": "2024-03-20",
            "end_date": "2025-03-30",
            "timeframe": "60",
            "exchange": "INDEX",
            "sector": "YES",
        },
        live={"exchange": "INDEX", "sector": "YES", "rsi": "NO"},
    )
