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
        "capital": 200_000,
        "symbols": ["NIFTY"],
        "backtest": {
            "start_date": "2022-01-01",
            "end_date": "2024-12-31",
            "timeframe": "60",
            "exchange": "NSE",
            "sector": "YES",
        },
    },
    {
        "name": "INSIDE_BAR",
        "enabled": False,
        "capital": 100_000,
        "symbols": ["INFY", "ITC"],
        "backtest": {
            "start_date": "2023-01-01",
            "end_date": "2024-12-31",
        },
    },
]
