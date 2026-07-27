"""Shared constants for DirectionalOptionSelling."""

from datetime import time

SUPER_TREND_LENGTH = 16
SUPER_TREND_FACTOR = 1.5
MIN_PREMIUM_USD = 120
# Morning 08:30 0DTE sleeve: lower premium floor (deep OTM / cheaper book).
MIN_PREMIUM_USD_MORNING = 20
# Broker MAIN_SL trails SuperTrend on the spot index: bullish ST-100 / bearish ST+100.
TRAIL_SL_POINTS = 100.0
# Initial MAIN_SL: option mark stop at entry_premium × this multiplier (short cover).
PREMIUM_SL_MULT = 2.0
# MAIN_SL mode: start on option mark; switch once to index/ST trail when green + ST favors.
SL_MODE_PREMIUM = "premium"
SL_MODE_INDEX = "index"
# Strategy emergency: if spot breaches ST±300 and the position is still open, fire LIMIT exit.
FORCE_EXIT_POINTS = 300.0
# Extra risk: if spot trades within ±50 of the open option strike, exit immediately.
STRIKE_PROXIMITY_EXIT_POINTS = 50.0
# Morning / daily ENTRY: require |strike − spot| ≥ this so we don't sell into the
# proximity-exit band (skip nearer strikes and fall through to the next eligible).
MIN_STRIKE_SPOT_DISTANCE = 400.0
ROLLOVER_TIME = time(17, 25)
ROLLOVER_MIN_STRIKE_DISTANCE = 200.0
# Sleeve-specific entry size (lots). Weekly = 4H HTF entry; daily = 1H flip entry.
ORDER_QTY_LOTS_WEEKLY = 50
ORDER_QTY_LOTS_DAILY = 10
# 08:30 IST scheduled 0DTE entry (1H SuperTrend only; no 4H/1D filter).
ORDER_QTY_LOTS_MORNING = 10
# Backward-compatible alias (daily sleeve).
ORDER_QTY_LOTS = ORDER_QTY_LOTS_DAILY
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
# Weekly entry: if selected Friday is within 2 DTE, roll to next weekly Friday.
WEEKLY_MIN_DTE = 3
# Monthly entry: if selected last-Friday is within this DTE, roll to next month.
MONTHLY_MIN_DTE = 7
# Broker MAIN_SL trail modify: loud failure + retries when ST moved but SL did not.
TRAIL_SL_MODIFY_ATTEMPTS = 3
TRAIL_SL_IMMEDIATE_RETRY_SLEEP_SEC = 0.35
TRAIL_SL_PENDING_RETRY_GAP_SEC = 5.0
