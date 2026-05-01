from __future__ import annotations

from typing import Any, Optional

import pandas as pd

from core.models.strategy_context import StrategyContext
from core.strategies.IndiaMktMixins import IST, IndiaMktMixins
from core.strategies.base import BaseStrategy


class OptionBuildup(IndiaMktMixins, BaseStrategy):
    """
    Standalone snapshot strategy.

    Runs every 5 minutes and calls find_strike_in_premium_range for CE and PE.
    Snapshot params for option buildup output are injected via
    _find_strike_snapshot_params.
    """

    name = "OptionBuildup"
    timeframe = "5"
    required_context = ["option_chain"]
    api = "DHAN"
    expiryType = "MONTHLY"
    otm_strike_step = 100
    otm_strike_count = 35


    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._option_buildup_logged_slots = set()

    def get_warmup_period(self):
        return 0

    def should_evaluate(self, candle: dict) -> bool:
        ts_ist = self._candle_ts_ist(candle)
        return int(ts_ist.minute) % 5 == 0

    def run_snapshot_cycle(
        self,
        *,
        symbol: str,
        exchange: str,
        spot_price: float,
        ts_utc: Any,
        option_chain_service: Any,
    ) -> None:
        """
        Direct scheduler entrypoint: no engine candle/websocket dependency.
        """
        candle = {
            "symbol": str(symbol),
            "exchange": str(exchange),
            "close": float(spot_price),
            "timestamp": pd.Timestamp(ts_utc),
        }
        ctx = StrategyContext(
            symbol=str(symbol),
            exchange=str(exchange),
            timestamp=pd.Timestamp(ts_utc).to_pydatetime(),
            spot_price=float(spot_price),
            instrument_store=None,
            position_store=None,
            option_chain_service=option_chain_service,
        )
        if not self.should_evaluate(candle):
            return
        self.get_option_chain_snapshot(candle, ctx, "CE")
        self.get_option_chain_snapshot(candle, ctx, "PE")


    def _candle_ts_ist(self, candle: dict) -> pd.Timestamp:
        ts_ist = pd.Timestamp(candle["timestamp"])
        if ts_ist.tzinfo is None:
            ts_ist = ts_ist.tz_localize(IST)
        else:
            ts_ist = ts_ist.tz_convert(IST)
        return ts_ist

    def _find_strike_snapshot_params(self, candle, ctx, option_type):
        ts_ist = self._candle_ts_ist(candle)
        is_five_min_slot = int(ts_ist.minute) % 5 == 0
        if not is_five_min_slot:
            return {}

        snapshot_date = ts_ist.strftime("%Y-%m-%d")
        snapshot_time = ts_ist.strftime("%H-%M")
        slot_key = "|".join(
            [
                str(getattr(ctx, "symbol", "") or ""),
                str(option_type or ""),
                snapshot_date,
                snapshot_time,
            ]
        )
        if slot_key in self._option_buildup_logged_slots:
            return {}

        self._option_buildup_logged_slots.add(slot_key)
        return {
            "snapshot": True,
            "snapshot_date": snapshot_date,
            "snapshot_time": snapshot_time,
            "snapshot_target": "option_buildup",
        }
