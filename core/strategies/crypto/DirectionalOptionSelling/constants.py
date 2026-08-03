"""Shared constants for DirectionalOptionSelling (symbol-wise knobs)."""

from __future__ import annotations

from datetime import time
from typing import Any, Dict, Mapping

SUPER_TREND_LENGTH = 16
SUPER_TREND_FACTOR = 1.5
# Broker MAIN_SL mode: start on option mark; switch once to index/ST trail when green + ST favors.
SL_MODE_PREMIUM = "premium"
SL_MODE_INDEX = "index"
ROLLOVER_TIME = time(17, 25)
META_KEY = "directional_option_selling"
# Higher-TF SuperTrend: weekly on 1D+4H align; daily on 1H with 1D+4H filter.
HTF_TIMEFRAMES = ("4h", "1d")
HTF_LOOKBACK_DAYS = {"4h": 45, "1d": 120}
SLEEVE_WEEKLY = "weekly"
SLEEVE_DAILY = "daily"
# Clock-slot 0DTE short on 1H SuperTrend (gated by ENABLE_MORNING_0DTE_TRADES).
SLEEVE_MORNING = "morning"
# 1D SuperTrend flip → monthly (last Friday) expiry; gated by ENABLE_MONTHLY_TRADES.
SLEEVE_MONTHLY = "monthly"
MORNING_ENTRY_TIME = time(9, 30)
# Broker MAIN_SL trail modify: loud failure + retries when ST moved but SL did not.
TRAIL_SL_MODIFY_ATTEMPTS = 3
TRAIL_SL_IMMEDIATE_RETRY_SLEEP_SEC = 0.35
TRAIL_SL_PENDING_RETRY_GAP_SEC = 5.0
# Buy-to-cover stop-LIMIT: limit must be above trigger, but not more than this.
MAIN_SL_LIMIT_ABOVE_TRIGGER_MAX = 10.0
# Default bump when live ask is at/below trigger (strictly limit > trigger).
MAIN_SL_LIMIT_ABOVE_TRIGGER_MIN = 1.0

# ---------------------------------------------------------------------------
# Per-underlying knobs (BTC vs ETH differ in $ premium / absolute point scales).
# ---------------------------------------------------------------------------
_SYMBOL_CONFIG_BTC: Dict[str, Any] = {
    "option_root": "BTC",
    "enabled": True,
    "min_premium_usd": 120.0,
    "min_premium_usd_morning": 20.0,
    "min_strike_spot_distance": 400.0,
    # Morning 0DTE: strike must be at least this far from 1H SuperTrend.
    "morning_min_strike_distance": 100.0,
    "rollover_min_strike_distance": 200.0,
    "trail_sl_points": 100.0,
    "force_exit_points": 300.0,
    "strike_proximity_exit_points": 50.0,
    "premium_sl_mult": 2.0,
    "order_qty_lots_weekly": 1,
    "order_qty_lots_monthly": 1,
    "order_qty_lots_daily": 10,
    "order_qty_lots_morning": 200,
    "weekly_min_dte": 3,
    "monthly_min_dte": 7,
    "enable_weekly_deeper_otm": True,
    "enable_weekly": True,
    "enable_monthly": True,
    "enable_intraday": True,
    "enable_morning": True,
}

# ETH scaled ~spot ratio vs BTC (~1/18–1/20). Tune live as needed.
_SYMBOL_CONFIG_ETH: Dict[str, Any] = {
    "option_root": "ETH",
    "enabled": False,
    "min_premium_usd": 8.0,
    "min_premium_usd_morning": 2.0,
    "min_strike_spot_distance": 20.0,
    # ~BTC 100 scaled by spot (~1/20).
    "morning_min_strike_distance": 5.0,
    "rollover_min_strike_distance": 10.0,
    "trail_sl_points": 5.0,
    "force_exit_points": 15.0,
    "strike_proximity_exit_points": 3.0,
    "premium_sl_mult": 2.0,
    "order_qty_lots_weekly": 5,
    "order_qty_lots_monthly": 5,
    "order_qty_lots_daily": 5,
    "order_qty_lots_morning": 10,
    "weekly_min_dte": 3,
    "monthly_min_dte": 7,
    "enable_weekly_deeper_otm": True,
    "enable_weekly": True,
    "enable_monthly": True,
    "enable_intraday": True,
    "enable_morning": True,
}

SYMBOL_CONFIG: Dict[str, Dict[str, Any]] = {
    "BTCUSD": dict(_SYMBOL_CONFIG_BTC),
    "ETHUSD": dict(_SYMBOL_CONFIG_ETH),
}

SUPPORTED_UNDERLYINGS = tuple(SYMBOL_CONFIG.keys())

# Backward-compatible module aliases (BTC defaults) for imports / older call sites.
MIN_PREMIUM_USD = float(_SYMBOL_CONFIG_BTC["min_premium_usd"])
MIN_PREMIUM_USD_MORNING = float(_SYMBOL_CONFIG_BTC["min_premium_usd_morning"])
TRAIL_SL_POINTS = float(_SYMBOL_CONFIG_BTC["trail_sl_points"])
PREMIUM_SL_MULT = float(_SYMBOL_CONFIG_BTC["premium_sl_mult"])
FORCE_EXIT_POINTS = float(_SYMBOL_CONFIG_BTC["force_exit_points"])
STRIKE_PROXIMITY_EXIT_POINTS = float(_SYMBOL_CONFIG_BTC["strike_proximity_exit_points"])
MIN_STRIKE_SPOT_DISTANCE = float(_SYMBOL_CONFIG_BTC["min_strike_spot_distance"])
MORNING_MIN_STRIKE_DISTANCE = float(
    _SYMBOL_CONFIG_BTC["morning_min_strike_distance"]
)
ROLLOVER_MIN_STRIKE_DISTANCE = float(_SYMBOL_CONFIG_BTC["rollover_min_strike_distance"])
ORDER_QTY_LOTS_WEEKLY = int(_SYMBOL_CONFIG_BTC["order_qty_lots_weekly"])
ORDER_QTY_LOTS_MONTHLY = int(_SYMBOL_CONFIG_BTC["order_qty_lots_monthly"])
ORDER_QTY_LOTS_DAILY = int(_SYMBOL_CONFIG_BTC["order_qty_lots_daily"])
ORDER_QTY_LOTS_MORNING = int(_SYMBOL_CONFIG_BTC["order_qty_lots_morning"])
ORDER_QTY_LOTS = ORDER_QTY_LOTS_DAILY
WEEKLY_MIN_DTE = int(_SYMBOL_CONFIG_BTC["weekly_min_dte"])
MONTHLY_MIN_DTE = int(_SYMBOL_CONFIG_BTC["monthly_min_dte"])


def normalize_underlying(symbol: Any) -> str:
    """Normalize to BTCUSD / ETHUSD; unknown symbols left uppercased."""
    raw = str(symbol or "").strip().upper()
    if not raw:
        return "BTCUSD"
    if raw in SYMBOL_CONFIG:
        return raw
    # Option roots / short names.
    if raw in ("BTC", "XBT"):
        return "BTCUSD"
    if raw == "ETH":
        return "ETHUSD"
    return raw


def symbol_config(symbol: Any = None) -> Mapping[str, Any]:
    """Return knobs for ``symbol``; falls back to BTCUSD when unknown."""
    sym = normalize_underlying(symbol)
    cfg = SYMBOL_CONFIG.get(sym)
    if cfg is not None:
        return cfg
    return SYMBOL_CONFIG["BTCUSD"]


def option_root_for(symbol: Any = None) -> str:
    return str(symbol_config(symbol)["option_root"])


def underlying_from_option_symbol(trading_symbol: Any) -> str | None:
    """Map ``P-BTC-64000-...`` / ``C-ETH-...`` → BTCUSD / ETHUSD."""
    parts = str(trading_symbol or "").strip().upper().split("-")
    if len(parts) < 2:
        return None
    root = parts[1]
    for under, cfg in SYMBOL_CONFIG.items():
        if str(cfg.get("option_root") or "").upper() == root:
            return under
    if root in ("BTC", "XBT"):
        return "BTCUSD"
    if root == "ETH":
        return "ETHUSD"
    return None
