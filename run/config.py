from enum import Enum


class RunMode(str, Enum):
    BACKTEST = "BACKTEST"
    PAPER = "PAPER"
    LIVE = "LIVE"


# 🔁 Default run mode when a job does not specify "run_mode".
RUN_MODE = RunMode.LIVE

# Global fallback: entry quantity in lots (used when a job does not override).
ORDER_QTY_LOTS = 1

# Default venue when job does not specify "venue". Used for single-venue runs.
DEFAULT_VENUE = "DHAN"  # "DHAN" | "DELTA"

# Stdlib logging defaults (override with job "log_level" / "library_log_level" or ALGO_LOG_LEVEL / ALGO_LIBRARY_LOG_LEVEL).
DEFAULT_ROOT_LOG_LEVEL = "INFO"
DEFAULT_LIBRARY_LOG_LEVEL = "WARNING"

# Per-job run_mode: set "run_mode": "PAPER" or "run_mode": "LIVE" (or "BACKTEST") on each job.
# If omitted, RUN_MODE above is used. You can run some strategies in paper and others in live in the same process.
STRATEGY_JOBS = [
    # leaps rsi 52 32 for dhan
    {
        "name": "LEAPS_RSI",
        "venue": "DHAN",
        "enabled": False,
        # "run_mode": "PAPER",  # or "LIVE"; omit to use RUN_MODE default
        "capital": 200000,
        "symbols": ["NIFTY"],
        "live": {"exchange": "INDEX", "sector": "YES", "rsi": "YES"},
        "backtest": {
            "start_date": "2023-10-19",
            "end_date": "2026-02-20",
            "timeframe": "60",
            "exchange": "INDEX",
            "sector": "YES",
        },
    },
    {
        "name": "MagicalLines",
        "venue": "DHAN",
        "enabled": False,
        "capital": 200000,
        "symbols": ["NIFTY"],
        "live": {"exchange": "INDEX", "sector": "YES"},
        "backtest": {
            "start_date": "2026-01-01",
            "end_date": "2026-02-19",
            "timeframe": "DAY",
            "exchange": "INDEX",
            "sector": "YES",
        },
    },
    # Nifty intraday magical line: entry on 15m 9:15–9:30 (close 9:30); SL on 1h :15 closes (10:15…15:15); 15:15 square-off;
    # monthly expiry (rollover after 15th), delta band + premium fallback. Dhan / NSE chain.
    {
        "name": "NiftyIntradayMagicalLine",
        "venue": "DHAN",
        "enabled": True,
        "ORDER_QTY_LOTS": 1,
        "run_mode": "LIVE",  # or "LIVE"; omit to use RUN_MODE default
        "capital": 200000,
        "symbols": ["NIFTY"],
        "instrument": "OPTION",
         "telegram": {
            "bot_token": "8663481671:AAHY-OnE8OiaJmkOfXbwqoe4InosJVblAtM",
            "chat_id": "1021479950",
        },
        "live": {"exchange": "INDEX", "sector": "YES"},
        "backtest": {
            "start_date": "2025-01-1",
            "end_date": "2025-06-30",
            "timeframe": "15",
            "exchange": "INDEX",
            "sector": "YES",
        },
    },
    {
        "name": "IPOBreakout",
        "venue": "DHAN",
        "enabled": False,
        "engine_id": "dhan_ipo_breakout",
        "capital": 200000,
        "symbols": None,
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
        "name": "SignalFloodTest",
        "venue": "DHAN",
        "enabled": False,
        "engine_id": "dhan_test_pipeline",
        "capital": 10000,
        "symbols": ["NIFTY"],
        "instrument": "FUTURES",
        "daily_max_loss": 100,
        "max_open_positions": 1,
        "max_portfolio_exposure": 5000,
        "cooldown_seconds": 5,
        "risk_per_trade_percent": 0.5,
        "check_short_option_margin_enabled": False,
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
    # OneDayMagicalLine: DELTA BTC options (sell CE/PE; buy to close / exits). Same wiring as FuturesEMAHighLow / SignalFloodTest (DELTA).
    # Backtest: omit run_mode (uses RUN_MODE). Live: add "run_mode": "LIVE".
    # Testnet: delta_testnet True + DEMO_DELTA_API_KEY / DEMO_DELTA_API_SECRET | Mainnet live: delta_testnet False + DELTA_API_KEY / DELTA_API_SECRET.
    {
        "name": "OneDayMagicalLine",
        "venue": "DELTA",
        "enabled": True,
        "run_mode": "LIVE",  # uncomment for Delta paper/live; omit for backtest (uses RUN_MODE)
        "capital": 200000,
        "symbols": ["BTCUSD"],
        "instrument": "OPTION",
        "delta_india": True,
        "delta_testnet": False,
        "delta_leverage": 10,
        "max_open_positions": 5,
        "check_short_option_margin_enabled": True,
        "telegram": {
            "bot_token": "8389724629:AAHY_CGcBF8HZCexedsEJFw80Mf6SxH5Bkk",
            "chat_id": "1021479950",
        },
        "live": {"exchange": "DELTA", "sector": "YES"},
        "backtest": {
            "start_date": "2026-02-01",
            "end_date": "2026-02-26",
            "timeframe": "60",
            "exchange": "DELTA",
            "sector": "YES",
        },
    },
    # ema 5, 0.7 for profit  and 0.3 for loss used both for nifty and btc, etc
    {
        "name": "FuturesEMAHighLow",
        "venue": "DELTA",
        "enabled": False,
        "capital": 200000,
        "symbols": ["BTCUSD"],
        "instrument": "FUTURES",
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
    # dont use this
    {
        "name": "Futures_EMA_Momentum",
        "venue": "DELTA",
        "enabled": False,
        "engine_id": "delta_futures_ema_momentum",
        "capital": 200000000,
        "symbols": ["BTCUSD"],
        "instrument": "FUTURES",
        "delta_india": True,
        "delta_testnet": False,
        "delta_leverage": 1,
        "live": {"exchange": "INDEX", "sector": "YES"},
        "backtest": {
            "start_date": "2024-09-01",  # dont go below this in delta exchange "2024-02-01"
            "end_date": "2026-03-13",
            "timeframe": "60",
        },
    },
    {
        "name": "SignalFloodTest",
        "venue": "DELTA",
        "enabled": False,
        "run_mode": "LIVE",
        "engine_id": "delta_test_pipeline",
        "symbols": ["BTCUSD"],
        "instrument": "FUTURES",
        "delta_india": True,
        "delta_testnet": True,
        "delta_leverage": 10,
        "capital": 10000,
        "daily_max_loss": 10000,  # not in engine
        "max_open_positions": 6,  # not in engine
        "max_portfolio_exposure": 1000,  # In Engine (RiskManager)
        "cooldown_seconds": 5,
        "risk_per_trade_percent": 1.0,
        "check_short_option_margin_enabled": False,  # futures-only; no option margin check
        "feed_stale_seconds": 30,  # In Engine
        "order_state_check_interval_min": 1,  # In engine
        "memory_threshold_percent": 5,  # In engine
        "latency_critical_ms": 6000,  # In engine
        "latency_critical_cycles": 6,  # In engine
        "symbol_error_threshold": 6,  # In engine
        # "strategy_timeout_seconds": 1000000000, # do we need this
        "live": {"exchange": "DELTA", "sector": "YES"},
        "telegram": {
            "bot_token": "8389724629:AAHY_CGcBF8HZCexedsEJFw80Mf6SxH5Bkk",
            "chat_id": "1021479950",
        },
        "backtest": {
            "start_date": "2024-03-20",
            "end_date": "2024-03-25",
            "timeframe": "1",
            "exchange": "DELTA",
            "sector": "YES",
        },
    },
]
