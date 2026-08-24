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
        "capital": 200000,
        "ORDER_QTY_LOTS": 1,
        "market_ws_stall_timeout_seconds": 0,
        "strategy_timeout_seconds": 60,
        "strategies": ["NiftyDOS"], #"NiftySMA9Weekly",, "BankNiftyBTST","LEAPS_RSI",
        "telegram": {
            "bot_token": os.getenv(
                "TELEGRAM_LEAPS_BOT_TOKEN",
                "8663481671:AAHY-OnE8OiaJmkOfXbwqoe4InosJVblAtM",
            ),
            "chat_id": os.getenv("TELEGRAM_LEAPS_CHAT_ID", "1021479950"),
        },
        # Factory default is 150ms; Dhan LIMIT round-trips are ~1s and were
        # leaving entries paused all session after the morning spike.
        "latency_critical_ms": 6000,
        "latency_critical_cycles": 6,

    },
    {
        "engine_id": "kotak",
        "venue": "DHAN",
        "enabled": False,
        "run_mode": "LIVE",
        "capital": 200000,
        "ORDER_QTY_LOTS": 1,
        "market_ws_stall_timeout_seconds": 0,
        "strategy_timeout_seconds": 60,
        "strategies": ["NiftyDOS"],
         "telegram": {
            "bot_token": os.getenv(
                "TELEGRAM_KOTAK_TOKEN",
                "8892391321:AAHOxQ2vRrXEe0Pz5Rn7hJRHX-GWYrbUOh4",
            ),
            "chat_id": os.getenv("TELEGRAM_OI_CHAT_ID", "1021479950"),
        },
          # Factory default is 150ms; Dhan LIMIT round-trips are ~1s and were
        # leaving entries paused all session after the morning spike.
        "latency_critical_ms": 6000,
        "latency_critical_cycles": 6,
    },
    {
        "engine_id": "delta_engine_one",
        "venue": "DELTA",
        "enabled": True,
        "run_mode": "LIVE",
        "capital": 200000,
        "strategies": [
            # "BTCZeroDTE",
            # "BTCZeroDTEElevenPM",
            "DirectionalOptionSelling",
            # "LiquiditySweepStrategy",
            # "RSIBreadAndButter",
        ],
        "max_open_positions": 15,
        "check_short_option_margin_enabled": True,
        # "ORDER_QTY_LOTS": 10,
        "delta_leverage": 100,
        "strategy_timeout_seconds": 60,
        "latency_critical_ms": 6000,
        "latency_critical_cycles": 6,
        # Delta OMS: reject ENTRY / MAIN_SL when book or mark is unsafe.
        "execution_validator": {
            "enabled": True,
            "max_spread_pct": 0.15,
            "max_mark_mid_pct": 0.50,
            "max_quote_age_sec": 30.0,
            "require_bid_ask": True,
            "require_mark": True,
            "allow_mark_fallback_to_mid": True,
            "default_sl_premium_mult": 2.0,
            "infer_entry_sl_from_default_mult": False,
            "min_stop_mark_ratio": 1.0,
            "validate_entry": True,
            "validate_stop": True,
        },
        # Block NEW ENTRY around high-impact USD macro events (±60m default).
        # Exits / FORCE_EXIT / MAIN_SL remain allowed. No network on trade path.
        "event_blackout": {
            "enabled": True,
            "minutes_before": 60,
            "minutes_after": 60,
            # On same-session HIGH events (e.g. FOMC ~23:30 IST): no 0DTE after
            # 17:30 IST; no 1DTE until the event blackout ends. DTE>=2 still OK
            # outside the ±60m window.
            "short_dte_rules_enabled": True,
            "zero_dte_cutoff_ist": "17:30",
            "block_1dte_until_event_done": True,
            "manual_yaml": "run/calendars/delta_event_blackout.yaml",
            "cache_json": "logs/calendars/delta_economic_events.json",
        },
        "telegram": {
            "bot_token": "8389724629:AAHY_CGcBF8HZCexedsEJFw80Mf6SxH5Bkk",
            "chat_id": "1021479950",
        },
    },
    
    {
        "engine_id": "dhan_oi_positional_buy",
        "venue": "DHAN",
        "enabled": False,
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

        "symbols": ["BTCUSD", "ETHUSD"],

    },

    {
        # Standalone LSS job — keep disabled while LiquiditySweepStrategy runs on
        # delta_engine_one (same LIVE account would double-enter).
        "engine_id": "delta_liquidity_sweep_bt",
        "venue": "DELTA",
        "enabled": False,
        "run_mode": "Live",
        "capital": 200000,
        "strategies": ["LiquiditySweepStrategy"],
        "symbols": ["BTCUSD","PAXGUSD"],
        "delta_india": True,
        "delta_testnet": False,
        "delta_leverage": 100,
        "ORDER_QTY_LOTS": 3,
        "backtest": {
            "start_date": "2026-07-19",
            "end_date": "2026-08-01",
            # Omit timeframe to use strategy entry_timeframe (params.entry_timeframe).
            # Or set explicitly to "1" / "5" to match strategy.yaml.
            "timeframe": "1",
            "exchange": "DELTA",
            "sector": "YES",
        },
    },

    {
        "engine_id": "kotak_nifty_intraday_magical_paper",
        "venue": "KOTAK",
        "enabled": False,
        "run_mode": "PAPER",
        "capital": 200_000,
        "ORDER_QTY_LOTS": 1,
        "strategies": ["NiftyIntradayMagicalLine"],
        "symbols": ["NIFTY"],
        "exchange": "INDEX",
    },

]


