from run.config import RunMode

STRATEGY_RUNTIME_SPEC = {
    "IPOBreakout": {
        RunMode.BACKTEST: {
            "data": {"ohlc": {"exchange": "NSE", "interval": "5"}},
        },
        RunMode.PAPER: {
            "data": {"ohlc": {"exchange": "NSE", "interval": "5"}},
        },
        RunMode.LIVE: {
            "data": {"ohlc": {"exchange": "NSE", "interval": "5"}},
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
    "BankNiftyBTST": {
        RunMode.BACKTEST: {
            "data": {
                "option_chain": {
                    "exchange": "NSE",
                    "interval": "5",
                    "segment": "OPT",
                    "api": "DHAN",
                    "expiry_flag": "MONTHLY",
                }
            }
        },
        RunMode.PAPER: {
            "data": {
                "option_chain": {
                    "exchange": "NSE",
                    "interval": "5",
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
                    "interval": "1",
                    "segment": "OPT",
                }
            }
        },
    },
    "OneDayMagicalLine": {
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
    "NiftyIntradayMagicalLine": {
        RunMode.BACKTEST: {
            "data": {
                "option_chain": {
                    "exchange": "NSE",
                    "interval": "15",
                    "segment": "OPT",
                    "api": "DHAN",
                    "expiry_flag": "MONTHLY",
                }
            }
        },
        RunMode.PAPER: {
            "data": {
                "option_chain": {
                    "exchange": "NSE",
                    "interval": "15",
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
                    "interval": "1",
                    "segment": "OPT",
                }
            }
        },
    },
    "MagicalLines": {
        RunMode.BACKTEST: {
            "data": {
                "option_chain": {
                    "exchange": "NSE",
                    "interval": "DAY",
                    "segment": "OPT",
                    "api": "DHAN",
                    "expiry_flag": "MONTHLY",
                }
            }
        },
        RunMode.PAPER: {
            "data": {
                "option_chain": {
                    "exchange": "NSE",
                    "interval": "DAY",
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
                    "interval": "1",
                    "segment": "OPT",
                }
            }
        },
    },
    "OIPositionalBuy": {
        RunMode.BACKTEST: {
            "data": {
                "option_chain": {
                    "exchange": "NSE",
                    "interval": "15",
                    "segment": "OPT",
                    "api": "DHAN",
                    "expiry_flag": "MONTHLY",
                }
            }
        },
        RunMode.PAPER: {
            "data": {
                "option_chain": {
                    "exchange": "NSE",
                    "interval": "15",
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
                    "interval": "15",
                    "segment": "OPT",
                    "api": "DHAN",
                    "expiry_flag": "MONTHLY",
                }
            }
        },
    },
    "Futures_EMA_Momentum": {
        RunMode.BACKTEST: {"data": {}},
        RunMode.PAPER: {"data": {}},
        RunMode.LIVE: {"data": {}},
    },
    "SignalFloodTest": {
        RunMode.PAPER: {"data": {}},
        RunMode.LIVE: {"data": {}},
    },
    "CryptoRsiIndicator": {
        RunMode.BACKTEST: {"data": {}},
        RunMode.PAPER: {"data": {}},
        RunMode.LIVE: {"data": {}},
    },
}
