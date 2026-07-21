"""Shared constants for DirectionalOptionSelling."""

from datetime import time

SUPER_TREND_LENGTH = 16
SUPER_TREND_FACTOR = 1.5
MIN_PREMIUM_USD = 120
# Broker MAIN_SL trails SuperTrend on the spot index: bullish ST-100 / bearish ST+100.
TRAIL_SL_POINTS = 100.0
# Strategy emergency: if spot breaches ST±300 and the position is still open, fire LIMIT exit.
FORCE_EXIT_POINTS = 300.0
# Extra risk: if spot trades within ±50 of the open option strike, exit immediately.
STRIKE_PROXIMITY_EXIT_POINTS = 50.0
ROLLOVER_TIME = time(17, 25)
ROLLOVER_MIN_STRIKE_DISTANCE = 200.0
ORDER_QTY_LOTS = 2
META_KEY = "directional_option_selling"
# Higher-TF SuperTrend: weekly on 1D+4H align; daily on 1H with 1D+4H filter.
HTF_TIMEFRAMES = ("4h", "1d")
HTF_LOOKBACK_DAYS = {"4h": 45, "1d": 120}
SLEEVE_WEEKLY = "weekly"
SLEEVE_DAILY = "daily"
# Weekly entry: if selected Friday is within 2 DTE, roll to next weekly Friday.
WEEKLY_MIN_DTE = 3
# Broker MAIN_SL trail modify: loud failure + retries when ST moved but SL did not.
TRAIL_SL_MODIFY_ATTEMPTS = 3
TRAIL_SL_IMMEDIATE_RETRY_SLEEP_SEC = 0.35
TRAIL_SL_PENDING_RETRY_GAP_SEC = 5.0
