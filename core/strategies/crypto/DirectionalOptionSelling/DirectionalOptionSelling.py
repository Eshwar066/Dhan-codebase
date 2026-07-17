"""BTC SuperTrend directional option selling on Delta Exchange."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, replace
from datetime import date, datetime, time, timezone
from typing import Any, Dict, List, Optional

import pandas as pd

from run.config import RUN_MODE, RunMode
from core.strategies.base import BaseStrategy
from core.strategies.IndiaMktMixins import IST, IndiaMktMixins
from core.strategies.deltaMktMixins import DeltaMktMixins, _delta_source_from_ctx
from core.strategies.meta import pack_strategy_meta, unpack_strategy_meta
from core.utils.structure.supertrend import add_supertrend, supertrend_column_names

logger = logging.getLogger(__name__)

SUPER_TREND_LENGTH = 16
SUPER_TREND_FACTOR = 1.5
MIN_PREMIUM_USD = 300.0
FORCE_EXIT_POINTS = 300.0
ROLLOVER_TIME = time(17, 25)
ROLLOVER_MIN_STRIKE_DISTANCE = 200.0
ORDER_QTY_LOTS = 1
META_KEY = "directional_option_selling"


@dataclass(frozen=True)
class _PositionMeta:
    symbol: str
    direction: int
    option_type: str
    supertrend: float
    strike: float
    expiry: str
    entry_premium: float
    entry_reason: str


@dataclass(frozen=True)
class _PendingTransition:
    previous_structure_id: str
    direction: int
    reason: str
    min_dte: int = 0
    min_strike_distance: float = 0.0


class DirectionalOptionSelling(IndiaMktMixins, DeltaMktMixins, BaseStrategy):
    """
    Sell one BTC Put after a confirmed bullish SuperTrend flip and one Call after
    a bearish flip. Reversals wait for the existing option exit fill.
    """

    name = "DirectionalOptionSelling"
    underlying_symbols = ["BTCUSD"]
    timeframe = "60"
    required_context = ["option_chain"]
    api = "DELTA"
    expiryType = "Daily"
    order_qty_lots = ORDER_QTY_LOTS
    supertrend_length = SUPER_TREND_LENGTH
    supertrend_factor = SUPER_TREND_FACTOR

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._confirmed_direction: Optional[int] = None
        self._current_supertrend: Optional[float] = None
        self._latest_candle: Optional[dict] = None
        self._meta_by_structure_id: Dict[str, _PositionMeta] = {}
        self._pending_exit_structure_ids: set[str] = set()
        self._pending_transition: Optional[_PendingTransition] = None
        self._force_reentry_direction: Optional[int] = None
        self._force_exit_after: Optional[pd.Timestamp] = None
        self._evaluated_bars: set[str] = set()
        self._rollover_dates: set[date] = set()

    def get_warmup_period(self) -> int:
        return max(50, SUPER_TREND_LENGTH * 4)

    def persisted_indicator_keys(self) -> List[str]:
        return supertrend_column_names()

    def prepare_indicators(self, df: Any) -> Any:
        """Keep backtest and live SuperTrend calculations identical."""
        if df is None or len(df) == 0:
            return df
        required = supertrend_column_names()
        if all(column in df.columns for column in required):
            return df
        return add_supertrend(
            df,
            length=self.supertrend_length,
            factor=self.supertrend_factor,
        )

    @staticmethod
    def _normal_direction(value: Any) -> Optional[int]:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        if pd.isna(number) or number == 0:
            return None
        return 1 if number > 0 else -1

    @staticmethod
    def _option_type(direction: int) -> str:
        return "PE" if direction > 0 else "CE"

    @staticmethod
    def _timestamp_ist(value: Any) -> pd.Timestamp:
        ts = pd.Timestamp(value)
        if ts.tzinfo is None:
            ts = ts.tz_localize(IST)
        else:
            ts = ts.tz_convert(IST)
        return ts

    def _closed_bar_time_ist(self, candle: dict) -> pd.Timestamp:
        """Hourly candle timestamps are bucket starts; return confirmed close time."""
        return self._timestamp_ist(candle["timestamp"]) + pd.Timedelta(minutes=60)

    def _bar_key(self, candle: dict) -> str:
        symbol = str(candle.get("symbol") or "").strip().upper()
        return f"{symbol}|{self._timestamp_ist(candle['timestamp']).isoformat()}"

    def should_evaluate(self, candle: dict) -> bool:
        if str(candle.get("symbol") or "").strip().upper() != "BTCUSD":
            return False
        key = self._bar_key(candle)
        if key in self._evaluated_bars:
            return False
        self._evaluated_bars.add(key)
        if len(self._evaluated_bars) > 5000:
            self._evaluated_bars = set(sorted(self._evaluated_bars)[-2500:])
        return True

    def _strategy_meta(self, meta: _PositionMeta) -> dict:
        return pack_strategy_meta(
            self.name,
            {
                "symbol": meta.symbol,
                "direction": meta.direction,
                "option_type": meta.option_type,
                "supertrend": meta.supertrend,
                "strike": meta.strike,
                "expiry": meta.expiry,
                "entry_premium": meta.entry_premium,
                "entry_reason": meta.entry_reason,
            },
        )

    def _restore_meta(self, structure_id: str, raw: Any) -> bool:
        if structure_id in self._meta_by_structure_id:
            return True
        canonical = unpack_strategy_meta(raw, self.name)
        if canonical is not None:
            raw = canonical
        if isinstance(raw, dict) and META_KEY in raw:
            raw = raw.get(META_KEY)
        if not isinstance(raw, dict):
            return False
        try:
            meta = _PositionMeta(
                symbol=str(raw["symbol"]).upper(),
                direction=int(raw["direction"]),
                option_type=str(raw["option_type"]).upper(),
                supertrend=float(raw["supertrend"]),
                strike=float(raw["strike"]),
                expiry=str(raw["expiry"]),
                entry_premium=float(raw["entry_premium"]),
                entry_reason=str(raw.get("entry_reason") or "signal"),
            )
        except (KeyError, TypeError, ValueError):
            return False
        self._meta_by_structure_id[structure_id] = meta
        return True

    def _ensure_meta(self, position: Any, ctx: Any) -> Optional[_PositionMeta]:
        sid = str(getattr(position, "structure_id", "") or "")
        meta = self._meta_by_structure_id.get(sid)
        if meta is not None:
            return meta
        intent_store = getattr(ctx, "intent_store", None)
        intent_id = getattr(position, "intent_id", None)
        if intent_store is not None and intent_id and callable(getattr(intent_store, "get", None)):
            record = intent_store.get(intent_id) or {}
            payload = record.get("payload") or {}
            strategy_meta = payload.get("strategy_meta") or payload.get("metadata_extras") or {}
            if self._restore_meta(sid, strategy_meta):
                return self._meta_by_structure_id.get(sid)
        inst = getattr(position, "instrument", None)
        option_type = str(getattr(inst, "option_type", "") or "").upper()
        direction = 1 if option_type.startswith("P") else -1
        try:
            fallback = _PositionMeta(
                symbol="BTCUSD",
                direction=direction,
                option_type="PE" if direction > 0 else "CE",
                supertrend=float(self._current_supertrend or 0),
                strike=float(getattr(inst, "strike", 0) or 0),
                expiry=str(getattr(inst, "expiry", "") or ""),
                entry_premium=float(getattr(position, "avg_price", 0) or 0),
                entry_reason="restored",
            )
        except (TypeError, ValueError):
            return None
        self._meta_by_structure_id[sid] = fallback
        return fallback

    def restore_state_on_startup(
        self, position_manager: Any, intent_store: Any = None
    ) -> None:
        """Restore open MAIN metadata so quote risk works before the next hourly bar."""
        if position_manager is None:
            return
        for position in list(getattr(position_manager, "positions", {}).values()):
            if int(getattr(position, "net_qty", 0) or 0) == 0:
                continue
            if getattr(position, "strategy", None) != self.name:
                continue
            if str(getattr(position, "tag", "") or "").upper() != "MAIN":
                continue
            sid = str(getattr(position, "structure_id", "") or "")
            instrument = getattr(position, "instrument", None)
            trading_symbol = str(
                getattr(instrument, "trading_symbol", "") or ""
            )
            stored = (
                position_manager.get_position_metadata(trading_symbol)
                if trading_symbol
                and callable(getattr(position_manager, "get_position_metadata", None))
                else None
            ) or {}
            raw = stored.get("strategy_meta") if isinstance(stored, dict) else None
            if raw is None and intent_store is not None:
                intent_id = getattr(position, "intent_id", None)
                record = intent_store.get(intent_id) if intent_id else None
                raw = (record or {}).get("payload", {}).get("strategy_meta")
            if sid and self._restore_meta(sid, raw):
                meta = self._meta_by_structure_id[sid]
                self._confirmed_direction = meta.direction
                self._current_supertrend = meta.supertrend

    def _open_main_positions(self, ctx: Any) -> List[Any]:
        return [
            position
            for position in (ctx.position_store.get_open_positions(strategy=self.name) or [])
            if getattr(position, "tag", None) == "MAIN"
            and int(getattr(position, "net_qty", 0) or 0) != 0
        ]

    @staticmethod
    def _expiry_date(value: Any) -> Optional[date]:
        if value is None:
            return None
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        raw = str(value).strip()
        for fmt in ("%d%m%y", "%Y-%m-%d", "%d-%m-%Y"):
            try:
                return datetime.strptime(raw, fmt).date()
            except ValueError:
                continue
        return None

    @staticmethod
    def _product_expiry(product: dict) -> str:
        symbol = str(product.get("symbol") or "").upper()
        parts = symbol.split("-")
        return str(parts[-1]).strip() if len(parts) >= 4 else ""

    @staticmethod
    def _product_strike(product: dict) -> Optional[float]:
        value = product.get("strike_price")
        if value is None:
            parts = str(product.get("symbol") or "").split("-")
            value = parts[2] if len(parts) >= 4 else None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _sell_premium(ticker: Any) -> Optional[tuple[float, float, float]]:
        if not isinstance(ticker, dict):
            return None
        quotes = ticker.get("quotes") or {}
        try:
            bid = float(quotes.get("best_bid") or 0)
        except (TypeError, ValueError):
            bid = 0.0
        try:
            ask = float(quotes.get("best_ask") or 0)
        except (TypeError, ValueError):
            ask = 0.0
        premium = bid
        if premium <= 0:
            for key in ("mark_price", "close", "price"):
                try:
                    premium = float(ticker.get(key) or 0)
                except (TypeError, ValueError):
                    premium = 0.0
                if premium > 0:
                    break
        return (premium, bid, ask) if premium > 0 else None

    @staticmethod
    def _ordered_expiries(expiries: List[str], trade_date: date, min_dte: int) -> List[str]:
        dated = []
        for code in set(expiries):
            parsed = DirectionalOptionSelling._expiry_date(code)
            if parsed is not None and parsed >= trade_date:
                dated.append((parsed, code))
        dated.sort()
        if min_dte > 0:
            return [code for expiry, code in dated if expiry > trade_date][:1]
        today = [code for expiry, code in dated if expiry == trade_date]
        future = [code for expiry, code in dated if expiry > trade_date]
        return (today[:1] + future[:1])[:2]

    def _select_live_contract(
        self,
        candle: dict,
        ctx: Any,
        option_type: str,
        supertrend: float,
        *,
        min_dte: int,
        min_strike_distance: float,
    ) -> Optional[tuple[float, float, pd.Series, str]]:
        source = _delta_source_from_ctx(ctx)
        if source is None:
            return None
        opt_letter = option_type[0].upper()
        products = source.get_products(use_cache=True) or []
        matching = [
            product
            for product in products
            if str(product.get("symbol") or "").upper().startswith(f"{opt_letter}-BTC-")
        ]
        trade_date = self._timestamp_ist(candle["timestamp"]).date()
        expiry_order = self._ordered_expiries(
            [self._product_expiry(product) for product in matching],
            trade_date,
            min_dte,
        )
        for expiry in expiry_order:
            candidates = []
            for product in matching:
                if self._product_expiry(product) != expiry:
                    continue
                strike = self._product_strike(product)
                symbol = str(product.get("symbol") or "").upper()
                distance = abs(strike - supertrend) if strike is not None else 0
                if (
                    strike is not None
                    and symbol
                    and distance >= float(min_strike_distance)
                ):
                    candidates.append((distance, strike, symbol, product))
            candidates.sort(key=lambda item: (item[0], item[1]))
            try:
                tickers = source.get_option_tickers_for_expiry("BTC", expiry, opt_letter) or {}
            except Exception:
                tickers = {}
            for _distance, strike, symbol, _product in candidates:
                ticker = tickers.get(symbol)
                if ticker is None:
                    try:
                        ticker = source.get_ticker(symbol)
                    except Exception:
                        ticker = None
                quote = self._sell_premium(ticker)
                if quote is None or quote[0] < MIN_PREMIUM_USD:
                    continue
                premium, bid, ask = quote
                row = pd.Series(
                    {
                        "symbol": symbol,
                        "strike": strike,
                        "price": premium,
                        "close": premium,
                        "best_bid": bid,
                        "best_ask": ask,
                        "expiry": expiry,
                    }
                )
                return strike, premium, row, expiry
        return None

    def _select_backtest_contract(
        self,
        candle: dict,
        ctx: Any,
        option_type: str,
        supertrend: float,
        *,
        min_dte: int,
        min_strike_distance: float,
    ) -> Optional[tuple[float, float, pd.Series, str]]:
        df = self.load_delta_data_for_candle(candle, ctx)
        if df is None or df.empty:
            return None
        work = df.copy()
        work.columns = [
            "symbol", "price", "qty", "timestamp", "side", "opt_type", "strike", "expiry"
        ]
        work["timestamp"] = pd.to_datetime(work["timestamp"])
        parts = work["symbol"].astype(str).str.split("-", expand=True)
        work["opt_type"] = parts[0].str.upper()
        work["strike"] = pd.to_numeric(parts[2], errors="coerce")
        work["expiry"] = parts[3].astype(str)
        candle_time = pd.Timestamp(candle["timestamp"]).tz_localize(None)
        work = work[
            (work["opt_type"] == option_type[0].upper())
            & (work["timestamp"] >= candle_time - pd.Timedelta(minutes=5))
            & (work["timestamp"] <= candle_time + pd.Timedelta(minutes=5))
        ]
        if work.empty:
            return None
        expiry_order = self._ordered_expiries(
            work["expiry"].dropna().astype(str).tolist(),
            self._timestamp_ist(candle["timestamp"]).date(),
            min_dte,
        )
        for expiry in expiry_order:
            latest = (
                work[work["expiry"] == expiry]
                .sort_values("timestamp")
                .groupby("strike", as_index=False)
                .last()
            )
            latest["price"] = pd.to_numeric(latest["price"], errors="coerce")
            latest = latest[(latest["price"] >= MIN_PREMIUM_USD) & (latest["qty"] > 0)]
            if latest.empty:
                continue
            latest = latest.copy()
            latest["distance"] = (latest["strike"] - supertrend).abs()
            latest = latest[latest["distance"] >= float(min_strike_distance)]
            if latest.empty:
                continue
            row = latest.sort_values(["distance", "strike"]).iloc[0]
            return float(row["strike"]), float(row["price"]), row, expiry
        return None

    def _select_contract(
        self,
        candle: dict,
        ctx: Any,
        direction: int,
        supertrend: float,
        *,
        min_dte: int = 0,
        min_strike_distance: float = 0.0,
    ) -> Optional[tuple[float, float, pd.Series, str]]:
        option_type = self._option_type(direction)
        if RUN_MODE == RunMode.BACKTEST:
            return self._select_backtest_contract(
                candle,
                ctx,
                option_type,
                supertrend,
                min_dte=min_dte,
                min_strike_distance=min_strike_distance,
            )
        return self._select_live_contract(
            candle,
            ctx,
            option_type,
            supertrend,
            min_dte=min_dte,
            min_strike_distance=min_strike_distance,
        )

    def _build_entry(
        self,
        candle: dict,
        ctx: Any,
        direction: int,
        *,
        reason: str,
        min_dte: int = 0,
        min_strike_distance: float = 0.0,
    ) -> Optional[Any]:
        if self._open_main_positions(ctx):
            return None
        supertrend = float(self._current_supertrend or candle.get("supertrend") or 0)
        if supertrend <= 0:
            return None
        selected = self._select_contract(
            candle,
            ctx,
            direction,
            supertrend,
            min_dte=min_dte,
            min_strike_distance=min_strike_distance,
        )
        if selected is None:
            logger.warning(
                "%s: no %s contract premium >= %.2f near SuperTrend %.2f",
                self.name,
                self._option_type(direction),
                MIN_PREMIUM_USD,
                supertrend,
            )
            return None
        strike, premium, row, expiry = selected
        option_type = self._option_type(direction)
        trading_symbol = self.delta_option_trading_symbol(
            row, strike, option_type, expiry
        )
        ctx.selected_expiry = expiry
        inst = ctx.instrument_store.intent_creation_details(
            trading_symbol, ctx.exchange, expiry, option_type, strike
        )
        if inst is None:
            return None
        structure_id = (
            f"{self.name}:BTCUSD:{self._timestamp_ist(candle['timestamp']).date()}:"
            f"{option_type}:{uuid.uuid4().hex[:8]}"
        )
        meta = _PositionMeta(
            symbol="BTCUSD",
            direction=direction,
            option_type=option_type,
            supertrend=supertrend,
            strike=strike,
            expiry=expiry,
            entry_premium=premium,
            entry_reason=reason,
        )
        intent = self.map_instrument_to_intent(
            inst=inst,
            strike_row=row,
            strategy=self.name,
            side="SELL",
            structure_id=structure_id,
            candle_ts=candle["timestamp"],
            tag="MAIN",
            symbol="BTCUSD",
            action="ENTRY",
            metadata_extras=self._strategy_meta(meta),
        )
        intent = replace(intent, qty=ORDER_QTY_LOTS)
        self._meta_by_structure_id[structure_id] = meta
        logger.info(
            "%s ENTRY reason=%s opt=%s strike=%.2f expiry=%s premium=%.2f ST=%.2f",
            self.name,
            reason,
            option_type,
            strike,
            expiry,
            premium,
            supertrend,
        )
        return intent

    def _exit_intent(self, position: Any, candle: dict, ctx: Any, reason: str) -> Any:
        price = None
        if RUN_MODE == RunMode.BACKTEST:
            price = self.get_option_price_at_candle(
                candle,
                ctx,
                position.instrument.strike,
                position.instrument.option_type,
                position.instrument.expiry,
                trading_symbol=position.instrument.trading_symbol,
            )
        return self.create_order_intent(
            inst=position.instrument,
            side="BUY" if int(position.net_qty) < 0 else "SELL",
            qty=abs(int(position.net_qty or 0)) or 1,
            price=price,
            order_type="LIMIT",
            strategy=self.name,
            candle_ts=candle["timestamp"],
            structure_id=position.structure_id,
            tag="MAIN_EXIT",
            symbol="BTCUSD",
            action="EXIT",
            metadata_extras={"exit_reason": reason},
        )

    def _begin_transition(
        self,
        position: Any,
        candle: dict,
        ctx: Any,
        *,
        direction: int,
        reason: str,
        min_dte: int = 0,
        min_strike_distance: float = 0.0,
    ) -> Optional[Any]:
        sid = str(getattr(position, "structure_id", "") or "")
        if not sid or sid in self._pending_exit_structure_ids:
            return None
        intent_store = getattr(ctx, "intent_store", None)
        if intent_store is not None and intent_store.has_pending_intent(
            strategy=self.name,
            structure_id=sid,
            actions=["EXIT", "FORCE_EXIT"],
        ):
            return None
        self._pending_exit_structure_ids.add(sid)
        self._pending_transition = _PendingTransition(
            previous_structure_id=sid,
            direction=direction,
            reason=reason,
            min_dte=min_dte,
            min_strike_distance=min_strike_distance,
        )
        return self._exit_intent(position, candle, ctx, reason)

    def _rollover_intent_if_due(
        self, candle: dict, ctx: Any, *, closed_bar: bool = False
    ) -> Optional[Any]:
        now = (
            self._closed_bar_time_ist(candle)
            if closed_bar
            else self._timestamp_ist(candle["timestamp"])
        )
        if now.time() < ROLLOVER_TIME or now.date() in self._rollover_dates:
            return None
        positions = self._open_main_positions(ctx)
        today_positions = [
            position
            for position in positions
            if self._expiry_date(getattr(position.instrument, "expiry", None)) == now.date()
        ]
        if not today_positions:
            self._rollover_dates.add(now.date())
            return None
        position = today_positions[0]
        meta = self._ensure_meta(position, ctx)
        direction = (
            self._confirmed_direction
            if self._confirmed_direction is not None
            else (meta.direction if meta is not None else 1)
        )
        # Re-opening today's contract would defeat settlement protection, so rollover
        # deliberately starts from the next listed daily expiry.
        intent = self._begin_transition(
            position,
            candle,
            ctx,
            direction=direction,
            reason="expiry_rollover",
            min_dte=1,
            min_strike_distance=ROLLOVER_MIN_STRIKE_DISTANCE,
        )
        if intent is not None:
            self._rollover_dates.add(now.date())
        return intent

    def on_candle(self, candle: dict, ctx: Any) -> Optional[List[Any]]:
        if str(candle.get("symbol") or "").strip().upper() != "BTCUSD":
            return None
        direction = self._normal_direction(candle.get("supertrend_direction"))
        try:
            supertrend = float(candle.get("supertrend"))
            close = float(candle.get("close"))
        except (TypeError, ValueError):
            return None
        if direction is None or pd.isna(supertrend) or supertrend <= 0:
            return None

        previous = self._confirmed_direction
        self._confirmed_direction = direction
        self._current_supertrend = supertrend
        self._latest_candle = dict(candle)
        positions = self._open_main_positions(ctx)

        if previous is None:
            rollover = self._rollover_intent_if_due(candle, ctx, closed_bar=True)
            return [rollover] if rollover is not None else None

        if direction != previous:
            self._force_reentry_direction = None
            self._force_exit_after = None
            min_dte = (
                1
                if self._closed_bar_time_ist(candle).time() >= ROLLOVER_TIME
                else 0
            )
            if positions:
                sid = str(getattr(positions[0], "structure_id", "") or "")
                if sid in self._pending_exit_structure_ids:
                    # The same closed bar can satisfy the intrabar stop and confirm a
                    # reversal. Reuse that pending exit, then enter the opposite leg.
                    self._pending_transition = _PendingTransition(
                        previous_structure_id=sid,
                        direction=direction,
                        reason="supertrend_reversal",
                        min_dte=min_dte,
                    )
                    intent = None
                else:
                    intent = self._begin_transition(
                        positions[0],
                        candle,
                        ctx,
                        direction=direction,
                        reason="supertrend_reversal",
                        min_dte=min_dte,
                    )
            else:
                intent = self._build_entry(
                    candle,
                    ctx,
                    direction,
                    reason="supertrend_reversal",
                    min_dte=min_dte,
                )
            return [intent] if intent is not None else None

        if (
            not positions
            and self._force_reentry_direction == direction
            and (
                self._force_exit_after is None
                or self._closed_bar_time_ist(candle) > self._force_exit_after
            )
        ):
            trend_valid = close > supertrend if direction > 0 else close < supertrend
            if trend_valid:
                self._force_reentry_direction = None
                intent = self._build_entry(
                    candle,
                    ctx,
                    direction,
                    reason="force_exit_reentry",
                    min_dte=(
                        1
                        if self._closed_bar_time_ist(candle).time() >= ROLLOVER_TIME
                        else 0
                    ),
                )
                return [intent] if intent is not None else None

        rollover = self._rollover_intent_if_due(candle, ctx, closed_bar=True)
        return [rollover] if rollover is not None else None

    def on_quote(self, quote: dict, ctx: Any) -> Optional[List[Any]]:
        if str(quote.get("symbol") or "").strip().upper() != "BTCUSD":
            return None
        timestamp = quote.get("ts")
        try:
            tick_dt = datetime.fromtimestamp(float(timestamp), tz=timezone.utc)
        except (TypeError, ValueError, OSError):
            tick_dt = datetime.now().astimezone()
        price = quote.get("ltp")
        try:
            spot = float(price)
        except (TypeError, ValueError):
            return None
        candle = {
            "symbol": "BTCUSD",
            "timestamp": tick_dt,
            "open": spot,
            "high": spot,
            "low": spot,
            "close": spot,
            "exchange": "DELTA",
        }

        rollover = self._rollover_intent_if_due(candle, ctx)
        if rollover is not None:
            return [rollover]
        if self._current_supertrend is None or self._confirmed_direction is None:
            return None
        positions = self._open_main_positions(ctx)
        if not positions:
            return None
        position = positions[0]
        sid = str(getattr(position, "structure_id", "") or "")
        if sid in self._pending_exit_structure_ids:
            return None
        meta = self._ensure_meta(position, ctx)
        position_direction = meta.direction if meta is not None else self._confirmed_direction
        threshold_hit = (
            position_direction > 0
            and spot <= float(self._current_supertrend) - FORCE_EXIT_POINTS
        ) or (
            position_direction < 0
            and spot >= float(self._current_supertrend) + FORCE_EXIT_POINTS
        )
        if not threshold_hit:
            return None
        self._force_reentry_direction = self._confirmed_direction
        self._force_exit_after = self._timestamp_ist(tick_dt)
        self._pending_exit_structure_ids.add(sid)
        logger.warning(
            "%s FORCE EXIT spot=%.2f ST=%.2f direction=%s",
            self.name,
            spot,
            self._current_supertrend,
            position_direction,
        )
        return [self._exit_intent(position, candle, ctx, "intrabar_supertrend_300")]

    def should_exit(self, position: Any, candle: dict, ctx: Any = None) -> bool:
        if ctx is None or getattr(position, "tag", None) != "MAIN":
            return False
        direction = self._confirmed_direction
        supertrend = self._current_supertrend
        if direction is None or supertrend is None:
            return False
        low = float(candle.get("low") or candle.get("close") or 0)
        high = float(candle.get("high") or candle.get("close") or 0)
        meta = self._ensure_meta(position, ctx)
        position_direction = meta.direction if meta is not None else direction
        return (
            position_direction > 0 and low <= supertrend - FORCE_EXIT_POINTS
        ) or (
            position_direction < 0 and high >= supertrend + FORCE_EXIT_POINTS
        )

    def on_position_exit(self, position: Any, candle: dict, ctx: Any) -> List[Any]:
        sid = str(getattr(position, "structure_id", "") or "")
        if not sid or sid in self._pending_exit_structure_ids:
            return []
        self._pending_exit_structure_ids.add(sid)
        self._force_reentry_direction = self._confirmed_direction
        self._force_exit_after = self._closed_bar_time_ist(candle)
        return [self._exit_intent(position, candle, ctx, "intrabar_supertrend_300")]

    def on_main_entry_filled(
        self,
        *,
        ctx: Any,
        structure_id: Optional[str],
        metadata_extras: Any = None,
        **kwargs: Any,
    ) -> List[Any]:
        if structure_id:
            self._restore_meta(str(structure_id), metadata_extras)
        return []

    def on_main_exit_filled(self, **kwargs: Any) -> List[Any]:
        sid = str(kwargs.get("structure_id") or "")
        if not sid:
            return []
        self._pending_exit_structure_ids.discard(sid)
        self._meta_by_structure_id.pop(sid, None)
        transition = self._pending_transition
        if transition is None or transition.previous_structure_id != sid:
            return []
        self._pending_transition = None
        ctx = kwargs.get("ctx")
        if ctx is None:
            return []
        candle = dict(self._latest_candle or {})
        if not candle:
            candle = {
                "symbol": "BTCUSD",
                "timestamp": kwargs.get("candle_ts") or datetime.now(),
                "close": getattr(ctx, "spot_price", 0),
                "exchange": "DELTA",
            }
        else:
            candle["timestamp"] = kwargs.get("candle_ts") or candle["timestamp"]
            if getattr(ctx, "spot_price", 0):
                candle["close"] = float(ctx.spot_price)
        intent = self._build_entry(
            candle,
            ctx,
            transition.direction,
            reason=transition.reason,
            min_dte=transition.min_dte,
            min_strike_distance=transition.min_strike_distance,
        )
        return [(intent, candle)] if intent is not None else []

    def on_forced_exit(self, **kwargs: Any) -> None:
        sid = str(kwargs.get("structure_id") or "")
        self._pending_exit_structure_ids.discard(sid)

    def on_structure_exit(self, structure_id: str, **kwargs: Any) -> None:
        super().on_structure_exit(structure_id=structure_id, **kwargs)
        self._pending_exit_structure_ids.discard(str(structure_id))

