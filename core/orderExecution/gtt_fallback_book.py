"""
GttFallbackBook: Dhan Forever (GTT) entry with engine-side bid/ask fallback.

Strategies opt in via ``execution_mode: HYBRID_GTT`` on ENTRY intents plus optional
``gtt_fallback`` spec in ``metadata_extras`` / ``strategy_meta``.

Flow per leg:
  1. Broker places Forever (GTT) order.
  2. Engine watches quotes; when trigger fires and leg is still unfilled,
     cancel GTT and place a resting LIMIT from the system.
  3. Fill (GTT or fallback) → existing ``on_main_entry_filled`` / SL path unchanged.
"""

from __future__ import annotations

import logging
import threading
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, time
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Protocol, Tuple
from zoneinfo import ZoneInfo

from core.models.order_intent import OrderIntent
from core.orderExecution.intent_store import IntentStatus

IST = ZoneInfo("Asia/Kolkata")
logger = logging.getLogger(__name__)

DEFAULT_ACTIVE_UNTIL = time(15, 20)


class GttFallbackPhase(str, Enum):
    GTT = "GTT"
    FALLBACK_SENT = "FALLBACK_SENT"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"


@dataclass
class BidAskLtp:
    bid: Optional[float] = None
    ask: Optional[float] = None
    ltp: Optional[float] = None
    ts: Optional[float] = None


@dataclass
class GttFallbackWatch:
    gtt_intent_id: str
    strategy_id: str
    structure_id: str
    trading_symbol: str
    side: str
    limit_price: float
    entry_date: date
    trigger_field: str = "ask"
    trigger_op: str = "<="
    active_until: time = DEFAULT_ACTIVE_UNTIL
    phase: GttFallbackPhase = GttFallbackPhase.GTT
    fallback_intent_id: Optional[str] = None
    broker_order_id: Optional[str] = None
    metadata_extras: Dict[str, Any] = field(default_factory=dict)
    instrument: Any = None
    qty: int = 1
    candle_ts: Any = None
    symbol: str = ""
    confirm_ticks: int = 1
    _trigger_hits: int = 0


class QuoteProvider(Protocol):
    def get_quote(self, trading_symbol: str) -> Optional[BidAskLtp]: ...


class FeedQuoteProvider:
    """Best bid/ask from a subscribed realtime feed cache."""

    def __init__(self, feed: Any) -> None:
        self._feed = feed

    def get_quote(self, trading_symbol: str) -> Optional[BidAskLtp]:
        sym = str(trading_symbol or "").strip()
        if not sym or self._feed is None:
            return None
        bid_fn = getattr(self._feed, "get_best_bid", None)
        ask_fn = getattr(self._feed, "get_best_ask", None)
        if not callable(bid_fn) or not callable(ask_fn):
            return None
        bid = bid_fn(sym)
        ask = ask_fn(sym)
        if bid is None and ask is None:
            return None
        ticker_fn = getattr(self._feed, "get_last_ticker", None)
        ltp = None
        if callable(ticker_fn):
            tick = ticker_fn(sym)
            if isinstance(tick, dict):
                ltp = tick.get("close") or tick.get("last_price")
        return BidAskLtp(bid=bid, ask=ask, ltp=ltp)


class RestQuoteProvider:
    """REST quote fallback when websocket is not subscribed or stale."""

    _SEGMENT_MAP = {
        "NFO": "NSE_FNO",
        "NSE_FNO": "NSE_FNO",
        "BFO": "BSE_FNO",
        "BSE_FNO": "BSE_FNO",
        "NSE": "NSE_EQ",
        "NSE_EQ": "NSE_EQ",
        "BSE": "BSE_EQ",
        "BSE_EQ": "BSE_EQ",
        "MCX": "MCX_COMM",
        "IDX": "IDX_I",
        "INDEX": "IDX_I",
    }

    def __init__(self, data_provider: Any, instrument_store: Any) -> None:
        self._data = data_provider
        self._store = instrument_store

    def get_quote(self, trading_symbol: str) -> Optional[BidAskLtp]:
        sym = str(trading_symbol or "").strip()
        if not sym or self._data is None:
            return None
        getter = getattr(self._data, "get_quote_v2", None)
        if not callable(getter):
            return None
        sec_id, segment = self._resolve_security(sym)
        if not sec_id:
            return None
        try:
            from core.library.dhan_marketfeed import parse_quote_response

            raw = getter({segment: [int(sec_id)]})
            flat = parse_quote_response(raw) if raw else {}
            row = flat.get(str(sec_id)) or flat.get(sec_id)
            if not isinstance(row, dict):
                return None
            ltp = _positive_float(row.get("last_price"))
            bid, ask = _depth_best(row.get("depth"))
            if bid is None and ask is None and ltp is None:
                return None
            return BidAskLtp(bid=bid, ask=ask, ltp=ltp)
        except Exception as exc:
            logger.debug("RestQuoteProvider failed sym=%s: %s", sym, exc)
            return None

    def _resolve_security(self, trading_symbol: str) -> Tuple[Optional[str], str]:
        store = self._store
        if store is None:
            return None, "NSE_FNO"
        inst = None
        if hasattr(store, "intent_creation_details"):
            try:
                inst = store.intent_creation_details(trading_symbol, "NSE", None, None, None)
            except Exception:
                inst = None
        if inst is None and hasattr(store, "get_feed_instruments"):
            rows = store.get_feed_instruments([trading_symbol])
            if rows:
                return str(rows[0].get("SecurityId")), str(
                    rows[0].get("ExchangeSegment") or "NSE_FNO"
                )
        if inst is None:
            return None, "NSE_FNO"
        sec = getattr(inst, "instrument_id", None)
        seg = str(getattr(inst, "segment", "") or "NFO").upper()
        feed_seg = self._SEGMENT_MAP.get(seg, "NSE_FNO")
        return (str(sec) if sec is not None else None), feed_seg


class CompositeQuoteProvider:
    """Feed-first; REST when feed has no usable bid/ask."""

    def __init__(self, *providers: QuoteProvider) -> None:
        self._providers = list(providers)

    def get_quote(self, trading_symbol: str) -> Optional[BidAskLtp]:
        best: Optional[BidAskLtp] = None
        for prov in self._providers:
            q = prov.get_quote(trading_symbol)
            if q is None:
                continue
            if q.bid is not None or q.ask is not None:
                return q
            if best is None and q.ltp is not None:
                best = q
        return best


SubscribeCallback = Callable[[List[str]], None]


def _positive_float(val: Any) -> Optional[float]:
    try:
        p = float(val)
    except (TypeError, ValueError):
        return None
    if p != p or p <= 0:
        return None
    return p


def _depth_best(depth: Any) -> Tuple[Optional[float], Optional[float]]:
    if not isinstance(depth, dict):
        return None, None
    buy = depth.get("buy") or depth.get("bids") or []
    sell = depth.get("sell") or depth.get("asks") or []
    bid = None
    ask = None
    if buy and isinstance(buy, list):
        try:
            bid = _positive_float(buy[0].get("price") if isinstance(buy[0], dict) else buy[0])
        except (IndexError, TypeError, AttributeError):
            pass
    if sell and isinstance(sell, list):
        try:
            ask = _positive_float(sell[0].get("price") if isinstance(sell[0], dict) else sell[0])
        except (IndexError, TypeError, AttributeError):
            pass
    return bid, ask


def _parse_hhmm(val: Any, default: time) -> time:
    if isinstance(val, time):
        return val.replace(second=0, microsecond=0)
    try:
        parts = str(val or "").strip().split(":")
        if len(parts) >= 2:
            return time(int(parts[0]), int(parts[1]))
    except (TypeError, ValueError):
        pass
    return default


def _trigger_met(watch: GttFallbackWatch, quote: BidAskLtp) -> bool:
    field = str(watch.trigger_field or "ask").lower()
    op = str(watch.trigger_op or "<=").strip()
    if field == "bid":
        val = quote.bid
    elif field == "ltp":
        val = quote.ltp
        if val is None:
            # Fall back to mid/ask when LTP not yet in feed cache.
            if quote.ask is not None and quote.bid is not None:
                val = (float(quote.ask) + float(quote.bid)) / 2.0
            else:
                val = quote.ask
    else:
        val = quote.ask
    if val is None:
        return False
    limit = float(watch.limit_price)
    if op == "<=":
        return float(val) <= limit
    if op == ">=":
        return float(val) >= limit
    if op == "<":
        return float(val) < limit
    if op == ">":
        return float(val) > limit
    return False


def _fallback_limit_price(watch: GttFallbackWatch, quote: Optional[BidAskLtp]) -> float:
    """
    Resting LIMIT after Forever cancel: use best ask (BUY) / best bid (SELL)
    so the order is marketable. Fall back to GTT limit only if quote missing.
    """
    limit = float(watch.limit_price)
    side = str(watch.side or "BUY").upper()
    if quote is None:
        return limit
    ask = _positive_float(quote.ask)
    bid = _positive_float(quote.bid)
    ltp = _positive_float(quote.ltp)
    if side == "BUY":
        if ask is not None and ask > 0:
            return float(ask)
        if ltp is not None and ltp > 0:
            return float(ltp)
        return limit
    if bid is not None and bid > 0:
        return float(bid)
    if ltp is not None and ltp > 0:
        return float(ltp)
    return limit


class GttFallbackBook:
    def __init__(
        self,
        order_router: Any,
        *,
        instrument_store: Any = None,
        engine_logger: Any = None,
    ) -> None:
        self._router = order_router
        self._instrument_store = instrument_store
        self._engine_logger = engine_logger
        self._lock = threading.Lock()
        self._watches: Dict[str, GttFallbackWatch] = {}
        self._quote_provider: Optional[QuoteProvider] = None
        self._subscribe_cb: Optional[SubscribeCallback] = None
        self._last_tick_log: Dict[str, float] = {}

    def set_quote_provider(self, provider: Optional[QuoteProvider]) -> None:
        self._quote_provider = provider

    def set_subscribe_callback(self, callback: Optional[SubscribeCallback]) -> None:
        self._subscribe_cb = callback

    def has_active_watches(self) -> bool:
        with self._lock:
            return any(
                w.phase in (GttFallbackPhase.GTT, GttFallbackPhase.FALLBACK_SENT)
                for w in self._watches.values()
            )

    def active_trading_symbols(self) -> List[str]:
        """Trading symbols with GTT/FALLBACK watches (for feed QuoteUpdated filters)."""
        with self._lock:
            return list(
                {
                    str(w.trading_symbol)
                    for w in self._watches.values()
                    if w.phase in (GttFallbackPhase.GTT, GttFallbackPhase.FALLBACK_SENT)
                    and str(w.trading_symbol or "").strip()
                }
            )

    def register_from_intent(self, intent: OrderIntent, *, broker_order_id: Any = None) -> None:
        extras = dict(getattr(intent, "metadata_extras", None) or {})
        mode = str(extras.get("execution_mode") or "").upper()
        if mode != "HYBRID_GTT":
            return
        if str(getattr(intent, "action", "") or "").upper() != "ENTRY":
            return
        inst = getattr(intent, "instrument", None)
        sym = ""
        if inst is not None:
            sym = (
                getattr(inst, "place_order_symbol", lambda: "")()
                if callable(getattr(inst, "place_order_symbol", None))
                else getattr(inst, "trading_symbol", "") or ""
            )
        if not sym:
            return
        fb = extras.get("gtt_fallback") if isinstance(extras.get("gtt_fallback"), dict) else {}
        candle_ts = getattr(intent, "candle_ts", None)
        entry_d = date.today()
        if candle_ts is not None:
            try:
                entry_d = (
                    candle_ts.date()
                    if hasattr(candle_ts, "date")
                    else datetime.fromisoformat(str(candle_ts)[:10]).date()
                )
            except (TypeError, ValueError):
                pass
        limit_price = float(getattr(intent, "price", 0) or 0)
        if limit_price <= 0:
            return
        try:
            confirm_ticks = max(1, int(fb.get("confirm_ticks") or 1))
        except (TypeError, ValueError):
            confirm_ticks = 1
        watch = GttFallbackWatch(
            gtt_intent_id=str(intent.intent_id),
            strategy_id=str(getattr(intent, "strategy", "") or ""),
            structure_id=str(getattr(intent, "structure_id", "") or ""),
            trading_symbol=str(sym),
            side=str(getattr(intent, "side", "BUY") or "BUY").upper(),
            limit_price=limit_price,
            entry_date=entry_d,
            trigger_field=str(fb.get("trigger_field") or "ask"),
            trigger_op=str(fb.get("trigger_op") or "<="),
            active_until=_parse_hhmm(fb.get("active_until"), DEFAULT_ACTIVE_UNTIL),
            broker_order_id=str(broker_order_id) if broker_order_id else None,
            metadata_extras=extras,
            instrument=inst,
            qty=int(getattr(intent, "qty", 1) or 1),
            candle_ts=candle_ts,
            symbol=str(getattr(intent, "symbol", "") or ""),
            confirm_ticks=confirm_ticks,
        )
        with self._lock:
            self._watches[watch.gtt_intent_id] = watch
        if self._subscribe_cb:
            try:
                self._subscribe_cb([watch.trading_symbol])
            except Exception as exc:
                logger.warning("GttFallback subscribe failed: %s", exc)
        self._log(
            "gtt_fallback_registered",
            f"watch={watch.trading_symbol} limit={watch.limit_price}",
            intent_id=watch.gtt_intent_id,
            strategy_id=watch.strategy_id,
        )

    def on_fill(self, intent_id: str) -> None:
        iid = str(intent_id or "")
        with self._lock:
            w = self._watches.get(iid)
            if w is None:
                for watch in self._watches.values():
                    if watch.fallback_intent_id == iid:
                        w = watch
                        break
            if w is None:
                return
            w.phase = GttFallbackPhase.FILLED

    def cancel_watch(self, intent_id: str, *, reason: str = "cancelled") -> None:
        with self._lock:
            w = self._watches.get(str(intent_id or ""))
            if w is None:
                return
            w.phase = GttFallbackPhase.CANCELLED
        self._log("gtt_fallback_cancelled", reason, intent_id=intent_id)

    def cancel_all_for_strategy(self, strategy_id: str, *, trade_date: Optional[date] = None) -> int:
        sid = str(strategy_id or "")
        n = 0
        with self._lock:
            targets = [
                w
                for w in self._watches.values()
                if w.strategy_id == sid
                and w.phase in (GttFallbackPhase.GTT, GttFallbackPhase.FALLBACK_SENT)
                and (trade_date is None or w.entry_date == trade_date)
            ]
        for w in targets:
            self._router.cancel_gtt_fallback_watch(w, reason="strategy_cutoff")
            self.cancel_watch(w.gtt_intent_id, reason="strategy_cutoff")
            n += 1
        return n

    def restore_from_intent_store(self) -> int:
        store = getattr(self._router, "intent_store", None)
        if store is None:
            return 0
        restored = 0
        today = datetime.now(IST).date()
        pending_statuses = (
            IntentStatus.SENT,
            IntentStatus.VALIDATED,
            IntentStatus.ACKED,
        )
        for st in pending_statuses:
            for rec in store.list_by_status(st):
                payload = rec.get("payload") or {}
                meta = payload.get("strategy_meta") or rec.get("strategy_meta") or {}
                if not isinstance(meta, dict):
                    continue
                if str(meta.get("execution_mode") or "").upper() != "HYBRID_GTT":
                    continue
                if str(payload.get("action") or rec.get("action") or "").upper() != "ENTRY":
                    continue
                iid = str(rec.get("intent_id") or "")
                if not iid or iid in self._watches:
                    continue
                parts = str(rec.get("structure_id") or payload.get("structure_id") or "").split(":")
                entry_d = today
                if len(parts) >= 3:
                    try:
                        entry_d = date.fromisoformat(str(parts[2])[:10])
                    except (TypeError, ValueError):
                        pass
                if entry_d != today:
                    continue
                inst = rec.get("instrument")
                sym = self._router._intent_trading_symbol(rec)
                if not sym:
                    continue
                fb = meta.get("gtt_fallback") if isinstance(meta.get("gtt_fallback"), dict) else {}
                limit_price = float(rec.get("price") or payload.get("price") or 0)
                if limit_price <= 0:
                    continue
                try:
                    confirm_ticks = max(1, int(fb.get("confirm_ticks") or 1))
                except (TypeError, ValueError):
                    confirm_ticks = 1
                watch = GttFallbackWatch(
                    gtt_intent_id=iid,
                    strategy_id=str(
                        rec.get("strategy") or payload.get("strategy_id") or ""
                    ),
                    structure_id=str(
                        rec.get("structure_id") or payload.get("structure_id") or ""
                    ),
                    trading_symbol=sym,
                    side=str(rec.get("side") or payload.get("side") or "BUY").upper(),
                    limit_price=limit_price,
                    entry_date=entry_d,
                    trigger_field=str(fb.get("trigger_field") or "ask"),
                    trigger_op=str(fb.get("trigger_op") or "<="),
                    active_until=_parse_hhmm(fb.get("active_until"), DEFAULT_ACTIVE_UNTIL),
                    broker_order_id=str(rec.get("broker_order_id") or "") or None,
                    metadata_extras=dict(meta),
                    instrument=inst,
                    qty=int(rec.get("qty") or payload.get("qty") or 1),
                    candle_ts=rec.get("candle_ts") or payload.get("candle_ts"),
                    symbol=str(payload.get("symbol") or rec.get("symbol") or ""),
                    phase=GttFallbackPhase.GTT,
                    confirm_ticks=confirm_ticks,
                )
                with self._lock:
                    self._watches[iid] = watch
                restored += 1
        if restored and self._subscribe_cb:
            syms = list({w.trading_symbol for w in self._watches.values()})
            try:
                self._subscribe_cb(syms)
            except Exception as exc:
                logger.warning("GttFallback restore subscribe failed: %s", exc)
        return restored

    def tick(self, now_ist: Optional[datetime] = None) -> None:
        """Full scan: fill sync, active_until, and quote triggers via QuoteProvider."""
        self._run_watches(now_ist=now_ist, quote_override=None, symbols=None, check_quotes=True)

    def maintenance_tick(self, now_ist: Optional[datetime] = None) -> None:
        """Fill sync + active_until only (no quote trigger). Use when quotes are push-driven."""
        self._run_watches(now_ist=now_ist, quote_override=None, symbols=None, check_quotes=False)

    def on_quote(
        self,
        trading_symbol: str,
        quote: Optional[BidAskLtp] = None,
        now_ist: Optional[datetime] = None,
    ) -> None:
        """
        Push path: evaluate watches for ``trading_symbol`` using the feed quote.

        Prefer this over ``tick()`` when QuoteUpdated is published from feed callbacks.
        """
        sym = str(trading_symbol or "").strip()
        if not sym:
            return
        self._run_watches(
            now_ist=now_ist,
            quote_override=quote,
            symbols={sym.upper(), sym},
            check_quotes=True,
        )

    def _run_watches(
        self,
        *,
        now_ist: Optional[datetime],
        quote_override: Optional[BidAskLtp],
        symbols: Optional[set],
        check_quotes: bool,
    ) -> None:
        if now_ist is None:
            now_ist = datetime.now(IST)
        if not self.has_active_watches():
            return
        with self._lock:
            active = [
                w
                for w in self._watches.values()
                if w.phase in (GttFallbackPhase.GTT, GttFallbackPhase.FALLBACK_SENT)
            ]
        for watch in active:
            if symbols is not None:
                wsym = str(watch.trading_symbol or "").strip()
                if wsym not in symbols and wsym.upper() not in symbols:
                    continue
            try:
                self._tick_watch(
                    watch,
                    now_ist,
                    quote_override=quote_override,
                    check_quotes=check_quotes,
                )
            except Exception as exc:
                logger.exception(
                    "GttFallback tick failed intent=%s: %s", watch.gtt_intent_id, exc
                )

    def _tick_watch(
        self,
        watch: GttFallbackWatch,
        now_ist: datetime,
        *,
        quote_override: Optional[BidAskLtp] = None,
        check_quotes: bool = True,
    ) -> None:
        router = self._router
        store = getattr(router, "intent_store", None)
        rec = store.get(watch.gtt_intent_id) if store else None

        if rec and hasattr(router, "_try_sync_gtt_intent_fill"):
            if router._try_sync_gtt_intent_fill(rec):
                self.on_fill(watch.gtt_intent_id)
                return

        if self._structure_filled(watch):
            self.on_fill(watch.gtt_intent_id)
            return

        slot_t = now_ist.time().replace(second=0, microsecond=0)
        if slot_t > watch.active_until and watch.entry_date == now_ist.date():
            router.cancel_gtt_fallback_watch(watch, reason="active_until")
            self.cancel_watch(watch.gtt_intent_id, reason="active_until")
            return

        if watch.phase == GttFallbackPhase.FALLBACK_SENT:
            if watch.fallback_intent_id and store:
                fb_rec = store.get(watch.fallback_intent_id)
                if fb_rec and fb_rec.get("status") == IntentStatus.FILLED:
                    self.on_fill(watch.fallback_intent_id)
            return

        if not check_quotes:
            return

        quote = quote_override
        if quote is None:
            if self._quote_provider is None:
                return
            quote = self._quote_provider.get_quote(watch.trading_symbol)
        if quote is None or not _trigger_met(watch, quote):
            watch._trigger_hits = 0
            return

        watch._trigger_hits = int(getattr(watch, "_trigger_hits", 0) or 0) + 1
        if watch._trigger_hits < max(1, int(watch.confirm_ticks or 1)):
            return

        # Premium reached GTT price; only fall back if Forever still unfilled.
        # Broker position truth is checked here (rather than on every quote) because
        # a Forever fill can reach Dhan positions before its order/fill update reaches
        # the local PositionManager.
        if self._broker_position_open(watch):
            self.on_fill(watch.gtt_intent_id)
            self._log(
                "gtt_fallback_position_detected",
                f"skip LIMIT; broker position already open {watch.trading_symbol}",
                intent_id=watch.gtt_intent_id,
            )
            return
        if not self._gtt_still_unfilled(watch, rec):
            self.on_fill(watch.gtt_intent_id)
            return

        # Re-poll Forever book once more before cancel (broker may have just triggered).
        if rec and hasattr(router, "_try_sync_gtt_intent_fill"):
            if router._try_sync_gtt_intent_fill(rec):
                self.on_fill(watch.gtt_intent_id)
                return
        if not self._gtt_still_unfilled(watch, store.get(watch.gtt_intent_id) if store else None):
            self.on_fill(watch.gtt_intent_id)
            return
        if self._broker_position_open(watch):
            self.on_fill(watch.gtt_intent_id)
            self._log(
                "gtt_fallback_position_detected",
                f"skip LIMIT; broker position already open {watch.trading_symbol}",
                intent_id=watch.gtt_intent_id,
            )
            return

        if watch.phase == GttFallbackPhase.GTT:
            cancelled = router.cancel_gtt_fallback_watch(watch, reason="fallback_trigger")
            if not cancelled:
                # Cancel failed — do not place LIMIT on top of live Forever order.
                self._log(
                    "gtt_fallback_cancel_failed",
                    f"skip LIMIT; Forever still open {watch.trading_symbol}",
                    intent_id=watch.gtt_intent_id,
                )
                return

        if watch.fallback_intent_id:
            return
        if store and store.has_pending_intent(
            watch.strategy_id,
            watch.structure_id,
            tags=["MAIN"],
            actions=["ENTRY"],
        ):
            pending_fb = False
            for st in (IntentStatus.CREATED, IntentStatus.VALIDATED, IntentStatus.SENT, IntentStatus.ACKED):
                for p in store.list_by_status(st):
                    pid = str(p.get("intent_id") or "")
                    if pid == watch.gtt_intent_id:
                        continue
                    payload = p.get("payload") or {}
                    sm = payload.get("strategy_meta") or {}
                    if (
                        str(payload.get("structure_id") or "") == watch.structure_id
                        and str(sm.get("gtt_fallback_parent") or "") == watch.gtt_intent_id
                    ):
                        pending_fb = True
                        watch.fallback_intent_id = pid
                        watch.phase = GttFallbackPhase.FALLBACK_SENT
                        break
                if pending_fb:
                    return

        fallback_price = _fallback_limit_price(watch, quote)
        fallback_id = router.place_gtt_fallback_order(watch, price=fallback_price)
        if fallback_id:
            watch.phase = GttFallbackPhase.FALLBACK_SENT
            watch.fallback_intent_id = fallback_id
            self._log(
                "gtt_fallback_placed",
                f"fallback LIMIT {watch.trading_symbol} @ {fallback_price} "
                f"(gtt_limit={watch.limit_price})",
                intent_id=fallback_id,
                parent_intent_id=watch.gtt_intent_id,
            )

    def _structure_filled(self, watch: GttFallbackWatch) -> bool:
        pm = getattr(self._router, "position_manager", None)
        if pm is None or not watch.structure_id:
            return False
        try:
            open_pos = pm.get_open_positions(
                underlying=watch.symbol or None,
                strategy=watch.strategy_id,
            )
        except Exception:
            return False
        for pos in open_pos or []:
            if str(getattr(pos, "structure_id", "")) != watch.structure_id:
                continue
            if str(getattr(pos, "tag", "") or "").upper() != "MAIN":
                continue
            if int(getattr(pos, "net_qty", 0) or 0) != 0:
                return True
        return False

    def _broker_position_open(self, watch: GttFallbackWatch) -> bool:
        """Check broker truth for this exact contract before placing fallback LIMIT."""
        broker = getattr(self._router, "broker", None)
        getter = getattr(broker, "get_positions_for_recon", None)
        if not callable(getter):
            return False
        try:
            positions = getter() or {}
        except Exception as exc:
            logger.warning(
                "GTT fallback broker position check failed sym=%s: %s",
                watch.trading_symbol,
                exc,
            )
            return False
        if not isinstance(positions, dict):
            return False

        def _symbol_key(value: Any) -> str:
            return "".join(ch for ch in str(value or "").upper() if ch.isalnum())

        aliases = {
            _symbol_key(watch.trading_symbol),
        }
        inst = watch.instrument
        if inst is not None:
            aliases.add(_symbol_key(getattr(inst, "trading_symbol", "")))
            aliases.add(_symbol_key(getattr(inst, "custom_symbol", "")))
            place_symbol = getattr(inst, "place_order_symbol", None)
            if callable(place_symbol):
                try:
                    aliases.add(_symbol_key(place_symbol()))
                except Exception:
                    pass
        aliases.discard("")

        for symbol, row in positions.items():
            if _symbol_key(symbol) not in aliases:
                continue
            try:
                qty = int(float((row or {}).get("qty", 0)))
            except (AttributeError, TypeError, ValueError):
                qty = 0
            if qty != 0:
                return True
        return False

    def _gtt_still_unfilled(self, watch: GttFallbackWatch, rec: Optional[Dict]) -> bool:
        if rec and rec.get("status") == IntentStatus.FILLED:
            return False
        broker = getattr(self._router, "broker", None)
        if broker and hasattr(broker, "find_forever_order_by_client_id"):
            try:
                order = broker.find_forever_order_by_client_id(watch.gtt_intent_id)
            except Exception:
                order = None
            if order:
                status = str(order.get("status") or "").lower()
                filled = float(order.get("filled_size") or 0)
                size = float(order.get("size") or 0)
                if status == "filled" or (size > 0 and filled >= size):
                    return False
                if status in ("cancelled", "rejected", "expired"):
                    return True
                return True
        if rec and rec.get("status") in (
            IntentStatus.SENT,
            IntentStatus.VALIDATED,
            IntentStatus.ACKED,
            IntentStatus.CREATED,
        ):
            return True
        return watch.phase == GttFallbackPhase.GTT

    def _log(self, event: str, message: str, **kwargs: Any) -> None:
        if self._engine_logger:
            try:
                self._engine_logger.log(event, message, **kwargs)
            except Exception:
                pass
        logger.info("%s: %s %s", event, message, kwargs)
