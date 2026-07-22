"""
Delta OMS Execution Validator.

Pre-trade / pre-stop gates for option liquidity and mark-vs-book sanity.
Venue-aware: enabled for DELTA by default; no-op elsewhere unless configured.

Use mark only for risk validation — never as the execution price.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass
class MarketSnapshot:
    """Single-point market view for one contract (prefer one source + timestamps)."""

    symbol: str
    bid: Optional[float] = None
    ask: Optional[float] = None
    ltp: Optional[float] = None
    mark: Optional[float] = None
    ts: Optional[float] = None  # unix seconds when snapshot was observed
    bid_size: Optional[float] = None
    ask_size: Optional[float] = None
    source: str = ""


@dataclass
class ValidationResult:
    ok: bool
    reason: str = ""
    details: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def accept(cls, **details: Any) -> "ValidationResult":
        return cls(ok=True, reason="", details=dict(details))

    @classmethod
    def reject(cls, reason: str, **details: Any) -> "ValidationResult":
        return cls(ok=False, reason=str(reason or "rejected"), details=dict(details))


@dataclass
class ExecutionValidatorConfig:
    """Tunable gates. Start loose on mark/mid; tighten per product later."""

    enabled: bool = True
    venue: str = "DELTA"
    max_spread_pct: float = 0.10
    max_mark_mid_pct: float = 0.50
    max_quote_age_sec: float = 30.0
    require_bid_ask: bool = True
    require_mark: bool = True
    validate_entry: bool = True
    validate_stop: bool = True
    # Short-option buy-to-cover stop must sit above mark by this ratio (1.0 = strictly > mark).
    min_stop_mark_ratio: float = 1.0
    # When ENTRY metadata has sl_premium_mult (or infer flag), SL ≈ entry * mult.
    default_sl_premium_mult: float = 2.0
    # If True, invent planned SL from default_sl_premium_mult even without strategy stamp.
    # Keep False so underlying-stop strategies (e.g. DOS spot SL) are not false-skipped.
    infer_entry_sl_from_default_mult: bool = False
    # Optional minimum book size at best bid/ask (None / 0 = disabled).
    min_book_size: float = 0.0
    # If True, EXIT / protective FORCE_EXIT (non-SL resting stops) are never blocked.
    skip_protective_exits: bool = True
    # Stop trigger methods that are not compared against option mark_price.
    non_mark_stop_methods: Tuple[str, ...] = (
        "spot_price",
        "underlying",
        "index",
        "last_price",
    )


def _pos_float(v: Any) -> Optional[float]:
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if f != f or f <= 0:
        return None
    return f


def snapshot_from_ticker(
    symbol: str,
    ticker: Optional[Dict[str, Any]],
    *,
    bid: Optional[float] = None,
    ask: Optional[float] = None,
    bid_size: Optional[float] = None,
    ask_size: Optional[float] = None,
    source: str = "ticker",
) -> MarketSnapshot:
    """Build a MarketSnapshot from a Delta-style ticker dict + optional L2 top."""
    t = ticker if isinstance(ticker, dict) else {}
    quotes = t.get("quotes") if isinstance(t.get("quotes"), dict) else {}

    bid_f = _pos_float(bid)
    ask_f = _pos_float(ask)
    if bid_f is None:
        bid_f = _pos_float(
            t.get("bid")
            or t.get("best_bid")
            or quotes.get("bid")
            or quotes.get("best_bid")
        )
    if ask_f is None:
        ask_f = _pos_float(
            t.get("ask")
            or t.get("best_ask")
            or quotes.get("ask")
            or quotes.get("best_ask")
        )

    mark = _pos_float(
        t.get("mark_price")
        or t.get("mark")
        or quotes.get("mark_price")
    )
    ltp = _pos_float(
        t.get("last_price")
        or t.get("close")
        or t.get("spot_price")
        or quotes.get("last_price")
    )

    ts = t.get("timestamp") or t.get("generated_at") or t.get("ts")
    try:
        ts_f = float(ts) if ts is not None else None
    except (TypeError, ValueError):
        ts_f = None
    if ts_f is not None and ts_f > 1e12:
        ts_f = ts_f / 1e6

    return MarketSnapshot(
        symbol=str(symbol or ""),
        bid=bid_f,
        ask=ask_f,
        ltp=ltp,
        mark=mark,
        ts=ts_f,
        bid_size=_pos_float(bid_size),
        ask_size=_pos_float(ask_size),
        source=source,
    )


def _metadata_payload(intent: Any) -> Dict[str, Any]:
    extras = getattr(intent, "metadata_extras", None)
    if not isinstance(extras, dict):
        return {}
    nested = extras.get("strategy_meta")
    if isinstance(nested, dict):
        return {**extras, **nested}
    return extras


def _stop_trigger_method(intent: Any) -> str:
    payload = _metadata_payload(intent)
    method = (
        payload.get("stop_trigger_method")
        or payload.get("trigger_method")
        or ""
    )
    if not method:
        for v in payload.values():
            if isinstance(v, dict) and v.get("stop_trigger_method"):
                method = v.get("stop_trigger_method")
                break
    return str(method or "").strip().lower()


def planned_sl_trigger_from_intent(
    intent: Any,
    *,
    entry_price: Optional[float] = None,
    default_sl_premium_mult: float = 2.0,
    infer_from_default_mult: bool = False,
) -> Optional[float]:
    """
    Resolve intended premium stop from ENTRY metadata.

    Looks for planned_sl_trigger / sl_trigger first. Otherwise, only estimates
    entry_premium * mult when the strategy stamped ``sl_premium_mult`` (or when
    ``infer_from_default_mult`` is True).
    """
    extras = _metadata_payload(intent)

    for key in ("planned_sl_trigger", "sl_trigger", "stop_loss_trigger"):
        trig = _pos_float(extras.get(key))
        if trig is not None:
            return trig

    # Nested strategy buckets may hold the same keys.
    payload = extras
    entry_prem = _pos_float(payload.get("entry_premium"))
    if entry_prem is None:
        for v in payload.values():
            if isinstance(v, dict) and "entry_premium" in v:
                entry_prem = _pos_float(v.get("entry_premium"))
                if entry_prem is not None:
                    payload = v
                    for key in ("planned_sl_trigger", "sl_trigger", "stop_loss_trigger"):
                        trig = _pos_float(payload.get(key))
                        if trig is not None:
                            return trig
                    break

    mult = _pos_float(
        payload.get("sl_premium_mult")
        or payload.get("SL_PREM_MULT")
        or extras.get("sl_premium_mult")
        or extras.get("SL_PREM_MULT")
    )
    if mult is None and not infer_from_default_mult:
        return None
    if mult is None:
        mult = float(default_sl_premium_mult or 2.0)

    base = entry_prem if entry_prem is not None else _pos_float(entry_price)
    if base is None:
        base = _pos_float(getattr(intent, "price", None))
    if base is None:
        return None
    return float(base) * float(mult)


def trigger_price_from_intent(intent: Any) -> Optional[float]:
    trig = _pos_float(getattr(intent, "trigger_price", None))
    if trig is not None:
        return trig
    extras = getattr(intent, "metadata_extras", None)
    if isinstance(extras, dict):
        for key in ("trigger_price", "planned_sl_trigger", "sl_trigger"):
            trig = _pos_float(extras.get(key))
            if trig is not None:
                return trig
    return _pos_float(getattr(intent, "price", None))


class ExecutionValidator:
    """
    Hard gates for Delta option ENTRY and MAIN_SL placement.

    Protective EXIT / FORCE_EXIT closes are not blocked (skip_protective_exits).
    """

    def __init__(
        self,
        config: Optional[ExecutionValidatorConfig] = None,
        *,
        snapshot_provider: Optional[Callable[[str], Optional[MarketSnapshot]]] = None,
        venue: Optional[str] = None,
    ) -> None:
        self.config = config or ExecutionValidatorConfig()
        self.snapshot_provider = snapshot_provider
        if venue:
            self.config.venue = str(venue).upper()

    def applies_to_venue(self, venue: Optional[str]) -> bool:
        if not self.config.enabled:
            return False
        want = str(self.config.venue or "DELTA").upper()
        got = str(venue or "").upper()
        return bool(want) and want == got

    def resolve_snapshot(self, symbol: str) -> Optional[MarketSnapshot]:
        if not symbol or self.snapshot_provider is None:
            return None
        try:
            return self.snapshot_provider(str(symbol))
        except Exception as exc:
            logger.warning("execution_validator snapshot failed for %s: %s", symbol, exc)
            return None

    def validate_intent(
        self,
        intent: Any,
        *,
        venue: Optional[str] = None,
        snapshot: Optional[MarketSnapshot] = None,
        exec_price: Optional[float] = None,
        planned_sl_trigger: Optional[float] = None,
    ) -> ValidationResult:
        """
        Validate an OrderIntent before broker submit.

        ENTRY (especially short options): book + mark/mid + planned SL vs mark.
        MAIN_SL / stop FORCE_EXIT: stop trigger vs mark.
        Protective EXIT: pass-through.
        """
        if not self.applies_to_venue(venue):
            return ValidationResult.accept(skipped=True, reason="venue_mismatch_or_disabled")

        action = str(getattr(intent, "action", "ENTRY") or "ENTRY").upper()
        tag = str(getattr(intent, "tag", "") or "").upper()
        side = str(getattr(intent, "side", "") or "").upper()
        inst = getattr(intent, "instrument", None)
        symbol = str(
            getattr(inst, "trading_symbol", None)
            or getattr(intent, "symbol", None)
            or ""
        ).strip()

        is_stop = tag == "MAIN_SL" or (
            action == "FORCE_EXIT" and tag == "MAIN_SL"
        )
        is_protective_exit = action in ("EXIT", "FORCE_EXIT") and not is_stop

        if is_protective_exit and self.config.skip_protective_exits:
            return ValidationResult.accept(skipped=True, reason="protective_exit")

        if snapshot is None and symbol:
            snapshot = self.resolve_snapshot(symbol)

        if action == "ENTRY" and self.config.validate_entry:
            return self.validate_entry(
                intent,
                snapshot=snapshot,
                exec_price=exec_price,
                planned_sl_trigger=planned_sl_trigger,
            )

        if is_stop and self.config.validate_stop:
            return self.validate_stop(
                intent,
                snapshot=snapshot,
                side=side,
            )

        return ValidationResult.accept(skipped=True, reason="no_rule")

    def validate_entry(
        self,
        intent: Any,
        *,
        snapshot: Optional[MarketSnapshot] = None,
        exec_price: Optional[float] = None,
        planned_sl_trigger: Optional[float] = None,
    ) -> ValidationResult:
        cfg = self.config
        side = str(getattr(intent, "side", "") or "").upper()
        inst = getattr(intent, "instrument", None)
        symbol = str(
            getattr(inst, "trading_symbol", None)
            or getattr(intent, "symbol", None)
            or (snapshot.symbol if snapshot else "")
            or ""
        ).strip()

        if snapshot is None and symbol:
            snapshot = self.resolve_snapshot(symbol)

        details: Dict[str, Any] = {
            "symbol": symbol,
            "side": side,
            "action": "ENTRY",
        }
        if snapshot is None:
            if cfg.require_bid_ask or cfg.require_mark:
                return ValidationResult.reject(
                    "missing_market_snapshot",
                    **details,
                )
            return ValidationResult.accept(**details)

        details.update(
            {
                "bid": snapshot.bid,
                "ask": snapshot.ask,
                "mark": snapshot.mark,
                "ltp": snapshot.ltp,
                "source": snapshot.source,
                "quote_ts": snapshot.ts,
            }
        )

        age = self._quote_age_sec(snapshot)
        if age is not None:
            details["quote_age_sec"] = age
            if cfg.max_quote_age_sec > 0 and age > cfg.max_quote_age_sec:
                return ValidationResult.reject("stale_quote", **details)

        bid, ask = snapshot.bid, snapshot.ask
        if cfg.require_bid_ask and (bid is None or ask is None):
            return ValidationResult.reject("missing_bid_ask", **details)

        if bid is not None and ask is not None:
            if ask < bid:
                return ValidationResult.reject("crossed_book", **details)
            mid = (bid + ask) / 2.0
            details["mid"] = mid
            if bid > 0 and cfg.max_spread_pct > 0:
                spread_pct = (ask - bid) / bid
                details["spread_pct"] = spread_pct
                if spread_pct > cfg.max_spread_pct:
                    return ValidationResult.reject("spread_too_wide", **details)

            if cfg.min_book_size > 0:
                if snapshot.bid_size is not None and snapshot.bid_size < cfg.min_book_size:
                    return ValidationResult.reject("insufficient_bid_size", **details)
                if snapshot.ask_size is not None and snapshot.ask_size < cfg.min_book_size:
                    return ValidationResult.reject("insufficient_ask_size", **details)

            mark = snapshot.mark
            if mark is None and cfg.require_mark:
                return ValidationResult.reject("missing_mark", **details)
            if mark is not None and mid > 0 and cfg.max_mark_mid_pct > 0:
                diverg = abs(mark - mid) / mid
                details["mark_mid_pct"] = diverg
                if diverg > cfg.max_mark_mid_pct:
                    return ValidationResult.reject("mark_mid_divergence", **details)
        elif cfg.require_bid_ask:
            return ValidationResult.reject("missing_bid_ask", **details)

        # Planned premium SL vs mark (short option sell → buy-to-cover stop).
        # Skip when strategy uses underlying/spot stops (no premium SL to validate).
        stop_method = _stop_trigger_method(intent)
        details["stop_trigger_method"] = stop_method or None
        non_mark = {
            str(m).strip().lower() for m in (cfg.non_mark_stop_methods or ())
        }
        if stop_method and stop_method in non_mark:
            return ValidationResult.accept(**details)

        entry_px = _pos_float(exec_price) if exec_price is not None else None
        if entry_px is None and bid is not None and ask is not None:
            entry_px = (bid + ask) / 2.0
        if entry_px is None:
            entry_px = _pos_float(getattr(intent, "price", None)) or snapshot.ltp

        sl_trig = planned_sl_trigger
        if sl_trig is None:
            sl_trig = planned_sl_trigger_from_intent(
                intent,
                entry_price=entry_px,
                default_sl_premium_mult=cfg.default_sl_premium_mult,
                infer_from_default_mult=bool(cfg.infer_entry_sl_from_default_mult),
            )
        details["planned_sl_trigger"] = sl_trig
        details["entry_estimate"] = entry_px

        mark = snapshot.mark
        if (
            side == "SELL"
            and sl_trig is not None
            and mark is not None
            and cfg.validate_stop
        ):
            # Buy-to-cover stop already through (or at) mark → do not take the short.
            min_trig = float(mark) * float(cfg.min_stop_mark_ratio or 1.0)
            details["min_valid_sl_trigger"] = min_trig
            if float(sl_trig) <= float(mark) or float(sl_trig) < min_trig:
                return ValidationResult.reject("invalid_stop_vs_mark", **details)

        if side == "BUY" and sl_trig is not None and mark is not None and cfg.validate_stop:
            # Sell-to-cover stop already through mark for a long.
            details["max_valid_sl_trigger"] = float(mark) / float(
                cfg.min_stop_mark_ratio or 1.0
            )
            if float(sl_trig) >= float(mark):
                return ValidationResult.reject("invalid_stop_vs_mark", **details)

        return ValidationResult.accept(**details)

    def validate_stop(
        self,
        intent: Any,
        *,
        snapshot: Optional[MarketSnapshot] = None,
        side: Optional[str] = None,
    ) -> ValidationResult:
        cfg = self.config
        side_u = str(side or getattr(intent, "side", "") or "").upper()
        inst = getattr(intent, "instrument", None)
        symbol = str(
            getattr(inst, "trading_symbol", None)
            or getattr(intent, "symbol", None)
            or (snapshot.symbol if snapshot else "")
            or ""
        ).strip()

        if snapshot is None and symbol:
            snapshot = self.resolve_snapshot(symbol)

        details: Dict[str, Any] = {
            "symbol": symbol,
            "side": side_u,
            "action": "MAIN_SL",
        }
        if snapshot is None:
            if cfg.require_mark:
                return ValidationResult.reject("missing_market_snapshot", **details)
            return ValidationResult.accept(**details)

        details.update(
            {
                "bid": snapshot.bid,
                "ask": snapshot.ask,
                "mark": snapshot.mark,
                "ltp": snapshot.ltp,
                "source": snapshot.source,
            }
        )
        age = self._quote_age_sec(snapshot)
        if age is not None:
            details["quote_age_sec"] = age

        stop_method = _stop_trigger_method(intent)
        details["stop_trigger_method"] = stop_method or None
        non_mark = {
            str(m).strip().lower() for m in (cfg.non_mark_stop_methods or ())
        }
        if stop_method and stop_method in non_mark:
            # Underlying/spot stops are not validated against option mark.
            return ValidationResult.accept(**details)

        mark = snapshot.mark
        if mark is None and cfg.require_mark:
            return ValidationResult.reject("missing_mark", **details)

        trigger = trigger_price_from_intent(intent)
        details["trigger"] = trigger
        if trigger is None:
            return ValidationResult.reject("missing_stop_trigger", **details)

        if mark is None:
            return ValidationResult.accept(**details)

        # Buy-to-cover stop (short option): trigger must be above mark.
        if side_u == "BUY":
            min_trig = float(mark) * float(cfg.min_stop_mark_ratio or 1.0)
            details["min_valid_sl_trigger"] = min_trig
            if float(trigger) <= float(mark) or float(trigger) < min_trig:
                return ValidationResult.reject("invalid_stop_vs_mark", **details)
        # Sell-to-cover stop (long option): trigger must be below mark.
        elif side_u == "SELL":
            max_trig = float(mark) / float(cfg.min_stop_mark_ratio or 1.0)
            details["max_valid_sl_trigger"] = max_trig
            if float(trigger) >= float(mark):
                return ValidationResult.reject("invalid_stop_vs_mark", **details)

        return ValidationResult.accept(**details)

    @staticmethod
    def _quote_age_sec(snapshot: MarketSnapshot) -> Optional[float]:
        if snapshot.ts is None:
            return None
        try:
            return max(0.0, time.time() - float(snapshot.ts))
        except (TypeError, ValueError):
            return None


def config_from_mapping(raw: Optional[Dict[str, Any]]) -> ExecutionValidatorConfig:
    """Build config from engine job ``execution_validator`` dict."""
    cfg = ExecutionValidatorConfig()
    if not isinstance(raw, dict):
        return cfg
    for key in (
        "enabled",
        "venue",
        "max_spread_pct",
        "max_mark_mid_pct",
        "max_quote_age_sec",
        "require_bid_ask",
        "require_mark",
        "validate_entry",
        "validate_stop",
        "min_stop_mark_ratio",
        "default_sl_premium_mult",
        "infer_entry_sl_from_default_mult",
        "min_book_size",
        "skip_protective_exits",
        "non_mark_stop_methods",
    ):
        if key in raw:
            setattr(cfg, key, raw[key])
    if isinstance(cfg.non_mark_stop_methods, (list, tuple, set)):
        cfg.non_mark_stop_methods = tuple(str(x) for x in cfg.non_mark_stop_methods)
    cfg.venue = str(cfg.venue or "DELTA").upper()
    return cfg
