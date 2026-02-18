from run.config import RunMode

STRATEGY_RUNTIME_SPEC = {
    "INSIDE_BAR": {
        RunMode.BACKTEST: {
            "data": {
                "ohlc": {"exchange": "NSE", "interval": "5"},
            }
        },
        RunMode.PAPER: {
            "data": {
                "ohlc": {"exchange": "NSE", "interval": "1"},
            }
        },
        RunMode.LIVE: {
            "data": {
                "ohlc": {"exchange": "NSE", "interval": "1"},
            }
        },
    },
    "LEAPS_RSI": {
        RunMode.BACKTEST: {
            "data": {
                "option_chain": {
                    "exchange": "NSE",
                    "interval": "60",  # 1hr candle
                    "segment": "OPT",
                    "api": "DHAN",
                    "expiry_flag": "MONTHLY",
                }
            }
        },
        RunMode.LIVE: {
            "data": {
                "option_chain": {
                    "exchange": "NSE",
                    "interval": "1",  # live
                    "segment": "OPT",
                }
            }
        },
    },
    "SignalFloodTest": {
        RunMode.PAPER: {"data": {}},
        RunMode.LIVE: {"data": {}},
    },
}
