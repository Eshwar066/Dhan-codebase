from enum import Enum


class RunMode(str, Enum):
    BACKTEST = "BACKTEST"
    PAPER = "PAPER"
    LIVE = "LIVE"


# 🔁 CHANGE ONLY THIS
RUN_MODE = RunMode.BACKTEST


STRATEGY_JOBS = [
    {
        "name": "LEAPS_RSI",
        "enabled": True,
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
        "enabled": False,
        "capital": 100000,
        "symbols": ["INFY", "ITC"],
        "backtest": {
            "start_date": "2023-01-01",
            "end_date": "2024-12-31",
        },
    },
]
