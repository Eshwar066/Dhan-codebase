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
}
