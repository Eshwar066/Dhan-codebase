from enum import Enum


class RunMode(str, Enum):
    BACKTEST = "BACKTEST"
    PAPER = "PAPER"
    LIVE = "LIVE"


# 🔁 Default run mode when a job does not specify "run_mode".
RUN_MODE = RunMode.PAPER

# Global fallback: entry quantity in lots (used when a job does not override).
ORDER_QTY_LOTS = 1

# Default venue when job does not specify "venue". Used for single-venue runs.
DEFAULT_VENUE = "DHAN"  # "DHAN" | "DELTA"

# Stdlib logging defaults (override with job "log_level" / "library_log_level" or ALGO_LOG_LEVEL / ALGO_LIBRARY_LOG_LEVEL).
DEFAULT_ROOT_LOG_LEVEL = "INFO"
DEFAULT_LIBRARY_LOG_LEVEL = "WARNING"

# Global debug toggle for high-frequency diagnostic logs (e.g. per-tick logs).
DEBUG_MODE = False

# New architecture: one job per engine, multiple strategies per engine.
# Each engine job shares venue/broker/risk/pipeline settings, and strategy list defines
# what the engine loads concurrently.
ENGINE_JOBS = [
    {
        "engine_id": "dhan_leaps_rsi",
        "venue": "DHAN",
        "enabled": True,
        "run_mode": "PAPER",
        "capital": 200000,
        "ORDER_QTY_LOTS": 1,
        "symbols": ["NIFTY"],
        "exchange": "NSE",
        # "symbols": ["GOLD"],
        # "exchange": "MCX",
        "market_ws_stall_timeout_seconds": 0,
        "telegram": {
            "bot_token": "8663481671:AAHY-OnE8OiaJmkOfXbwqoe4InosJVblAtM",
            "chat_id": "1021479950",
        },
        
        "strategies": ["LEAPS_RSI",], #"NiftyIntradayMagicalLine"
        "live": {"exchange": "INDEX", "sector": "YES", "rsi": "YES"},
        # "live": {"exchange": "MCX", "sector": "NO", "rsi": "YES"},
        "backtest": {
            "start_date": "2026-04-24",
            "end_date": "2026-04-24",
            "timeframe": "60",
            "exchange": "INDEX",
            "sector": "YES",
        },
    },
    {
        "engine_id": "dhan_oi_positional_buy",
        "venue": "DHAN",
        "enabled": True,
        "run_mode": "LIVE",
        "capital": 200000,
        "ORDER_QTY_LOTS": 1,
        "symbols": ["NIFTY"],
        "exchange": "NSE",
        "strategies": ["OIPositionalBuy"],
        "live": {"exchange": "INDEX", "sector": "YES"},
        "backtest": {
            "start_date": "2026-04-01",
            "end_date": "2026-04-28",
            "timeframe": "15",
            "exchange": "INDEX",
            "sector": "YES",
        },
    },
    {
        "engine_id": "dhan_magicallines",
        "venue": "DHAN",
        "enabled": False,
        "capital": 200000,
        "symbols": ["NIFTY"],
        "strategies": ["MagicalLines"],
        "live": {"exchange": "INDEX", "sector": "YES"},
        "backtest": {
            "start_date": "2026-01-01",
            "end_date": "2026-02-19",
            "timeframe": "DAY",
            "exchange": "INDEX",
            "sector": "YES",
        },
    },
    {
        "engine_id": "dhan_ipo_breakout",
        "venue": "DHAN",
        "enabled": False,
        "capital": 200000,
        "symbols": None,
        "strategies": ["IPOBreakout"],
        "backtest": {
            "start_date": "2022-01-01",
            "end_date": "2026-02-20",
            "timeframe": "DAY",
            "exchange": "NSE",
            "sector": "NO",
            "ipo_days": 365,
            "ipo_filter": {"price_above": 200, "volume_above": 500000},
            "ipo_max_symbols": 50,
            "ipo_fallback_symbols": ["RELIANCE"],
        },
        "live": {
            "exchange": "NSE",
            "sector": "NO",
            "ipo_days": 365,
            "ipo_filter": {"price_above": 200, "volume_above": 500000},
            "ipo_max_symbols": 50,
        },
    },
    {
        "engine_id": "dhan_test_pipeline",
        "venue": "DHAN",
        "enabled": False,
        "run_mode": "LIVE",
        "capital": 10000,
        "symbols": ["GOLD"],
        "exchange": "MCX",
        "market_ws_stall_timeout_seconds": 0,
        "strategies": ["SignalFloodTest"],
        # Websocket-only run: keep core connectivity keys above and live config below.
        # "daily_max_loss": 100,
        # "max_open_positions": 1,
        # "max_portfolio_exposure": 5000,
        # "cooldown_seconds": 5,
        # "risk_per_trade_percent": 0.5,
        # "check_short_option_margin_enabled": False,
        # "feed_stale_seconds": 30,
        # "order_state_check_interval_min": 1,
        # "memory_threshold_percent": 5,
        # "latency_critical_ms": 50,
        # "latency_critical_cycles": 1,
        # "symbol_error_threshold": 2,
        "live": {"exchange": "MCX", "sector": "NO"},
        # "backtest": {
        #     "start_date": "2023-10-19",
        #     "end_date": "2023-10-25",
        #     "timeframe": "1",
        #     "exchange": "MCX",
        #     "sector": "NO",
        # },
    },
    {
        "engine_id": "delta_oneday_magicalline",
        "venue": "DELTA",
        "enabled": True,
        "run_mode": "LIVE",
        "capital": 200000,
        "symbols": ["BTCUSD"],
        "strategies": ["OneDayMagicalLine"],
        "delta_india": True,
        "delta_testnet": False,
        "delta_leverage": 10,
        "max_open_positions": 5,
        "telegram": {
            "bot_token": "8389724629:AAHY_CGcBF8HZCexedsEJFw80Mf6SxH5Bkk",
            "chat_id": "1021479950",
        },
        "check_short_option_margin_enabled": True,
        "live": {"exchange": "DELTA", "sector": "YES"},
        "backtest": {
            "start_date": "2026-02-01",
            "end_date": "2026-02-26",
            "timeframe": "60",
            "exchange": "DELTA",
            "sector": "YES",
        },
    },
    
    {
        "engine_id": "delta_futures_ema_highlow",
        "venue": "DELTA",
        "enabled": False,
        "capital": 200000,
        "symbols": ["BTCUSD"],
        "strategies": ["FuturesEMAHighLow"],
        "delta_india": True,
        "delta_testnet": False,
        "delta_leverage": 1,
        "live": {"exchange": "INDEX", "sector": "YES"},
        "backtest": {
            "start_date": "2024-02-01",
            "end_date": "2026-03-02",
            "timeframe": "60",
            "exchange": "INDEX",
            "sector": "YES",
        },
    },
    {
        "engine_id": "delta_futures_ema_momentum",
        "venue": "DELTA",
        "enabled": False,
        "capital": 200000000,
        "symbols": ["BTCUSD"],
        "strategies": ["Futures_EMA_Momentum"],
        "delta_india": True,
        "delta_testnet": False,
        "delta_leverage": 1,
        "live": {"exchange": "INDEX", "sector": "YES"},
        "backtest": {
            "start_date": "2024-09-01",
            "end_date": "2026-03-13",
            "timeframe": "60",
        },
    },
    {
        "engine_id": "delta_test_pipeline",
        "venue": "DELTA",
        "enabled": False,
        "run_mode": "LIVE",
        "capital": 10000,
        "symbols": ["BTCUSD"],
        "strategies": ["SignalFloodTest"],
        "delta_india": True,
        "delta_testnet": True,
        "delta_leverage": 10,
        "daily_max_loss": 10000,
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
        "backtest": {
            "start_date": "2024-03-20",
            "end_date": "2024-03-25",
            "timeframe": "1",
            "exchange": "DELTA",
            "sector": "YES",
        },
    },
]
