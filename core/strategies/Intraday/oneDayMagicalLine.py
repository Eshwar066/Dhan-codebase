"""
BTCUSD One-Day Magical Line (Intraday Option Selling)

Rules (per user spec)
1. On 1hr candles, at `17:30` IST candle close mark spot as `ML1`.
2. At `17:30`, if candle is green (close > open) => short `PE` else short `CE`.
3. If market crosses `ML1`, reverse direction:
   - Currently short `PE` => reverse to short `CE` when spot crosses above ML1
   - Currently short `CE` => reverse to short `PE` when spot crosses below ML1
5. From short premium use 15% as SL:
   - If option premium rises by >= 15% from entry premium => exit (no reversal).

Implementation notes
- Uses `IndiaMktMixins` for option strike/premium selection and option LTP fetching.
- Delta product symbols via `DeltaMktMixins.delta_option_trading_symbol` (see `deltaMktMixins.py`).
- Reversal ENTRY is emitted from `on_candle` (engine expects entry intents from `on_candle`).
- ML1 is stored per opened position via `structure_id` to enable correct reversal + SL.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, time
from typing import Any, Dict, Optional, Tuple

import pandas as pd


from core.strategies.IndiaMktMixins import IndiaMktMixins
from core.strategies.deltaMktMixins import DeltaMktMixins
from core.strategies.base import BaseStrategy
from core.utils.expiry_resolver import ExpiryResolver
from run.config import RUN_MODE, RunMode, STRATEGY_JOBS


VALID_TIME_1730 = {time(21, 5)}  # 1hr candle close time (IST)

# Strike/premium selection (kept conservative and similar to `MagicalLines`)
STRIKE_STEP = 500
STRIKE_LOOKBACK = 5  # +/- 15 steps around ATM => 31 strikes
TARGET_PREMIUM_MIN = 700
TARGET_PREMIUM_MAX = 1500
TARGET_DELTA = 0.25
DELTA_RANGE = (0.2, 0.3)

# Risk
SL_PCT = 0.15  # 15% rise in short option premium triggers exit


@dataclass(frozen=True)
class _PosMeta:
    symbol: str
    entry_date: date
    ml1: float
    entry_premium: float
    level: int


class OneDayMagicalLine(IndiaMktMixins, DeltaMktMixins, BaseStrategy):
    """
    One-Day Magical Line strategy for intraday BTCUSD option selling.
    """

    name = "OneDayMagicalLine"
    timeframe = "1"  # change to 60min later
    required_context = ["option_chain"]
    api = "DELTA"
    expiryType = "Weekly"
    valid_times = VALID_TIME_1730
    delta = TARGET_DELTA
    delta_range = DELTA_RANGE

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._meta_by_structure_id: Dict[str, _PosMeta] = {}
        self._pending_exit_structure_ids: set[str] = set()
        self._reversal_level_counter: Dict[Tuple[str, date], int] = {}
        self._exit_reason_by_structure_id: Dict[str, str] = {}
        # For reversal cross detection in both backtest + live:
        # - `_last_spot_close_by_symbol` is the previous candle close (committed)
        # - `_pending_spot_close_by_symbol` is the current candle close (set in on_candle, committed next candle)
        self._last_spot_close_by_symbol: Dict[str, float] = {}
        self._pending_spot_close_by_symbol: Dict[str, float] = {}

    def get_warmup_period(self):
        return 0

    def _strategy_meta_dict(self, meta: _PosMeta) -> dict:
        return {
            "one_day_ml1": {
                "symbol": meta.symbol,
                "entry_date": meta.entry_date.isoformat(),
                "ml1": meta.ml1,
                "entry_premium": meta.entry_premium,
                "level": meta.level,
            }
        }

    def _restore_odml_meta_from_position(self, pos: Any, position_store: Any) -> None:
        if not pos or not getattr(pos, "structure_id", None):
            return
        if pos.structure_id in self._meta_by_structure_id:
            return
        sym = pos.instrument.trading_symbol
        bucket = position_store.get_position_metadata(sym)
        if not bucket:
            return
        raw = (bucket.get("strategy_meta") or {}).get("one_day_ml1")
        if not raw:
            return
        try:
            meta = _PosMeta(
                symbol=str(raw["symbol"]),
                entry_date=date.fromisoformat(str(raw["entry_date"])),
                ml1=float(raw["ml1"]),
                entry_premium=float(raw["entry_premium"]),
                level=int(raw["level"]),
            )
        except (KeyError, TypeError, ValueError):
            return
        self._meta_by_structure_id[pos.structure_id] = meta
        k = (meta.symbol, meta.entry_date)
        self._reversal_level_counter[k] = max(
            self._reversal_level_counter.get(k, 0), meta.level
        )

    def _is_delta_testnet_enabled(self) -> bool:
        for job in STRATEGY_JOBS:
            if str(job.get("name")) != self.name:
                continue
            if str(job.get("venue", "")).upper() != "DELTA":
                continue
            return bool(job.get("delta_testnet", False))
        return False

    # Strike selection: backtest = Delta tick CSV; live/paper = products + tickers (``deltaMktMixins``).
    # Branch uses ``run.config.RUN_MODE`` — for live engines set global ``RUN_MODE`` or ensure it matches the job.
    def find_strike_in_premium_range(
        self,
        candle,
        ctx,
        option_type,
        min_prem=600,
        max_prem=1500,
        lookback_sec=60,
    ):
        if RUN_MODE == RunMode.BACKTEST:
            return DeltaMktMixins.find_strike_in_premium_range(
                self,
                candle,
                ctx,
                option_type,
                min_prem=min_prem,
                max_prem=max_prem,
                lookback_sec=lookback_sec,
                expiry="Weekly",
            )
        if self._is_delta_testnet_enabled():
            return self.find_strike_in_premium_range_live(
                candle,
                ctx,
                option_type,
                min_prem=10,
                max_prem=30000,
                expiry="Weekly",
                side="SELL",
                lookback_sec=lookback_sec,
                target_delta=0.1,
                delta_min=0.01,
                delta_max=1,
                max_spread_ratio=20,
            )
        return DeltaMktMixins.find_strike_in_premium_range_live(
            self,
            candle,
            ctx,
            option_type,
            min_prem=min_prem,
            max_prem=max_prem,
            lookback_sec=lookback_sec,
            expiry="Weekly",
            side="SELL",
            target_delta=self.delta,
            delta_min=self.delta_range[0],
            delta_max=self.delta_range[1],
        )

    def find_strike_in_premium_range_live(
        self,
        candle,
        ctx,
        option_type,
        *,
        min_prem=600,
        max_prem=1500,
        lookback_sec=60,
        expiry="Weekly",
        side="SELL",
        target_delta=None,
        delta_min=None,
        delta_max=None,
        max_spread_ratio=0.15,
    ):
        return DeltaMktMixins.find_strike_in_premium_range_live(
            self,
            candle,
            ctx,
            option_type,
            min_prem=min_prem,
            max_prem=max_prem,
            lookback_sec=lookback_sec,
            expiry=expiry,
            side=side,
            target_delta=target_delta,
            delta_min=delta_min,
            delta_max=delta_max,
            max_spread_ratio=max_spread_ratio,
        )

    # ==================================================
    # TIME FILTER
    # ==================================================
    def should_evaluate(self, candle: dict):
        """
        Used by the engine mainly to decide whether to call `on_candle` + `should_exit`.

        For this strategy we need exit checks (reversal + SL) on every 1hr candle
        after entry, so we keep this permissive.
        """
        return True

    def should_enter(self, candle: dict) -> bool:
        """Only enter at `17:30` IST candle close."""
        ts = pd.to_datetime(candle["timestamp"])

        # return self._is_valid_time(ts, self.valid_times)
        return True

    def _direction_at_1730(self, candle: dict) -> str:
        open_ = float(candle.get("open", candle.get("close", 0)) or 0)
        close = float(candle.get("close", 0) or 0)
        # Green => short PE, else short CE
        return "SHORT_PE" if close > open_ else "SHORT_CE"

    def _option_type_for_direction(self, direction: str) -> str:
        return "PE" if direction == "SHORT_PE" else "CE"

    # ==================================================
    # ML1 CROSS DETECTION (uses stored prev candle close)
    # ==================================================
    def _is_reversal_cross(
        self,
        position: Any,
        candle: dict,
        ml1: float,
    ) -> bool:
        symbol = candle["symbol"]
        prev_close = self._last_spot_close_by_symbol.get(symbol)
        curr_close = float(candle["close"])
        if prev_close is None:
            return False

        opt_type = (position.instrument.option_type or "").upper()
        # For short PE position: reverse to CE when spot crosses above ML1
        if opt_type in ("PE", "PUT"):
            return prev_close <= ml1 and curr_close > ml1
        # For short CE position: reverse to PE when spot crosses below ML1
        if opt_type in ("CE", "CALL"):
            return prev_close >= ml1 and curr_close < ml1
        return False

    # ==================================================
    # STOPLOSS (15% rise in option premium)
    # ==================================================
    def _is_sl_triggered(
        self, position: Any, candle: dict, ctx: Any, meta: _PosMeta
    ) -> bool:
        curr_prem = self.get_option_price_at_candle(
            candle=candle,
            ctx=ctx,
            strike=position.instrument.strike,
            option_type=position.instrument.option_type,
            expiry=position.instrument.expiry,
            trading_symbol=position.instrument.trading_symbol,
        )
        if curr_prem is None:
            return False
        return curr_prem >= meta.entry_premium * (1.0 + SL_PCT)

    # ==================================================
    # ENTRY
    # ==================================================
    def on_candle(self, candle: dict, ctx: Any):
        """Lag diagnostics: set ``ALGO_LAG_DIAG=1`` (see ``cursor.md`` / ``core/utils/lag_diag.py``)."""
        from datetime import datetime

        from core.utils.lag_diag import IST, lag_diag_enabled

        _t0 = datetime.now(IST) if lag_diag_enabled() else None
        if _t0 is not None:
            print("🚀 on_candle start:", _t0)
        try:
            return self._on_candle_body(candle, ctx)
        finally:
            if _t0 is not None and lag_diag_enabled():
                print(
                    "⚙️ Strategy execution time (sec):",
                    (datetime.now(IST) - _t0).total_seconds(),
                )

    def _on_candle_body(self, candle: dict, ctx: Any):
        symbol = candle["symbol"]

        # Commit previous candle close for cross detection.
        if symbol in self._pending_spot_close_by_symbol:
            self._last_spot_close_by_symbol[symbol] = (
                self._pending_spot_close_by_symbol.pop(symbol)
            )

        curr_spot_close = float(candle["close"])

        # --------------------------------------------------
        # 1) Reversal: if we have an open MAIN and ML1 is crossed,
        #    open the reverse option from on_candle.
        # --------------------------------------------------
        open_positions = ctx.position_store.get_open_positions(
            underlying=symbol, strategy=self.name
        )

        reversal_entry: Optional[Any] = None
        if open_positions:
            for pos in open_positions:
                if (
                    getattr(pos, "tag", None) != "MAIN"
                    or getattr(pos, "net_qty", 0) == 0
                ):
                    continue

                self._restore_odml_meta_from_position(pos, ctx.position_store)
                meta = self._meta_by_structure_id.get(pos.structure_id)
                if meta is None:
                    continue

                if not self._is_reversal_cross(pos, candle, meta.ml1):
                    continue

                # If SL triggered, we exit but do NOT reverse.
                if self._is_sl_triggered(pos, candle, ctx, meta):
                    continue

                opt_type = (pos.instrument.option_type or "").upper()
                reverse_option_type = "CE" if opt_type in ("PE", "PUT") else "PE"

                # Next reversal level for this ML1 entry day
                next_level = (
                    self._reversal_level_counter.get(
                        (meta.symbol, meta.entry_date), meta.level
                    )
                    + 1
                )
                self._reversal_level_counter[(meta.symbol, meta.entry_date)] = (
                    next_level
                )
                new_structure_id = (
                    f"{self.name}:{meta.symbol}:ML1:{meta.entry_date}:L{next_level}"
                )

                if ctx.position_store.has_open_structure(
                    strategy=self.name, structure_id=new_structure_id, tag="MAIN"
                ):
                    reversal_entry = None
                    break
                if getattr(
                    ctx, "intent_store", None
                ) and ctx.intent_store.has_pending_intent(
                    strategy=self.name,
                    structure_id=new_structure_id,
                ):
                    reversal_entry = None
                    break

                result = self.find_strike_in_premium_range(
                    candle,
                    ctx,
                    reverse_option_type,
                    min_prem=TARGET_PREMIUM_MIN,
                    max_prem=TARGET_PREMIUM_MAX,
                )
                if result is None:
                    reversal_entry = None
                    break

                strike, premium, row = result
                if not strike:
                    reversal_entry = None
                    break

                expiry = ctx.selected_expiry
                trading_symbol = self.delta_option_trading_symbol(
                    row,
                    float(strike),
                    reverse_option_type,
                    str(expiry),
                )
                inst = ctx.instrument_store.intent_creation_details(
                    trading_symbol,
                    ctx.exchange,
                    expiry,
                    reverse_option_type,
                    strike,
                )
                if inst is None:
                    reversal_entry = None
                    break

                new_meta = _PosMeta(
                    symbol=meta.symbol,
                    entry_date=meta.entry_date,
                    ml1=meta.ml1,
                    entry_premium=float(premium),
                    level=next_level,
                )
                reversal_entry = self.map_instrument_to_intent(
                    inst=inst,
                    strike_row=row,
                    strategy=self.name,
                    side="SELL",
                    structure_id=new_structure_id,
                    candle_ts=candle["timestamp"],
                    tag="MAIN",
                    symbol=meta.symbol,
                    action="ENTRY",
                    metadata_extras=self._strategy_meta_dict(new_meta),
                )
                self._meta_by_structure_id[new_structure_id] = new_meta
                self._exit_reason_by_structure_id.pop(new_structure_id, None)
                break

        # Always stage current close for the next candle's cross detection.
        self._pending_spot_close_by_symbol[symbol] = curr_spot_close

        if reversal_entry is not None:
            return reversal_entry

        # --------------------------------------------------
        # 2) Initial entry: only at 17:30.
        # --------------------------------------------------
        if not self.should_enter(candle):
            return None

        trade_dt = pd.to_datetime(candle["timestamp"]).date()
        # Enforce: at most one MAIN structure open for this underlying
        open_positions = ctx.position_store.get_open_positions(
            underlying=symbol, strategy=self.name
        )
        if any(
            getattr(p, "tag", None) == "MAIN" and getattr(p, "net_qty", 0) != 0
            for p in open_positions
        ):
            return None

        direction = self._direction_at_1730(candle)
        option_type = self._option_type_for_direction(direction)

        # ML1 is spot close at 17:30 candle close
        ml1 = float(candle["close"])

        # Level starts at 1 for this day
        level = self._reversal_level_counter.get((symbol, trade_dt), 0) + 1
        self._reversal_level_counter[(symbol, trade_dt)] = level

        structure_id = f"{self.name}:{symbol}:ML1:{trade_dt}:L{level}"
        if ctx.position_store.has_open_structure(
            strategy=self.name, structure_id=structure_id, tag="MAIN"
        ):
            return None

        has_pending = (
            ctx.intent_store.has_pending_intent(
                strategy=self.name,
                structure_id=structure_id,
            )
            if getattr(ctx, "intent_store", None)
            else False
        )
        if has_pending:
            return None

        # Select strike by target premium range for delta excahnage
        result = self.find_strike_in_premium_range(
            candle,
            ctx,
            option_type,
            min_prem=TARGET_PREMIUM_MIN,
            max_prem=TARGET_PREMIUM_MAX,
        )

        if result is None:
            return None

        strike, premium, row = result
        if not strike:
            return None

        expiry = ctx.selected_expiry

        trading_symbol = self.delta_option_trading_symbol(
            row,
            float(strike),
            option_type,
            str(expiry),
        )
        inst = ctx.instrument_store.intent_creation_details(
            trading_symbol, ctx.exchange, expiry, option_type, strike
        )
        if inst is None:
            return None

        meta = _PosMeta(
            symbol=symbol,
            entry_date=trade_dt,
            ml1=ml1,
            entry_premium=float(premium),
            level=level,
        )
        entry_intent = self.map_instrument_to_intent(
            inst=inst,
            strike_row=row,
            strategy=self.name,
            side="SELL",
            structure_id=structure_id,
            candle_ts=candle["timestamp"],
            tag="MAIN",
            symbol=symbol,
            action="ENTRY",
            metadata_extras=self._strategy_meta_dict(meta),
        )

        self._meta_by_structure_id[structure_id] = meta
        self._exit_reason_by_structure_id.pop(structure_id, None)

        return entry_intent

    # ==================================================
    # EXIT: reverse on ML1 cross, else SL by premium
    # ==================================================
    def should_exit(self, position: Any, candle: dict, ctx: Any = None) -> bool:
        if position.tag != "MAIN":
            return False

        structure_id = position.structure_id
        if structure_id in self._pending_exit_structure_ids:
            return False

        if ctx is not None:
            self._restore_odml_meta_from_position(position, ctx.position_store)
        meta = self._meta_by_structure_id.get(structure_id)
        if meta is None:
            return False

        # Reversal has priority over SL (either way we exit; SL means "no reversal").
        if self._is_reversal_cross(position, candle, meta.ml1):
            self._exit_reason_by_structure_id[structure_id] = "REVERSAL"
            return True

        if self._is_sl_triggered(position, candle, ctx, meta):
            self._exit_reason_by_structure_id[structure_id] = "SL"
            return True

        return False

    def on_position_exit(self, position: Any, candle: dict, ctx: Any):
        structure_id = position.structure_id
        if getattr(ctx, "intent_store", None) and ctx.intent_store.has_pending_intent(
            strategy=self.name,
            structure_id=structure_id,
        ):
            return []
        # Prevent duplicate exit intents if broker fill is delayed
        self._pending_exit_structure_ids.add(structure_id)

        price = self.get_option_price_at_candle(
            candle=candle,
            ctx=ctx,
            strike=position.instrument.strike,
            option_type=position.instrument.option_type,
            expiry=position.instrument.expiry,
            trading_symbol=position.instrument.trading_symbol,
        )
        return [
            self.create_order_intent(
                inst=position.instrument,
                side="BUY" if position.net_qty < 0 else "SELL",
                qty=abs(position.net_qty),
                price=price,
                strategy=self.name,
                candle_ts=candle["timestamp"],
                structure_id=position.structure_id,
                tag="MAIN_EXIT",
                symbol=candle["symbol"],
                action="EXIT",
            )
        ]

    # ==================================================
    # CLEANUP: remove cached ML1/meta for exited structures
    # ==================================================
    def on_structure_exit(self, structure_id: str, **kwargs):
        super().on_structure_exit(structure_id=structure_id, **kwargs)
        self._pending_exit_structure_ids.discard(structure_id)
        self._exit_reason_by_structure_id.pop(structure_id, None)
        self._meta_by_structure_id.pop(structure_id, None)
