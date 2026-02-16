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
        "enabled": True,
        "capital": 200000,
        "symbols": ["BTCUSD"],
        "instrument": "FUTURES",
        "live": {"exchange": "INDEX", "sector": "YES"},
        "backtest": {
            "start_date": "2024-03-20",
            "end_date": "2025-03-30",
            "timeframe": "60",
            "exchange": "INDEX",
            "sector": "YES",
        },
    },
]
