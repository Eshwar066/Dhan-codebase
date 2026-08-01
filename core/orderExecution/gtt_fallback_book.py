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

import json
import logging
import threading
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, time
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Protocol, Tuple
from zoneinfo import ZoneInfo

from core.models.order_intent import OrderIntent
from core.orderExecution.intent_store import IntentStatus

IST = ZoneInfo("Asia/Kolkata")
logger = logging.getLogger(__name__)

DEFAULT_ACTIVE_UNTIL = time(15, 20)
# Dhan Forever statuses that mean the GTT already fired (child order live/filled).
# Placing a fallback LIMIT on top of these races into double entry.
_FOREVER_FIRED_STATUSES = frozenset(
    {"filled", "traded", "complete", "completed", "triggered"}
)


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
    # Skip fallback LIMIT when computed premium is >= this (strictly place only if < max).
    max_fallback_price: Optional[float] = None
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


def _parse_max_fallback_price(raw: Any) -> Optional[float]:
    try:
        val = float(raw)
    except (TypeError, ValueError):
        return None
    return val if val > 0 else None


def _fallback_price_allowed(watch: GttFallbackWatch, price: float) -> bool:
    """True when fallback LIMIT premium is strictly below max_fallback_price (if set)."""
    cap = watch.max_fallback_price
    if cap is None:
        return True
    try:
        return float(price) < float(cap)
    except (TypeError, ValueError):
        return False


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
        self._persist_path = self._resolve_persist_path(order_router)

    @staticmethod
    def _resolve_persist_path(order_router: Any) -> Path:
        logs_root = getattr(order_router, "_logs_root", None)
        if logs_root is None:
            logs_root = Path(__file__).resolve().parents[2] / "logs"
        engine_id = str(
            getattr(order_router, "_order_state_engine_id", None)
            or getattr(order_router, "engine_id", None)
            or "default"
        ).replace(" ", "_").replace("/", "_")
        path = Path(logs_root) / f"gtt_watches_{engine_id}.json"
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        return path

    def _watch_to_dict(self, watch: GttFallbackWatch) -> Dict[str, Any]:
        engine_sym = str(
            getattr(watch.instrument, "trading_symbol", None) or ""
        ).strip()
        # Intent.symbol is often the underlying (BANKNIFTY); broker positions use
        # the option contract. Prefer instrument / place-order symbol for restore.
        if not engine_sym or engine_sym.upper() in {"BANKNIFTY", "NIFTY", "SENSEX"}:
            engine_sym = str(watch.trading_symbol or watch.symbol or "").strip()
        return {
            "gtt_intent_id": watch.gtt_intent_id,
            "strategy_id": watch.strategy_id,
            "structure_id": watch.structure_id,
            "trading_symbol": watch.trading_symbol,
            "side": watch.side,
            "limit_price": watch.limit_price,
            "entry_date": watch.entry_date.isoformat(),
            "trigger_field": watch.trigger_field,
            "trigger_op": watch.trigger_op,
            "active_until": watch.active_until.strftime("%H:%M"),
            "phase": watch.phase.value if isinstance(watch.phase, GttFallbackPhase) else str(watch.phase),
            "fallback_intent_id": watch.fallback_intent_id,
            "broker_order_id": watch.broker_order_id,
            "metadata_extras": dict(watch.metadata_extras or {}),
            "qty": watch.qty,
            "symbol": engine_sym,
            "confirm_ticks": watch.confirm_ticks,
            "max_fallback_price": watch.max_fallback_price,
            "engine_symbol": engine_sym,
        }

    def _persist_watches(self) -> None:
        path = self._persist_path
        if path is None:
            return
        with self._lock:
            rows = [
                self._watch_to_dict(w)
                for w in self._watches.values()
                if w.phase in (GttFallbackPhase.GTT, GttFallbackPhase.FALLBACK_SENT)
            ]
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"watches": rows}, indent=2), encoding="utf-8")
        except OSError as exc:
            logger.warning("GttFallback persist failed path=%s: %s", path, exc)

    def _resolve_instrument(self, trading_symbol: str, engine_symbol: str = "") -> Any:
        store = self._instrument_store
        if store is None or not hasattr(store, "intent_creation_details"):
            return None
        for sym in (engine_symbol, trading_symbol):
            s = str(sym or "").strip()
            if not s:
                continue
            try:
                from core.orderExecution.position_manager import PositionManager

                opt, strike = PositionManager._extract_option_hint(s, "")
                inst = store.intent_creation_details(s, "NSE", None, opt, strike)
                if inst is not None:
                    return inst
            except Exception:
                continue
        return None

    def _ensure_intent_stub(self, watch: GttFallbackWatch) -> Optional[Dict[str, Any]]:
        """Rebuild a pending HYBRID_GTT ENTRY intent after process restart."""
        router = self._router
        store = getattr(router, "intent_store", None)
        if store is None:
            return None
        iid = str(watch.gtt_intent_id or "")
        if not iid:
            return None
        if store.exists(iid):
            rec = store.get(iid)
            if rec is not None and watch.broker_order_id and not rec.get("broker_order_id"):
                rec["broker_order_id"] = watch.broker_order_id
            if rec is not None and rec.get("instrument") is None and watch.instrument is not None:
                rec["instrument"] = watch.instrument
            return rec
        extras = dict(watch.metadata_extras or {})
        extras.setdefault("execution_mode", "HYBRID_GTT")
        engine_sym = str(
            getattr(watch.instrument, "trading_symbol", None) or ""
        ).strip()
        if not engine_sym or engine_sym.upper() in {"BANKNIFTY", "NIFTY", "SENSEX"}:
            engine_sym = str(watch.trading_symbol or watch.symbol or "").strip()
        payload = {
            "action": "ENTRY",
            "side": watch.side,
            "symbol": engine_sym,
            "trading_symbol": watch.trading_symbol,
            "price": watch.limit_price,
            "qty": watch.qty,
            "strategy": watch.strategy_id,
            "strategy_id": watch.strategy_id,
            "structure_id": watch.structure_id,
            "tag": "MAIN",
            "execution_mode": "HYBRID_GTT",
            "strategy_meta": extras,
            "engine_id": getattr(router, "engine_id", None),
        }
        rec = store.create(payload=payload, intent_id=iid)
        try:
            store.update(iid, IntentStatus.VALIDATED)
            store.update(
                iid,
                IntentStatus.SENT,
                broker_order_id=watch.broker_order_id,
            )
        except ValueError:
            pass
        rec = store.get(iid) or rec
        if watch.instrument is None:
            watch.instrument = self._resolve_instrument(
                watch.trading_symbol, engine_sym
            )
        if rec is not None:
            rec["instrument"] = watch.instrument
            rec["side"] = watch.side
            rec["qty"] = watch.qty
            rec["price"] = watch.limit_price
            rec["tag"] = "MAIN"
            rec["structure_id"] = watch.structure_id
            rec["strategy"] = watch.strategy_id
            rec["action"] = "ENTRY"
            rec["broker_order_id"] = watch.broker_order_id
            rec["strategy_meta"] = extras
        if hasattr(router, "_set_order_state"):
            try:
                from core.orderExecution.order_router import OrderState

                cur = getattr(router, "_order_state", {}).get(iid)
                if cur not in (
                    OrderState.FILLED,
                    OrderState.CANCELLED,
                    OrderState.REJECTED,
                ):
                    router._set_order_state(
                        iid,
                        OrderState.OPEN,
                        action="gtt_watch_restore",
                        message="Restored HYBRID_GTT watch after restart",
                    )
            except Exception:
                pass
        return rec

    def restore_from_disk(self) -> int:
        """Reload active watches persisted before restart; rebuild intent stubs."""
        path = self._persist_path
        if path is None or not path.is_file():
            return 0
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("GttFallback restore_from_disk failed: %s", exc)
            return 0
        rows = data.get("watches") if isinstance(data, dict) else None
        if not isinstance(rows, list):
            return 0
        today = datetime.now(IST).date()
        restored = 0
        for row in rows:
            if not isinstance(row, dict):
                continue
            iid = str(row.get("gtt_intent_id") or "")
            if not iid or iid in self._watches:
                continue
            phase = str(row.get("phase") or GttFallbackPhase.GTT.value).upper()
            if phase not in (
                GttFallbackPhase.GTT.value,
                GttFallbackPhase.FALLBACK_SENT.value,
            ):
                continue
            try:
                entry_d = date.fromisoformat(str(row.get("entry_date") or "")[:10])
            except ValueError:
                entry_d = today
            if entry_d != today:
                continue
            try:
                limit_price = float(row.get("limit_price") or 0)
            except (TypeError, ValueError):
                continue
            if limit_price <= 0:
                continue
            trading_symbol = str(row.get("trading_symbol") or "").strip()
            if not trading_symbol:
                continue
            engine_sym = str(row.get("engine_symbol") or row.get("symbol") or "")
            inst = self._resolve_instrument(trading_symbol, engine_sym)
            try:
                confirm_ticks = max(1, int(row.get("confirm_ticks") or 1))
            except (TypeError, ValueError):
                confirm_ticks = 1
            max_fb = _parse_max_fallback_price(row.get("max_fallback_price"))
            if max_fb is None:
                extras = row.get("metadata_extras") or {}
                fb = extras.get("gtt_fallback") if isinstance(extras, dict) else {}
                if isinstance(fb, dict):
                    max_fb = _parse_max_fallback_price(fb.get("max_fallback_price"))
            watch = GttFallbackWatch(
                gtt_intent_id=iid,
                strategy_id=str(row.get("strategy_id") or ""),
                structure_id=str(row.get("structure_id") or ""),
                trading_symbol=trading_symbol,
                side=str(row.get("side") or "BUY").upper(),
                limit_price=limit_price,
                entry_date=entry_d,
                trigger_field=str(row.get("trigger_field") or "ask"),
                trigger_op=str(row.get("trigger_op") or "<="),
                active_until=_parse_hhmm(row.get("active_until"), DEFAULT_ACTIVE_UNTIL),
                broker_order_id=str(row.get("broker_order_id") or "") or None,
                metadata_extras=dict(row.get("metadata_extras") or {}),
                instrument=inst,
                qty=int(row.get("qty") or 1),
                symbol=str(row.get("symbol") or engine_sym or ""),
                phase=GttFallbackPhase.FALLBACK_SENT
                if phase == GttFallbackPhase.FALLBACK_SENT.value
                else GttFallbackPhase.GTT,
                fallback_intent_id=str(row.get("fallback_intent_id") or "") or None,
                confirm_ticks=confirm_ticks,
                max_fallback_price=max_fb,
            )
            with self._lock:
                self._watches[iid] = watch
            self._ensure_intent_stub(watch)
            restored += 1
        if restored and self._subscribe_cb:
            syms = list({w.trading_symbol for w in self._watches.values()})
            try:
                self._subscribe_cb(syms)
            except Exception as exc:
                logger.warning("GttFallback restore subscribe failed: %s", exc)
        if restored:
            self._log(
                "gtt_fallback_restored",
                f"restored {restored} watch(es) from disk",
            )
        return restored

    def restore_missing_from_strategy_logs(self, *, include_filled: bool = False) -> int:
        """
        After a restart that wiped IntentStore, rebuild today's HYBRID_GTT watches
        from strategy JSON logs (gtt_fallback_registered / order_placed).
        """
        logs_root = getattr(self._router, "_logs_root", None)
        if logs_root is None:
            return 0
        order_state = getattr(self._router, "_order_state", {}) or {}
        terminal = set()
        try:
            from core.orderExecution.order_router import OrderState

            terminal = {
                OrderState.FILLED,
                OrderState.CANCELLED,
                OrderState.REJECTED,
            }
        except Exception:
            pass
        today = datetime.now(IST).date()
        # intent_id -> partial fields gathered from logs
        found: Dict[str, Dict[str, Any]] = {}
        for path in Path(logs_root).glob("*/*.log"):
            # Skip dated rotations like BankNiftyBTST.log.2026-07-23
            if path.suffix != ".log":
                continue
            try:
                lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
            except OSError:
                continue
            strategy_guess = path.parent.name
            for line in lines:
                if (
                    "gtt_fallback_registered" not in line
                    and "order_placed" not in line
                    and "signal_generated" not in line
                ):
                    continue
                try:
                    evt = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(evt, dict):
                    continue
                ts = str(evt.get("timestamp") or "")
                if len(ts) >= 10:
                    try:
                        if date.fromisoformat(ts[:10]) != today:
                            continue
                    except ValueError:
                        pass
                et = str(evt.get("event_type") or "")
                iid = str(evt.get("intent_id") or "")
                if not iid:
                    continue
                row = found.setdefault(
                    iid, {"intent_id": iid, "strategy_id": strategy_guess}
                )
                if et == "gtt_fallback_registered":
                    msg = str(evt.get("message") or "")
                    trading_symbol = ""
                    limit_price = 0.0
                    if "watch=" in msg:
                        rest = msg.split("watch=", 1)[1]
                        if " limit=" in rest:
                            trading_symbol, lim = rest.split(" limit=", 1)
                            trading_symbol = trading_symbol.strip()
                            try:
                                limit_price = float(lim.strip())
                            except ValueError:
                                limit_price = 0.0
                    if trading_symbol:
                        row["trading_symbol"] = trading_symbol
                    if limit_price > 0:
                        row["limit_price"] = limit_price
                    row["strategy_id"] = str(
                        evt.get("strategy_id")
                        or row.get("strategy_id")
                        or strategy_guess
                    )
                    row["from_gtt_log"] = True
                elif et == "order_placed":
                    oid = evt.get("order_id")
                    if oid:
                        row["broker_order_id"] = str(oid)
                    sym = str(evt.get("symbol") or "")
                    if sym:
                        row["engine_symbol"] = sym
                elif et == "signal_generated" and str(
                    evt.get("action") or ""
                ).upper() == "ENTRY":
                    try:
                        px = float(evt.get("price") or 0)
                    except (TypeError, ValueError):
                        px = 0.0
                    if px > 0:
                        row["limit_price"] = px
                    sym = str(evt.get("symbol") or "")
                    if sym:
                        row["engine_symbol"] = sym
                    row["strategy_id"] = str(
                        evt.get("strategy_id")
                        or row.get("strategy_id")
                        or strategy_guess
                    )

        restored = 0
        for iid, row in found.items():
            if not row.get("from_gtt_log"):
                continue
            if iid in self._watches:
                continue
            st = order_state.get(iid)
            # include_filled=True used by bracket rebind after restart.
            if st in terminal and not include_filled:
                continue
            trading_symbol = str(row.get("trading_symbol") or "").strip()
            engine_sym = str(row.get("engine_symbol") or "")
            try:
                limit_price = float(row.get("limit_price") or 0)
            except (TypeError, ValueError):
                limit_price = 0.0
            if not trading_symbol or limit_price <= 0:
                continue
            strategy_id = str(row.get("strategy_id") or "")
            # Reconstruct BTST structure_id when possible.
            structure_id = ""
            opt = "CE" if "CALL" in trading_symbol.upper() or engine_sym.upper().endswith("-CE") else (
                "PE" if "PUT" in trading_symbol.upper() or engine_sym.upper().endswith("-PE") else ""
            )
            if strategy_id and opt:
                structure_id = f"{strategy_id}:BANKNIFTY:{today.isoformat()}:{opt}"
            extras = {
                "execution_mode": "HYBRID_GTT",
                "gtt_fallback": {
                    "trigger_field": "ltp",
                    "trigger_op": ">=",
                    "active_until": "15:20",
                    "confirm_ticks": 2,
                    "max_fallback_price": 170.0,
                },
            }
            if strategy_id == "BankNiftyBTST" and opt:
                extras["banknifty_btst"] = {
                    "symbol": "BANKNIFTY",
                    "entry_date": today.isoformat(),
                    "option_type": opt,
                    "ref_premium": limit_price / 1.5,
                    "limit_price": limit_price,
                }
            inst = self._resolve_instrument(trading_symbol, engine_sym)
            watch = GttFallbackWatch(
                gtt_intent_id=iid,
                strategy_id=strategy_id,
                structure_id=structure_id,
                trading_symbol=trading_symbol,
                side="BUY",
                limit_price=limit_price,
                entry_date=today,
                trigger_field="ltp",
                trigger_op=">=",
                active_until=DEFAULT_ACTIVE_UNTIL,
                broker_order_id=str(row.get("broker_order_id") or "") or None,
                metadata_extras=extras,
                instrument=inst,
                qty=1,
                symbol=engine_sym or trading_symbol,
                phase=GttFallbackPhase.GTT,
                confirm_ticks=2,
                max_fallback_price=170.0 if strategy_id == "BankNiftyBTST" else None,
            )
            with self._lock:
                self._watches[iid] = watch
            self._ensure_intent_stub(watch)
            restored += 1
        if restored:
            self._persist_watches()
            if self._subscribe_cb:
                try:
                    self._subscribe_cb(
                        list({w.trading_symbol for w in self._watches.values()})
                    )
                except Exception:
                    pass
            self._log(
                "gtt_fallback_restored",
                f"restored {restored} watch(es) from strategy logs",
            )
        return restored

    def rebind_filled_legs_for_brackets(
        self, broker_positions: Dict[str, Any]
    ) -> int:
        """
        After restart, FILLED HYBRID_GTT intents are skipped by adopt. If the broker
        still holds the leg, re-attach ownership metadata only.

        Do NOT call the MAIN fill / MAIN_SL hook here — LiveEngine's
        ``_ensure_bracket_legs_after_reconcile`` is the single arm path. Calling
        both produced duplicate STOPLIMIT SLs (see 2026-07-24 10:19 PE).
        """
        if not broker_positions:
            return 0
        router = self._router
        pm = getattr(router, "position_manager", None)
        if pm is None:
            return 0
        from core.utils.expiry_resolver import ExpiryResolver

        # Ensure today's log-based watches exist even if already FILLED locally.
        logs_root = getattr(router, "_logs_root", None)
        today = datetime.now(IST).date()
        candidates: Dict[str, Dict[str, Any]] = {}
        with self._lock:
            for w in self._watches.values():
                candidates[w.gtt_intent_id] = {
                    "intent_id": w.gtt_intent_id,
                    "strategy_id": w.strategy_id,
                    "structure_id": w.structure_id,
                    "trading_symbol": w.trading_symbol,
                    "limit_price": w.limit_price,
                    "broker_order_id": w.broker_order_id,
                    "metadata_extras": dict(w.metadata_extras or {}),
                    "instrument": w.instrument,
                    "qty": w.qty,
                    "side": w.side,
                }
        if logs_root is not None:
            # Pull FILLED legs that were dropped from the watch file after adopt.
            self.restore_missing_from_strategy_logs(include_filled=True)
            with self._lock:
                for w in self._watches.values():
                    candidates.setdefault(
                        w.gtt_intent_id,
                        {
                            "intent_id": w.gtt_intent_id,
                            "strategy_id": w.strategy_id,
                            "structure_id": w.structure_id,
                            "trading_symbol": w.trading_symbol,
                            "limit_price": w.limit_price,
                            "broker_order_id": w.broker_order_id,
                            "metadata_extras": dict(w.metadata_extras or {}),
                            "instrument": w.instrument,
                            "qty": w.qty,
                            "side": w.side,
                        },
                    )

        rebound = 0
        for iid, row in candidates.items():
            trading_symbol = str(row.get("trading_symbol") or "")
            if not trading_symbol:
                continue
            want = {
                "".join(ch for ch in trading_symbol.upper() if ch.isalnum()),
            }
            ik = ExpiryResolver.option_identity_key(trading_symbol)
            if ik:
                want.add(ik)
            matched_sym = None
            matched_bp = None
            for b_sym, bp in broker_positions.items():
                try:
                    qty = int((bp or {}).get("qty") or 0)
                except (TypeError, ValueError):
                    qty = 0
                if qty == 0:
                    continue
                b_keys = {
                    "".join(ch for ch in str(b_sym).upper() if ch.isalnum()),
                }
                bik = ExpiryResolver.option_identity_key(str(b_sym))
                if bik:
                    b_keys.add(bik)
                if want & b_keys:
                    matched_sym = str(b_sym)
                    matched_bp = bp
                    break
            if not matched_sym or matched_bp is None:
                continue

            watch = GttFallbackWatch(
                gtt_intent_id=str(iid),
                strategy_id=str(row.get("strategy_id") or ""),
                structure_id=str(row.get("structure_id") or ""),
                trading_symbol=trading_symbol,
                side=str(row.get("side") or "BUY").upper(),
                limit_price=float(row.get("limit_price") or 0),
                entry_date=today,
                broker_order_id=str(row.get("broker_order_id") or "") or None,
                metadata_extras=dict(row.get("metadata_extras") or {}),
                instrument=row.get("instrument"),
                qty=int(row.get("qty") or 1),
                symbol=matched_sym,
                phase=GttFallbackPhase.GTT,
            )
            if watch.instrument is None:
                watch.instrument = self._resolve_instrument(
                    trading_symbol, matched_sym
                )
            if watch.instrument is not None and matched_sym:
                try:
                    watch.instrument.trading_symbol = matched_sym
                except Exception:
                    pass
            rec = self._ensure_intent_stub(watch)
            if rec is None:
                continue
            extras = dict(row.get("metadata_extras") or {})
            strategy = str(row.get("strategy_id") or "") or None
            structure_id = str(row.get("structure_id") or "") or None
            try:
                avg = float(
                    matched_bp.get("avg_price") or watch.limit_price or 0
                )
            except (TypeError, ValueError):
                avg = float(watch.limit_price or 0)
            try:
                with pm._lock:
                    pm._merge_position_metadata(
                        matched_sym,
                        strategy=strategy,
                        structure_id=structure_id,
                        tag="MAIN",
                        intent_id=str(iid),
                        metadata_extras=extras,
                    )
                    pos = pm.positions.get(matched_sym)
                    if pos is not None:
                        if strategy:
                            pos.strategy = strategy
                        if structure_id:
                            pos.structure_id = structure_id
                        pos.tag = "MAIN"
                        pos.intent_id = str(iid)
                        if avg > 0 and not float(getattr(pos, "avg_price", 0) or 0):
                            pos.avg_price = avg
                        if watch.instrument is not None:
                            # Prefer resolved lot_size over bare reconcile Instrument(lot=1).
                            try:
                                lot = int(getattr(watch.instrument, "lot_size", 0) or 0)
                                if lot > 1:
                                    pos.instrument.lot_size = lot
                            except Exception:
                                pass
                rebound += 1
            except Exception as exc:
                logger.warning(
                    "GttFallback rebind metadata failed intent=%s: %s",
                    iid,
                    exc,
                )
        return rebound

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
            max_fallback_price=_parse_max_fallback_price(fb.get("max_fallback_price")),
        )
        with self._lock:
            self._watches[watch.gtt_intent_id] = watch
        if self._subscribe_cb:
            try:
                self._subscribe_cb([watch.trading_symbol])
            except Exception as exc:
                logger.warning("GttFallback subscribe failed: %s", exc)
        self._persist_watches()
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
        self._persist_watches()

    def cancel_watch(self, intent_id: str, *, reason: str = "cancelled") -> None:
        with self._lock:
            w = self._watches.get(str(intent_id or ""))
            if w is None:
                return
            w.phase = GttFallbackPhase.CANCELLED
        self._persist_watches()
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
            store = getattr(self._router, "intent_store", None)
            rec = store.get(w.gtt_intent_id) if store else None
            if self._adopt_fill_from_broker(w, rec):
                self.on_fill(w.gtt_intent_id)
                self._log(
                    "gtt_fallback_position_detected",
                    f"adopted fill at strategy cutoff {w.trading_symbol}",
                    intent_id=w.gtt_intent_id,
                )
                continue
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
                    max_fallback_price=_parse_max_fallback_price(
                        fb.get("max_fallback_price")
                    ),
                )
                with self._lock:
                    self._watches[iid] = watch
                self._ensure_intent_stub(watch)
                restored += 1
        if restored and self._subscribe_cb:
            syms = list({w.trading_symbol for w in self._watches.values()})
            try:
                self._subscribe_cb(syms)
            except Exception as exc:
                logger.warning("GttFallback restore subscribe failed: %s", exc)
        if restored:
            self._persist_watches()
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
            # PM already has the leg (e.g. broker reconcile) — still adopt so
            # MAIN_SL / metadata hooks run if the GTT intent is not FILLED yet.
            if self._adopt_fill_from_broker(watch, rec):
                self.on_fill(watch.gtt_intent_id)
                return
            self.on_fill(watch.gtt_intent_id)
            return

        # Forever status often lags the actual fill. Periodically adopt from broker
        # positions even when quotes are unavailable (instrument lookup failures).
        if self._maybe_adopt_broker_open_fill(watch, rec, force=False):
            return

        slot_t = now_ist.time().replace(second=0, microsecond=0)
        if slot_t > watch.active_until and watch.entry_date == now_ist.date():
            # Last-chance adopt before cutting off an already-filled Forever order.
            if self._maybe_adopt_broker_open_fill(watch, rec, force=True):
                return
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
        if quote is None:
            # Quotes failed (common when place-order symbol ≠ engine symbol); still
            # try broker position truth so SL is not stranded after a GTT fill.
            self._maybe_adopt_broker_open_fill(watch, rec, force=False)
            watch._trigger_hits = 0
            return
        if not _trigger_met(watch, quote):
            watch._trigger_hits = 0
            return

        watch._trigger_hits = int(getattr(watch, "_trigger_hits", 0) or 0) + 1
        if watch._trigger_hits < max(1, int(watch.confirm_ticks or 1)):
            return

        # Premium reached GTT price; only fall back if Forever still unfilled.
        # Broker position truth is checked here (rather than on every quote) because
        # a Forever fill can reach Dhan positions before its order/fill update reaches
        # the local PositionManager.
        if self._adopt_if_already_in(watch, rec):
            return
        if not self._gtt_still_unfilled(watch, rec):
            if self._adopt_fill_from_broker(watch, rec):
                self.on_fill(watch.gtt_intent_id)
                return
            # Forever reports filled/cancelled but adopt failed — keep watching
            # briefly so a later broker-position poll can still arm SL.
            return

        # Re-poll Forever book once more before cancel (broker may have just triggered).
        if rec and hasattr(router, "_try_sync_gtt_intent_fill"):
            if router._try_sync_gtt_intent_fill(rec):
                self.on_fill(watch.gtt_intent_id)
                return
        if not self._gtt_still_unfilled(watch, store.get(watch.gtt_intent_id) if store else None):
            if self._adopt_fill_from_broker(watch, rec):
                self.on_fill(watch.gtt_intent_id)
            return
        if self._adopt_if_already_in(watch, rec):
            return

        # Price-cap check BEFORE cancelling Forever so we do not abandon GTT
        # only to refuse the LIMIT (Jul 24 CE chased ask @190).
        fallback_price = _fallback_limit_price(watch, quote)
        if not _fallback_price_allowed(watch, fallback_price):
            self._log(
                "gtt_fallback_price_cap_skip",
                f"skip LIMIT @ {fallback_price} "
                f"(max_fallback_price={watch.max_fallback_price}) "
                f"{watch.trading_symbol}",
                intent_id=watch.gtt_intent_id,
            )
            # If Forever already fired, adopt; else cancel Forever + watch — do not chase.
            if self._forever_already_fired(watch) or self._broker_position_open(watch):
                if self._adopt_fill_from_broker(watch, rec):
                    self.on_fill(watch.gtt_intent_id)
                return
            router.cancel_gtt_fallback_watch(watch, reason="fallback_price_cap")
            self._cancel_open_child_day_orders(watch)
            self.cancel_watch(watch.gtt_intent_id, reason="fallback_price_cap")
            return

        if watch.phase == GttFallbackPhase.GTT:
            cancelled = router.cancel_gtt_fallback_watch(watch, reason="fallback_trigger")
            if not cancelled:
                # Cancel failed OR Forever already TRIGGERED/filled — adopt, never stack LIMIT.
                if self._adopt_fill_from_broker(watch, rec):
                    self.on_fill(watch.gtt_intent_id)
                    self._log(
                        "gtt_fallback_triggered_adopt",
                        f"Forever already fired; skip LIMIT {watch.trading_symbol}",
                        intent_id=watch.gtt_intent_id,
                    )
                    return
                self._log(
                    "gtt_fallback_cancel_failed",
                    f"skip LIMIT; Forever still open {watch.trading_symbol}",
                    intent_id=watch.gtt_intent_id,
                )
                return

        # Post-cancel race: Forever child may have filled while we cancelled parent.
        if self._adopt_if_already_in(watch, store.get(watch.gtt_intent_id) if store else None):
            return
        self._cancel_open_child_day_orders(watch)
        if self._broker_position_open(watch):
            if self._adopt_fill_from_broker(watch, rec):
                self.on_fill(watch.gtt_intent_id)
                self._log(
                    "gtt_fallback_position_detected",
                    f"adopted fill after Forever cancel; skip LIMIT "
                    f"{watch.trading_symbol}",
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

        # Recompute ask after cancel; re-check price cap on the final quote.
        fallback_price = _fallback_limit_price(watch, quote)
        if not _fallback_price_allowed(watch, fallback_price):
            self._log(
                "gtt_fallback_price_cap_skip",
                f"skip LIMIT @ {fallback_price} after cancel "
                f"(max_fallback_price={watch.max_fallback_price}) "
                f"{watch.trading_symbol}",
                intent_id=watch.gtt_intent_id,
            )
            self.cancel_watch(watch.gtt_intent_id, reason="fallback_price_cap")
            return

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

    def _adopt_if_already_in(
        self, watch: GttFallbackWatch, rec: Optional[Dict]
    ) -> bool:
        """Adopt + complete watch when broker already has the leg or Forever fired."""
        if not (
            self._broker_position_open(watch) or self._forever_already_fired(watch)
        ):
            return False
        if self._adopt_fill_from_broker(watch, rec):
            self.on_fill(watch.gtt_intent_id)
            self._log(
                "gtt_fallback_position_detected",
                f"adopted fill + skip LIMIT; broker already in "
                f"{watch.trading_symbol}",
                intent_id=watch.gtt_intent_id,
            )
            return True
        self._log(
            "gtt_fallback_position_detected",
            f"broker already in but adopt failed; keep watching "
            f"{watch.trading_symbol}",
            intent_id=watch.gtt_intent_id,
        )
        return True

    def _forever_already_fired(self, watch: GttFallbackWatch) -> bool:
        """True when Dhan Forever is TRIGGERED/TRADED (child may be live or filled)."""
        broker = getattr(self._router, "broker", None)
        if not broker or not hasattr(broker, "find_forever_order_by_client_id"):
            return False
        try:
            order = broker.find_forever_order_by_client_id(watch.gtt_intent_id)
        except Exception:
            return False
        if not order:
            return False
        status = str(order.get("status") or "").lower()
        filled = float(order.get("filled_size") or 0)
        size = float(order.get("size") or 0)
        if status in _FOREVER_FIRED_STATUSES:
            return True
        return size > 0 and filled >= size

    def _cancel_open_child_day_orders(self, watch: GttFallbackWatch) -> int:
        """
        Cancel resting day BUY/SELL orders on this contract left by a Forever child
        (often correlationId=NR) so fallback LIMIT cannot stack on top.
        """
        broker = getattr(self._router, "broker", None)
        cancel_fn = getattr(broker, "cancel_open_day_orders_for_symbol", None)
        if not callable(cancel_fn):
            return 0
        try:
            n = int(
                cancel_fn(
                    watch.trading_symbol,
                    side=str(watch.side or "BUY").upper(),
                    exclude_order_ids={
                        str(watch.broker_order_id or ""),
                        str(watch.fallback_intent_id or ""),
                    },
                )
                or 0
            )
        except Exception as exc:
            logger.warning(
                "GTT child day-order cancel failed sym=%s: %s",
                watch.trading_symbol,
                exc,
            )
            return 0
        if n:
            self._log(
                "gtt_fallback_child_cancelled",
                f"cancelled {n} open day order(s) on {watch.trading_symbol}",
                intent_id=watch.gtt_intent_id,
            )
        return n

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

    def _adopt_fill_from_broker(
        self, watch: GttFallbackWatch, rec: Optional[Dict]
    ) -> bool:
        """Sync GTT ENTRY fill from Forever APIs or broker position so MAIN_SL arms."""
        router = self._router
        store = getattr(router, "intent_store", None)
        if rec is None and store:
            rec = store.get(watch.gtt_intent_id)
        if not rec:
            return False
        if hasattr(router, "_try_sync_gtt_intent_fill"):
            try:
                if router._try_sync_gtt_intent_fill(rec):
                    return True
            except Exception as exc:
                logger.warning(
                    "GTT fill sync failed intent=%s: %s", watch.gtt_intent_id, exc
                )
        if hasattr(router, "adopt_gtt_intent_from_broker_positions"):
            try:
                return bool(router.adopt_gtt_intent_from_broker_positions(rec))
            except Exception as exc:
                logger.warning(
                    "GTT broker-position adopt failed intent=%s: %s",
                    watch.gtt_intent_id,
                    exc,
                )
        return False

    def _maybe_adopt_broker_open_fill(
        self,
        watch: GttFallbackWatch,
        rec: Optional[Dict],
        *,
        force: bool = False,
    ) -> bool:
        """Throttled broker-position adopt for watches whose Forever status is stale."""
        import time as _time

        now = _time.monotonic()
        last = float(getattr(watch, "_last_broker_pos_check", 0.0) or 0.0)
        if not force and (now - last) < 15.0:
            return False
        watch._last_broker_pos_check = now
        if not self._broker_position_open(watch):
            return False
        adopted = self._adopt_fill_from_broker(watch, rec)
        if not adopted:
            self._log(
                "gtt_fallback_position_detected",
                f"broker position open but adopt failed {watch.trading_symbol}",
                intent_id=watch.gtt_intent_id,
            )
            return False
        self.on_fill(watch.gtt_intent_id)
        self._log(
            "gtt_fallback_position_detected",
            f"adopted fill; broker position already open {watch.trading_symbol}",
            intent_id=watch.gtt_intent_id,
        )
        return True

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
                # TRIGGERED = Forever fired (child live/filled) — never treat as unfilled.
                if status in _FOREVER_FIRED_STATUSES or (
                    size > 0 and filled >= size
                ):
                    return False
                if status in ("cancelled", "rejected", "expired"):
                    # Terminal without fill → eligible for fallback LIMIT.
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
