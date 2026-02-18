from enum import Enum


class RunMode(str, Enum):
    BACKTEST = "BACKTEST"
    PAPER = "PAPER"
    LIVE = "LIVE"


# 🔁 CHANGE ONLY THIS
RUN_MODE = RunMode.LIVE

# Default venue when job does not specify "venue". Used for single-venue runs.
DEFAULT_VENUE = "DELTA"  # "DHAN" | "DELTA"

STRATEGY_JOBS = [
    {
        "name": "LEAPS_RSI",
        "venue": "DHAN",
        "enabled": False,
        "capital": 200000,
        "symbols": ["NIFTY"],
        "live": {"exchange": "INDEX", "sector": "YES", "rsi": "YES"},
        "backtest": {
            "start_date": "2023-10-19",
            "end_date": "2024-02-28",
            "timeframe": "60",
            "exchange": "INDEX",
            "sector": "YES",
        },
    },
    {
        "name": "INSIDE_BAR",
        "venue": "DHAN",
        "enabled": False,
        "capital": 100000,
        "symbols": ["INFY", "ITC"],
        "backtest": {
            "start_date": "2023-01-01",
            "end_date": "2024-12-31",
        },
    },
    {
        "name": "FuturesEMAHighLow",
        "venue": "DELTA",
        "enabled": False,
        "capital": 200000,
        "symbols": ["BTCUSD"],
        "instrument": "FUTURES",
        "delta_india": True,
        "delta_testnet": False,
        "live": {"exchange": "INDEX", "sector": "YES"},
        "backtest": {
            "start_date": "2024-03-20",
            "end_date": "2025-03-30",
            "timeframe": "60",
            "exchange": "INDEX",
            "sector": "YES",
        },
    },
    # Pipeline test configs: Signal every 1m, hit Risk/OMS/Router/Broker/PM. Use PAPER or LIVE.
    {
        "name": "SignalFloodTest",
        "venue": "DELTA",
        "enabled": True,
        "engine_id": "delta_test_pipeline",
        "capital": 10000,
        "symbols": ["BTCUSD"],
        "instrument": "FUTURES",
        "delta_india": True,
        "delta_testnet": False,
        "daily_max_loss": 100,
        "max_open_positions": 1,
        "feed_stale_seconds": 30,
        "order_state_check_interval_min": 1,
        "memory_threshold_percent": 5,
        "latency_critical_ms": 50,
        "latency_critical_cycles": 1,
        "symbol_error_threshold": 2,
        "live": {"exchange": "INDEX", "sector": "YES"},
        "backtest": {
            "start_date": "2024-03-20",
            "end_date": "2024-03-25",
            "timeframe": "1",
            "exchange": "INDEX",
            "sector": "YES",
        },
    },
    {
        "name": "SignalFloodTest",
        "venue": "DHAN",
        "enabled": False,
        "engine_id": "dhan_test_pipeline",
        "capital": 10000,
        "symbols": ["NIFTY"],
        "instrument": "FUTURES",
        "daily_max_loss": 100,
        "max_open_positions": 1,
        "feed_stale_seconds": 30,
        "order_state_check_interval_min": 1,
        "memory_threshold_percent": 5,
        "latency_critical_ms": 50,
        "latency_critical_cycles": 1,
        "symbol_error_threshold": 2,
        "live": {"exchange": "INDEX", "sector": "YES"},
        "backtest": {
            "start_date": "2023-10-19",
            "end_date": "2023-10-25",
            "timeframe": "1",
            "exchange": "INDEX",
            "sector": "YES",
        },
    },
]
