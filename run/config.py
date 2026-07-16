import os

from enum import Enum





class RunMode(str, Enum):

    BACKTEST = "BACKTEST"

    PAPER = "PAPER"

    LIVE = "LIVE"





# Default run mode when an engine does not specify "run_mode".

RUN_MODE = RunMode.LIVE



# Global fallback: entry quantity in lots (used when engine/strategy does not override).

ORDER_QTY_LOTS = 1



# Default venue when engine does not specify "venue".

DEFAULT_VENUE = "DHAN"  # "DHAN" | "DELTA"



# Stdlib logging defaults (override per engine or via ALGO_LOG_LEVEL / ALGO_LIBRARY_LOG_LEVEL).

DEFAULT_ROOT_LOG_LEVEL = "INFO"

DEFAULT_LIBRARY_LOG_LEVEL = "WARNING"



DEBUG_MODE = False



# One engine job = one OS process. Strategy-level settings live in run/strategy_profiles.py.

ENGINE_JOBS = [
    {
        "engine_id": "dhan_leaps_rsi",
        "venue": "DHAN",
        "enabled": True,
        "run_mode": "LIVE",
        "capital": 200_000,
        "ORDER_QTY_LOTS": 1,
        "market_ws_stall_timeout_seconds": 0,
        "strategy_timeout_seconds": 60,
        "strategies": ["LEAPS_RSI", "BankNiftyBTST","NiftySMA9Weekly"],
        "telegram": {
            "bot_token": os.getenv(
                "TELEGRAM_LEAPS_BOT_TOKEN",
                "8663481671:AAHY-OnE8OiaJmkOfXbwqoe4InosJVblAtM",
            ),
            "chat_id": os.getenv("TELEGRAM_LEAPS_CHAT_ID", "1021479950"),
        },

    },
    {
        "engine_id": "delta_engine_one",
        "venue": "DELTA",
        "enabled": True,
        "run_mode": "LIVE",
        "capital": 200000,
        "strategies": [
            "BTCZeroDTE",
            "BTCZeroDTEElevenPM",
            # "RSIBreadAndButter",
        ],
        "max_open_positions": 8,
        "check_short_option_margin_enabled": True,
        "ORDER_QTY_LOTS": 10,
        "delta_leverage": 10,
        "latency_critical_ms": 6000,
        "latency_critical_cycles": 6,
        "telegram": {
            "bot_token": "8389724629:AAHY_CGcBF8HZCexedsEJFw80Mf6SxH5Bkk",
            "chat_id": "1021479950",
        },
    },
    {
        "engine_id": "dhan_sma9_weekly",
        "venue": "DHAN",
        "enabled": False,
        "run_mode": "LIVE",
        "capital": 200_000,
        "ORDER_QTY_LOTS": 1,
        "market_ws_stall_timeout_seconds": 0,
        "strategy_timeout_seconds": 60,
        "strategies": ["NiftySMA9Weekly"],
        "telegram": {
            "bot_token": os.getenv(
                "TELEGRAM_LEAPS_BOT_TOKEN",
                "8663481671:AAHY-OnE8OiaJmkOfXbwqoe4InosJVblAtM",
            ),
            "chat_id": os.getenv("TELEGRAM_LEAPS_CHAT_ID", "1021479950"),
        },
    },
    {
        "engine_id": "dhan_oi_positional_buy",
        "venue": "DHAN",
        "enabled": True,
        "run_mode": "PAPER",
        "capital": 200_000,
        "ORDER_QTY_LOTS": 1,
        "strategies": [
            "OIPositionalBuy",
            "NiftyIntradayMagicalLine",
            "FuturesEMAHighLow",
            "BankNiftyBTST",
        ],
        "telegram": {
            "bot_token": os.getenv(
                "TELEGRAM_OI_BOT_TOKEN",
                "8892391321:AAHOxQ2vRrXEe0Pz5Rn7hJRHX-GWYrbUOh4",
            ),
            "chat_id": os.getenv("TELEGRAM_OI_CHAT_ID", "1021479950"),
        },
    },

    {

        "engine_id": "delta_futures_ema_highlow",

        "venue": "DHAN",

        "enabled": False,

        "run_mode": "BACKTEST",

        "capital": 200_000,

        "strategies": ["FuturesEMAHighLow"],

        "delta_india": False,

        "delta_testnet": False,

        "delta_leverage": 1,

    },

    {

        "engine_id": "dhan_banknifty_btst",

        "venue": "DHAN",

        "enabled": True,

        "run_mode": "BACKTEST",

        "capital": 200_000,

        "ORDER_QTY_LOTS": 1,

        "strategies": ["BankNiftyBTST"],

    },

    {

        "engine_id": "dhan_nifty_intraday_magical",

        "venue": "DHAN",

        "enabled": False,

        "run_mode": "BACKTEST",

        "capital": 200_000,

        "ORDER_QTY_LOTS": 1,

        "strategies": ["NiftyIntradayMagicalLine"],

    },

    {

        "engine_id": "dhan_magicallines",

        "venue": "DHAN",

        "enabled": False,

        "capital": 200_000,

        "strategies": ["MagicalLines"],

    },

    {

        "engine_id": "dhan_ipo_breakout",

        "venue": "DHAN",

        "enabled": False,

        "capital": 200_000,

        "strategies": ["IPOBreakout"],

    },

    {

        "engine_id": "dhan_test_pipeline",

        "venue": "DHAN",

        "enabled": False,

        "run_mode": "LIVE",

        "capital": 10_000,

        "symbols": ["GOLD"],

        "exchange": "MCX",

        "market_ws_stall_timeout_seconds": 0,

        "strategies": ["SignalFloodTest"],

        "live": {"exchange": "MCX", "sector": "NO"},

    },

    {

        "engine_id": "delta_oneday_magicalline",

        "venue": "DELTA",

        "enabled": False,

        "run_mode": "LIVE",

        "capital": 200_000,

        "strategies": ["OneDayMagicalLine"],

        "max_open_positions": 5,

        "check_short_option_margin_enabled": True,

        "telegram": {

            "bot_token": "8389724629:AAHY_CGcBF8HZCexedsEJFw80Mf6SxH5Bkk",

            "chat_id": "1021479950",

        },

    },

   

    {

        "engine_id": "delta_futures_ema_momentum",

        "venue": "DELTA",

        "enabled": False,

        "capital": 200_000_000,

        "strategies": ["Futures_EMA_Momentum"],

    },

    {

        "engine_id": "delta_test_pipeline",

        "venue": "DELTA",

        "enabled": False,

        "run_mode": "LIVE",

        "capital": 10_000,

        "strategies": ["SignalFloodTest"],

        "delta_testnet": True,

        "delta_leverage": 10,

        "daily_max_loss": 10_000,

        "max_open_positions": 6,

        "max_portfolio_exposure": 1000,

        "cooldown_seconds": 5,

        "risk_per_trade_percent": 1.0,

        "check_short_option_margin_enabled": False,

        "feed_stale_seconds": 30,

        "order_state_check_interval_min": 1,

        "memory_threshold_percent": 5,

        "latency_critical_ms": 6000,

        "latency_critical_cycles": 6,

        "symbol_error_threshold": 6,

        "live": {"exchange": "DELTA", "sector": "YES"},

        "symbols": ["BTCUSD"],

    },

]


