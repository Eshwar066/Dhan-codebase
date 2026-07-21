"""
ReentryAtCostBook: OMS-owned same-contract re-entry after MAIN_SL.

Strategies opt in by declaring ``reentry_at_cost`` on the MAIN ENTRY intent
(``metadata_extras`` / ``strategy_meta``) and/or as a class attribute::

    reentry_at_cost = {
        "enabled": True,
        "max_reentries": 1,
        "poll_interval_sec": 300,
        "min_premium": 0.1,
        "until_expiry": True,
    }

Flow:
  1. MAIN_SL fill → OMS arms a persisted wait (cost = entry premium).
  2. Engine / QuoteUpdated polls the book every poll_interval_sec.
  3. When option premium <= cost (and >= min_premium), OMS places MAIN ENTRY
     on the same contract with incremented reentry_count / structure_id :R{n}.
  4. Wait stops when: re-entry placed, MAIN opens on that contract, max
     reentries reached, or (if until_expiry) the option expiry day ends.

Persistence: ``logs/oms/reentry_at_cost.json`` (survives restart).

Event adapters (arm / tick / stop): ``core.events.handlers.reentry_at_cost``
(wired like GTT via ``core.events.wiring``).
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Callable, Dict, List, Optional
from zoneinfo import ZoneInfo

from core.models.order_intent import OrderIntent
from core.strategies.meta import (
    pack_strategy_meta,
    unpack_strategy_meta,
)

IST = ZoneInfo("Asia/Kolkata")
logger = logging.getLogger(__name__)

REENTRY_META_KEY = "reentry_at_cost"
DEFAULT_POLL_INTERVAL_SEC = 300
DEFAULT_MIN_PREMIUM = 0.1
DEFAULT_MAX_REENTRIES = 1


@dataclass
class ReentryAtCostWatch:
    watch_id: str
    strategy_id: str
    previous_structure_id: str
    trading_symbol: str
    underlying_symbol: str
    side: str  # entry side to re-place (typically SELL)
    qty: int
    strike: float
    expiry: str
    option_type: str
    cost_premium: float
    reentry_count: int  # count already used on the SL'd leg
    max_reentries: int = DEFAULT_MAX_REENTRIES
    poll_interval_sec: int = DEFAULT_POLL_INTERVAL_SEC
    min_premium: float = DEFAULT_MIN_PREMIUM
    until_expiry: bool = True
    armed_at_ist: str = ""
    last_poll_ts: float = 0.0
    metadata_extras: Dict[str, Any] = field(default_factory=dict)
    exchange: str = "DELTA"


def _parse_expiry_code(expiry: str) -> Optional[date]:
    raw = str(expiry or "").strip()
    if len(raw) != 6 or not raw.isdigit():
        return None
    try:
        return date(2000 + int(raw[4:6]), int(raw[2:4]), int(raw[0:2]))
    except ValueError:
        return None


def _next_structure_id(previous: str, reentry_count: int) -> str:
    base = re.sub(r":R\d+$", "", str(previous or "").strip())
    if not base:
        base = "REENTRY"
    return f"{base}:R{int(reentry_count)}"


def resolve_reentry_policy(
    strategy: Any,
    metadata_extras: Any,
) -> Optional[Dict[str, Any]]:
    """Merge strategy class/instance policy with per-trade metadata override."""
    policy: Dict[str, Any] = {}
    attr = getattr(strategy, "reentry_at_cost", None) if strategy is not None else None
    if isinstance(attr, dict):
        policy.update(attr)
    elif attr is True:
        policy["enabled"] = True

    payload = unpack_strategy_meta(metadata_extras) or {}
    if isinstance(metadata_extras, dict):
        raw = metadata_extras.get(REENTRY_META_KEY)
        if isinstance(raw, dict):
            policy.update(raw)
        elif raw is True:
            policy["enabled"] = True
    nested = payload.get(REENTRY_META_KEY) if isinstance(payload, dict) else None
    if isinstance(nested, dict):
        policy.update(nested)
    elif nested is True:
        policy["enabled"] = True

    if not policy:
        return None
    if not bool(policy.get("enabled", False)):
        return None
    return policy


class ReentryAtCostBook:
    """OMS book: arm on MAIN_SL, poll premium-to-cost, place same-contract ENTRY."""

    def __init__(
        self,
        order_router: Any,
        *,
        instrument_store: Any = None,
        engine_logger: Any = None,
        persist_path: Optional[str] = None,
    ) -> None:
        self._router = order_router
        self._instrument_store = instrument_store
        self._engine_logger = engine_logger
        self._lock = threading.Lock()
        self._watches: Dict[str, ReentryAtCostWatch] = {}
        logs_root = getattr(order_router, "_logs_root", None)
        if persist_path:
            self._persist_path = persist_path
        elif logs_root is not None:
            self._persist_path = str(os.path.join(str(logs_root), "oms", "reentry_at_cost.json"))
        else:
            self._persist_path = os.path.join("logs", "oms", "reentry_at_cost.json")
        self._premium_fn: Optional[Callable[..., Optional[float]]] = None
        self._strategy_resolver: Optional[Callable[[str], Any]] = None
        self._load()

    def set_premium_fn(self, fn: Optional[Callable[..., Optional[float]]]) -> None:
        """``fn(trading_symbol, *, side, strike, option_type, expiry) -> premium|None``."""
        self._premium_fn = fn

    def set_strategy_resolver(self, fn: Optional[Callable[[str], Any]]) -> None:
        self._strategy_resolver = fn

    def has_pending(self) -> bool:
        self._prune_expired()
        with self._lock:
            return bool(self._watches)

    def pending_count(self) -> int:
        with self._lock:
            return len(self._watches)

    # ---------- arm / stop ----------

    def maybe_arm_from_main_sl(
        self,
        *,
        strategy: Any,
        instrument: Any,
        structure_id: Optional[str],
        metadata_extras: Any = None,
        qty: Any = None,
        side: Any = None,
        price: Any = None,
        **_kwargs: Any,
    ) -> bool:
        """Arm a wait after MAIN_SL if strategy opted into reentry_at_cost."""
        if instrument is None or not structure_id:
            return False
        policy = resolve_reentry_policy(strategy, metadata_extras)
        if policy is None:
            return False

        allow_fn = getattr(strategy, "reentry_at_cost_allowed", None)
        if callable(allow_fn):
            try:
                if not allow_fn(metadata_extras):
                    return False
            except Exception as exc:
                logger.warning("reentry_at_cost_allowed failed: %s", exc)
                return False

        payload = unpack_strategy_meta(metadata_extras) or {}
        reentry_count = int(payload.get("reentry_count", 0) or 0)
        max_reentries = int(policy.get("max_reentries", DEFAULT_MAX_REENTRIES) or DEFAULT_MAX_REENTRIES)
        if reentry_count >= max_reentries:
            self._log(
                "reentry_at_cost_skipped_max",
                f"max_reentries={max_reentries} already used={reentry_count}",
                strategy=str(getattr(strategy, "name", "") or ""),
                structure_id=str(structure_id),
            )
            return False

        trading_symbol = str(getattr(instrument, "trading_symbol", "") or "")
        strike = float(getattr(instrument, "strike", 0) or 0)
        expiry = str(getattr(instrument, "expiry", "") or "")
        option_type = str(
            getattr(instrument, "option_type", None)
            or payload.get("option_type")
            or ""
        ).upper()
        if option_type in ("CALL",):
            option_type = "CE"
        elif option_type in ("PUT",):
            option_type = "PE"
        if not trading_symbol or strike <= 0 or not expiry:
            logger.warning(
                "reentry_at_cost arm skipped missing contract fields sid=%s",
                structure_id,
            )
            return False

        cost = payload.get("entry_premium")
        try:
            cost_f = float(cost) if cost is not None else float(price or 0)
        except (TypeError, ValueError):
            cost_f = float(price or 0)
        # MAIN_SL fill price is the stop (worse); cost must be original entry premium.
        if cost_f <= 0:
            logger.warning(
                "reentry_at_cost arm skipped bad cost sid=%s", structure_id
            )
            return False

        # Exit fill side is the cover; re-entry uses opposite (original entry side).
        exit_side = str(side or "").upper()
        if exit_side == "BUY":
            entry_side = "SELL"
        elif exit_side == "SELL":
            entry_side = "BUY"
        else:
            entry_side = "SELL"

        try:
            qty_i = max(1, int(qty or payload.get("qty_lots") or 1))
        except (TypeError, ValueError):
            qty_i = 1

        underlying = str(
            payload.get("symbol")
            or getattr(instrument, "underlying_symbol", None)
            or getattr(strategy, "underlying_symbols", ["BTCUSD"])[0]
            or ""
        ).upper()

        extras = dict(metadata_extras) if isinstance(metadata_extras, dict) else {}
        # Ensure policy is stamped on persisted extras for restore.
        extras[REENTRY_META_KEY] = {
            "enabled": True,
            "max_reentries": max_reentries,
            "poll_interval_sec": int(
                policy.get("poll_interval_sec", DEFAULT_POLL_INTERVAL_SEC)
                or DEFAULT_POLL_INTERVAL_SEC
            ),
            "min_premium": float(
                policy.get("min_premium", DEFAULT_MIN_PREMIUM) or DEFAULT_MIN_PREMIUM
            ),
            "until_expiry": bool(policy.get("until_expiry", True)),
        }

        watch = ReentryAtCostWatch(
            watch_id=str(structure_id),
            strategy_id=str(getattr(strategy, "name", "") or ""),
            previous_structure_id=str(structure_id),
            trading_symbol=trading_symbol,
            underlying_symbol=underlying,
            side=entry_side,
            qty=qty_i,
            strike=strike,
            expiry=expiry,
            option_type=option_type,
            cost_premium=cost_f,
            reentry_count=reentry_count,
            max_reentries=max_reentries,
            poll_interval_sec=max(
                30,
                int(
                    policy.get("poll_interval_sec", DEFAULT_POLL_INTERVAL_SEC)
                    or DEFAULT_POLL_INTERVAL_SEC
                ),
            ),
            min_premium=float(
                policy.get("min_premium", DEFAULT_MIN_PREMIUM) or DEFAULT_MIN_PREMIUM
            ),
            until_expiry=bool(policy.get("until_expiry", True)),
            armed_at_ist=datetime.now(IST).isoformat(),
            metadata_extras=extras,
            exchange=str(
                getattr(instrument, "exchange", None)
                or extras.get("exchange")
                or "DELTA"
            ),
        )
        with self._lock:
            self._watches[watch.watch_id] = watch
        self._save()
        self._log(
            "reentry_at_cost_armed",
            (
                f"contract={trading_symbol} cost={cost_f:.4f} "
                f"next_reentry={reentry_count + 1}/{max_reentries} expiry={expiry}"
            ),
            strategy=watch.strategy_id,
            structure_id=str(structure_id),
            symbol=underlying,
        )
        return True

    def on_position_opened(
        self,
        *,
        instrument: Any = None,
        strategy_id: Optional[str] = None,
        trading_symbol: Optional[str] = None,
        strike: Any = None,
        option_type: Any = None,
        expiry: Any = None,
        **_kwargs: Any,
    ) -> None:
        """Stop retries once MAIN is open again for this strike/contract."""
        ts = str(
            trading_symbol
            or (getattr(instrument, "trading_symbol", None) if instrument else None)
            or ""
        ).strip()
        try:
            strike_f = float(
                strike
                if strike is not None
                else (getattr(instrument, "strike", None) if instrument else 0)
                or 0
            )
        except (TypeError, ValueError):
            strike_f = 0.0
        ot = str(
            option_type
            or (getattr(instrument, "option_type", None) if instrument else None)
            or ""
        ).upper()
        if ot in ("CALL",):
            ot = "CE"
        elif ot in ("PUT",):
            ot = "PE"
        exp = str(
            expiry
            or (getattr(instrument, "expiry", None) if instrument else None)
            or ""
        ).strip()
        if not ts and strike_f <= 0:
            return
        drop: List[str] = []
        with self._lock:
            for wid, w in self._watches.items():
                if strategy_id and w.strategy_id != str(strategy_id):
                    continue
                if ts and w.trading_symbol == ts:
                    drop.append(wid)
                    continue
                if (
                    strike_f > 0
                    and abs(float(w.strike) - strike_f) < 1e-9
                    and (not ot or w.option_type == ot)
                    and (not exp or w.expiry == exp)
                ):
                    drop.append(wid)
            for wid in drop:
                self._watches.pop(wid, None)
        if drop:
            self._save()
            self._log(
                "reentry_at_cost_stopped",
                f"open contract trading_symbol={ts} strike={strike_f} dropped={drop}",
                strategy=str(strategy_id or ""),
            )

    def cancel_for_structure(self, structure_id: str) -> None:
        sid = str(structure_id or "")
        with self._lock:
            removed = self._watches.pop(sid, None)
        if removed is not None:
            self._save()

    def stop_for_trading_symbol(
        self,
        *,
        trading_symbol: Optional[str] = None,
        strategy_id: Optional[str] = None,
        structure_id: Optional[str] = None,
    ) -> None:
        """Cancel reentry-at-cost watches when broker confirms flat (manual exit / sync)."""
        ts = str(trading_symbol or "").strip()
        sid = str(structure_id or "").strip()
        drop: List[str] = []
        with self._lock:
            if sid and sid in self._watches:
                drop.append(sid)
            for wid, w in self._watches.items():
                if wid in drop:
                    continue
                if strategy_id and w.strategy_id != str(strategy_id):
                    continue
                if ts and w.trading_symbol == ts:
                    drop.append(wid)
            for wid in drop:
                self._watches.pop(wid, None)
        if drop:
            self._save()
            self._log(
                "reentry_at_cost_stopped",
                f"broker_flat_sync trading_symbol={ts} structure_id={sid} dropped={drop}",
                strategy=str(strategy_id or ""),
            )

    # ---------- poll / place ----------

    def tick(self) -> int:
        """Poll due watches; place re-entries when premium <= cost. Returns placed count."""
        self._prune_expired()
        now = datetime.now().timestamp()
        with self._lock:
            due = [
                w
                for w in self._watches.values()
                if (now - float(w.last_poll_ts or 0.0)) >= float(w.poll_interval_sec)
            ]
        placed = 0
        for watch in due:
            watch.last_poll_ts = now
            try:
                if self._try_place(watch):
                    placed += 1
            except Exception as exc:
                logger.warning(
                    "reentry_at_cost tick failed watch=%s: %s",
                    watch.watch_id,
                    exc,
                )
        if due:
            self._save()
        return placed

    def _try_place(self, watch: ReentryAtCostWatch) -> bool:
        if watch.reentry_count >= watch.max_reentries:
            self.cancel_for_structure(watch.watch_id)
            return False
        if self._contract_has_open_main(watch):
            self.on_position_opened(
                trading_symbol=watch.trading_symbol,
                strategy_id=watch.strategy_id,
                strike=watch.strike,
                option_type=watch.option_type,
                expiry=watch.expiry,
            )
            return False

        premium = self._current_premium(watch)
        if premium is None:
            return False
        if premium < float(watch.min_premium):
            return False
        if premium > float(watch.cost_premium):
            self._log(
                "reentry_at_cost_waiting",
                (
                    f"{watch.trading_symbol} prem={premium:.4f} "
                    f"cost={watch.cost_premium:.4f}"
                ),
                strategy=watch.strategy_id,
                structure_id=watch.previous_structure_id,
                symbol=watch.underlying_symbol,
            )
            return False

        intent = self._build_entry_intent(watch, premium)
        if intent is None:
            return False
        sym = watch.trading_symbol
        result = self._router.process_intent(intent, {sym: float(premium)})
        ok = isinstance(result, dict) and bool(result.get("ok"))
        if not ok:
            self._log(
                "reentry_at_cost_place_failed",
                f"contract={sym} premium={premium:.4f} result={result}",
                strategy=watch.strategy_id,
                structure_id=watch.previous_structure_id,
            )
            return False

        with self._lock:
            self._watches.pop(watch.watch_id, None)
        self._save()
        self._log(
            "reentry_at_cost_placed",
            (
                f"contract={sym} premium={premium:.4f} cost={watch.cost_premium:.4f} "
                f"structure_id={intent.structure_id} reentry={watch.reentry_count + 1}"
            ),
            strategy=watch.strategy_id,
            structure_id=intent.structure_id,
            symbol=watch.underlying_symbol,
        )
        return True

    def _build_entry_intent(
        self, watch: ReentryAtCostWatch, premium: float
    ) -> Optional[OrderIntent]:
        inst = self._resolve_instrument(watch)
        if inst is None:
            logger.warning(
                "reentry_at_cost instrument missing %s", watch.trading_symbol
            )
            return None
        next_count = int(watch.reentry_count) + 1
        structure_id = _next_structure_id(watch.previous_structure_id, next_count)

        # Guard against duplicate open / pending for the new structure id.
        pm = getattr(self._router, "position_manager", None)
        if pm is not None and callable(getattr(pm, "has_open_structure", None)):
            if pm.has_open_structure(
                strategy=watch.strategy_id, structure_id=structure_id, tag="MAIN"
            ):
                return None
        ist = getattr(self._router, "intent_store", None)
        if ist is not None and callable(getattr(ist, "has_pending_intent", None)):
            if ist.has_pending_intent(
                strategy=watch.strategy_id,
                structure_id=structure_id,
                tags=["MAIN"],
                actions=["ENTRY"],
            ):
                return None

        extras = self._metadata_for_reentry(watch, premium, next_count)
        return OrderIntent(
            intent_id=uuid.uuid4().hex,
            instrument=inst,
            side=str(watch.side or "SELL").upper(),
            qty=max(1, int(watch.qty or 1)),
            price=float(premium),
            order_type="LIMIT",
            strategy=watch.strategy_id,
            structure_id=structure_id,
            trade_type="MARGIN",
            tag="MAIN",
            symbol=watch.underlying_symbol,
            action="ENTRY",
            candle_ts=datetime.utcnow(),
            parent_intent_id=None,
            metadata_extras=extras,
            trigger_price=None,
        )

    def _metadata_for_reentry(
        self, watch: ReentryAtCostWatch, premium: float, reentry_count: int
    ) -> Dict[str, Any]:
        extras = dict(watch.metadata_extras or {})
        payload = unpack_strategy_meta(extras) or {}
        payload["entry_premium"] = float(premium)
        payload["reentry_count"] = int(reentry_count)
        payload["symbol"] = watch.underlying_symbol
        payload["option_type"] = watch.option_type
        payload[REENTRY_META_KEY] = {
            "enabled": True,
            "max_reentries": watch.max_reentries,
            "poll_interval_sec": watch.poll_interval_sec,
            "min_premium": watch.min_premium,
            "until_expiry": watch.until_expiry,
        }
        packed = pack_strategy_meta(watch.strategy_id, payload)
        # Preserve any legacy top-level keys already on extras.
        out = dict(extras)
        out.update(packed)
        # Keep commonly used legacy keys in sync when present.
        for key in ("btc_zero_dte", "btc_zero_dte_eleven_pm"):
            if key in out and isinstance(out[key], dict):
                out[key] = dict(payload)
        out[REENTRY_META_KEY] = payload[REENTRY_META_KEY]
        return out

    def _current_premium(self, watch: ReentryAtCostWatch) -> Optional[float]:
        if callable(self._premium_fn):
            try:
                px = self._premium_fn(
                    watch.trading_symbol,
                    side=watch.side,
                    strike=watch.strike,
                    option_type=watch.option_type,
                    expiry=watch.expiry,
                )
                if px is not None and float(px) > 0:
                    return float(px)
            except Exception as exc:
                logger.debug("reentry premium_fn failed: %s", exc)
        # Broker/source ticker fallback via router data if available.
        broker = getattr(self._router, "broker", None)
        get_ticker = getattr(broker, "get_ticker", None) if broker else None
        if not callable(get_ticker):
            source = getattr(broker, "source", None) if broker else None
            get_ticker = getattr(source, "get_ticker", None) if source else None
        if callable(get_ticker):
            try:
                ticker = get_ticker(watch.trading_symbol)
                if isinstance(ticker, dict):
                    quotes = ticker.get("quotes") or {}
                    if str(watch.side).upper() == "SELL":
                        bid = quotes.get("best_bid")
                        if bid is not None and float(bid) > 0:
                            return float(bid)
                    else:
                        ask = quotes.get("best_ask")
                        if ask is not None and float(ask) > 0:
                            return float(ask)
                    mark = ticker.get("mark_price") or ticker.get("close")
                    if mark is not None and float(mark) > 0:
                        return float(mark)
            except Exception:
                pass
        return None

    def _resolve_instrument(self, watch: ReentryAtCostWatch) -> Any:
        store = self._instrument_store or getattr(self._router, "instrument_store", None)
        if store is None:
            return None
        try:
            return store.intent_creation_details(
                watch.trading_symbol,
                watch.exchange,
                watch.expiry,
                watch.option_type,
                watch.strike,
            )
        except Exception as exc:
            logger.warning(
                "reentry_at_cost resolve failed %s: %s", watch.trading_symbol, exc
            )
            return None

    def _contract_has_open_main(self, watch: ReentryAtCostWatch) -> bool:
        pm = getattr(self._router, "position_manager", None)
        if pm is None:
            return False
        positions = getattr(pm, "positions", None)
        if isinstance(positions, dict):
            iterable = positions.values()
        elif callable(getattr(pm, "get_open_positions", None)):
            iterable = pm.get_open_positions(strategy=watch.strategy_id) or []
        else:
            return False
        for pos in iterable:
            if str(getattr(pos, "strategy", "") or "") not in ("", watch.strategy_id):
                # When iterating all positions, filter by strategy when present.
                strat = str(getattr(pos, "strategy", "") or "")
                if strat and strat != watch.strategy_id:
                    continue
            if str(getattr(pos, "tag", "") or "MAIN").upper() not in ("MAIN", ""):
                if str(getattr(pos, "tag", "") or "").upper() != "MAIN":
                    continue
            inst = getattr(pos, "instrument", None)
            sym = str(getattr(inst, "trading_symbol", "") or "")
            if sym and sym == watch.trading_symbol:
                qty = getattr(pos, "qty", None)
                try:
                    if qty is not None and int(qty) == 0:
                        continue
                except (TypeError, ValueError):
                    pass
                return True
        return False

    # ---------- persist / prune ----------

    def _prune_expired(self) -> None:
        today = datetime.now(IST).date()
        drop: List[str] = []
        with self._lock:
            for wid, w in self._watches.items():
                if w.reentry_count >= w.max_reentries:
                    drop.append(wid)
                    continue
                if not w.until_expiry:
                    continue
                exp = _parse_expiry_code(w.expiry)
                if exp is not None and today > exp:
                    drop.append(wid)
            for wid in drop:
                self._watches.pop(wid, None)
        if drop:
            self._save()
            self._log(
                "reentry_at_cost_expired",
                f"pruned={drop}",
            )

    def _watch_to_dict(self, w: ReentryAtCostWatch) -> dict:
        return {
            "watch_id": w.watch_id,
            "strategy_id": w.strategy_id,
            "previous_structure_id": w.previous_structure_id,
            "trading_symbol": w.trading_symbol,
            "underlying_symbol": w.underlying_symbol,
            "side": w.side,
            "qty": int(w.qty),
            "strike": float(w.strike),
            "expiry": w.expiry,
            "option_type": w.option_type,
            "cost_premium": float(w.cost_premium),
            "reentry_count": int(w.reentry_count),
            "max_reentries": int(w.max_reentries),
            "poll_interval_sec": int(w.poll_interval_sec),
            "min_premium": float(w.min_premium),
            "until_expiry": bool(w.until_expiry),
            "armed_at_ist": w.armed_at_ist,
            "last_poll_ts": float(w.last_poll_ts or 0.0),
            "metadata_extras": dict(w.metadata_extras or {}),
            "exchange": w.exchange,
        }

    def _watch_from_dict(self, raw: dict) -> Optional[ReentryAtCostWatch]:
        try:
            return ReentryAtCostWatch(
                watch_id=str(raw["watch_id"]),
                strategy_id=str(raw["strategy_id"]),
                previous_structure_id=str(
                    raw.get("previous_structure_id") or raw["watch_id"]
                ),
                trading_symbol=str(raw["trading_symbol"]),
                underlying_symbol=str(raw.get("underlying_symbol") or ""),
                side=str(raw.get("side") or "SELL").upper(),
                qty=int(raw.get("qty") or 1),
                strike=float(raw["strike"]),
                expiry=str(raw["expiry"]),
                option_type=str(raw.get("option_type") or "").upper(),
                cost_premium=float(raw["cost_premium"]),
                reentry_count=int(raw.get("reentry_count") or 0),
                max_reentries=int(raw.get("max_reentries") or DEFAULT_MAX_REENTRIES),
                poll_interval_sec=int(
                    raw.get("poll_interval_sec") or DEFAULT_POLL_INTERVAL_SEC
                ),
                min_premium=float(raw.get("min_premium") or DEFAULT_MIN_PREMIUM),
                until_expiry=bool(raw.get("until_expiry", True)),
                armed_at_ist=str(raw.get("armed_at_ist") or ""),
                last_poll_ts=float(raw.get("last_poll_ts") or 0.0),
                metadata_extras=dict(raw.get("metadata_extras") or {}),
                exchange=str(raw.get("exchange") or "DELTA"),
            )
        except (KeyError, TypeError, ValueError) as exc:
            logger.warning("reentry_at_cost skip bad watch row: %s", exc)
            return None

    def _load(self) -> None:
        path = self._persist_path
        if not os.path.isfile(path):
            return
        try:
            with open(path, encoding="utf-8") as f:
                payload = json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("reentry_at_cost load failed: %s", exc)
            return
        rows = payload.get("watches") if isinstance(payload, dict) else None
        if not isinstance(rows, dict):
            return
        loaded: Dict[str, ReentryAtCostWatch] = {}
        today = datetime.now(IST).date()
        for wid, raw in rows.items():
            if not isinstance(raw, dict):
                continue
            watch = self._watch_from_dict(raw)
            if watch is None:
                continue
            if watch.reentry_count >= watch.max_reentries:
                continue
            if watch.until_expiry:
                exp = _parse_expiry_code(watch.expiry)
                if exp is not None and today > exp:
                    continue
            loaded[str(wid)] = watch
        with self._lock:
            self._watches = loaded
        if loaded:
            logger.info("ReentryAtCostBook loaded %s watch(es)", len(loaded))

    def _save(self) -> None:
        path = self._persist_path
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with self._lock:
            watches = {wid: self._watch_to_dict(w) for wid, w in self._watches.items()}
        payload = {
            "version": 1,
            "updated_at_ist": datetime.now(IST).isoformat(),
            "watches": watches,
        }
        tmp = f"{path}.tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2, sort_keys=True)
            os.replace(tmp, path)
        except OSError as exc:
            logger.warning("reentry_at_cost save failed: %s", exc)

    def _log(self, event: str, message: str, **fields: Any) -> None:
        if self._engine_logger is not None:
            try:
                self._engine_logger.log(event, message, **fields)
                return
            except Exception:
                pass
        logger.info("%s %s %s", event, message, fields)
