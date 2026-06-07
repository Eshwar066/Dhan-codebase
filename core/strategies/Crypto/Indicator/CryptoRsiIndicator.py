"""
Crypto RSI indicator alerts (BTC + ETH, 1m).

Rules (see readme.md in this folder)
- Compute RSI(14) on every 1m candle.
- Telegram alert when RSI crosses **above 70** or **below 30**.
- Alert-only: no orders are placed.
"""

from __future__ import annotations

from typing import Any, Callable, List, Optional

import pandas as pd
import talib

from run.config import RUN_MODE, RunMode
from core.strategies.base import BaseStrategy
from core.strategies.indicator_helpers import default_persisted_keys_for_rsi
from core.utils.telegram_alert import send_telegram_alert

RSI_PERIOD = 14
RSI_OVERBOUGHT = 70.0
RSI_OVERSOLD = 30.0


class CryptoRsiIndicator(BaseStrategy):
    """Delta crypto RSI cross alerts to Telegram (BTCUSD, ETHUSD)."""

    name = "CryptoRsiIndicator"
    timeframe = "1"
    required_context = []
    api = "DELTA"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.telegram_alert: Optional[Callable[[str], None]] = None
        self.telegram_bot_token: Optional[str] = None
        self.telegram_chat_id: Optional[str] = None

    def get_warmup_period(self):
        return RSI_PERIOD + 2

    def prepare_indicators(self, df):
        df["rsi"] = talib.RSI(df["close"], RSI_PERIOD)
        df["prev_rsi"] = df["rsi"].shift(1)
        return df

    def requires_live_rsi_patch(self) -> bool:
        return True

    def persisted_indicator_keys(self) -> List[str]:
        return default_persisted_keys_for_rsi()

    @staticmethod
    def _crossed_above(prev: float, curr: float, level: float) -> bool:
        return prev < level <= curr

    @staticmethod
    def _crossed_below(prev: float, curr: float, level: float) -> bool:
        return prev > level >= curr

    def _send_alert(self, message: str) -> None:
        if RUN_MODE == RunMode.BACKTEST:
            print(f"[{self.name}] {message}")
            return
        alert_fn = getattr(self, "telegram_alert", None)
        if callable(alert_fn):
            alert_fn(message)
            return
        token = getattr(self, "telegram_bot_token", None)
        chat = getattr(self, "telegram_chat_id", None)
        if token and chat:
            send_telegram_alert(message, str(chat), str(token))

    def should_evaluate(self, candle) -> bool:
        if candle.get("indicator_signals_ready") is False:
            return False
        rsi = candle.get("rsi")
        prev = candle.get("prev_rsi")
        if pd.isna(rsi) or pd.isna(prev):
            return False
        prev_f = float(prev)
        rsi_f = float(rsi)
        return self._crossed_above(prev_f, rsi_f, RSI_OVERBOUGHT) or self._crossed_below(
            prev_f, rsi_f, RSI_OVERSOLD
        )

    def on_candle(self, candle, ctx: Any):
        del ctx
        rsi = float(candle["rsi"])
        prev = float(candle["prev_rsi"])
        symbol = str(candle.get("symbol") or "")
        ts = candle.get("timestamp")
        close = float(candle.get("close") or 0.0)

        if self._crossed_above(prev, rsi, RSI_OVERBOUGHT):
            self._send_alert(
                f"RSI OVERBOUGHT | {symbol} | RSI crossed above {RSI_OVERBOUGHT:.0f} "
                f"({prev:.2f} -> {rsi:.2f}) | close={close:.2f} | {ts}"
            )
        elif self._crossed_below(prev, rsi, RSI_OVERSOLD):
            self._send_alert(
                f"RSI OVERSOLD | {symbol} | RSI crossed below {RSI_OVERSOLD:.0f} "
                f"({prev:.2f} -> {rsi:.2f}) | close={close:.2f} | {ts}"
            )
        return None
