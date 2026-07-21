"""
Reentry-at-cost event adapters (GTT-style).

Domain logic lives in ``core.orderExecution.reentry_at_cost_book``.
This module is the thin Event → book surface when the bus is wired:

  * IntentFilled (MAIN_SL)     → arm watch
  * IntentFilled (MAIN entry)  → stop watch for contract
  * IntentFilled (MAIN_EXIT/TARGET) → cancel structure watch
  * QuoteUpdated               → poll due watches (premium ≤ cost)

Path rule: **hooks XOR bus**. When ``wire_event_bus`` registers these
handlers it sets ``engine._reentry_at_cost_bus_wired = True``; LiveEngine
PM hooks and the direct main-loop ``tick_book`` then no-op. If the bus is
not wired, LiveEngine calls the same helpers from PM hooks / loop tick.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from core.events.context import EngineEventContext
from core.events.types import Event

logger = logging.getLogger(__name__)

# Set on the engine by ``register_reentry_at_cost_handlers`` / cleared when not wired.
_BUS_WIRED_ATTR = "_reentry_at_cost_bus_wired"


def strategy_opts_into_reentry(strategy: Any) -> bool:
    """True when strategy enables OMS same-contract reentry-at-cost."""
    if strategy is None:
        return False
    from core.orderExecution.reentry_at_cost_book import resolve_reentry_policy

    return resolve_reentry_policy(strategy, None) is not None


def reentry_driven_by_bus(engine: Any) -> bool:
    """True when reentry arm/stop/tick must go through bus handlers only."""
    return bool(getattr(engine, _BUS_WIRED_ATTR, False))


def mark_reentry_bus_wired(engine: Any, wired: bool) -> None:
    setattr(engine, _BUS_WIRED_ATTR, bool(wired))


def assert_reentry_path_xor(*, bus_wired: bool, hooks_drive: bool) -> None:
    """Fail if both the bus handlers and PM/loop hooks would drive the book."""
    if bus_wired and hooks_drive:
        raise AssertionError(
            "reentry-at-cost path violation: bus handlers and PM/loop hooks "
            "both driving (expected hooks XOR bus)"
        )


def get_book(engine: Any) -> Any:
    return getattr(getattr(engine, "order_router", None), "reentry_at_cost_book", None)


def resolve_strategy(engine: Any, strategy_name: Any) -> Any:
    name = str(strategy_name or "").strip()
    if not name:
        return None
    fn = getattr(engine, "_strategy_obj_for_name", None)
    if callable(fn):
        return fn(name)
    for s in getattr(engine, "strategies", None) or []:
        if str(getattr(s, "name", "") or "") == name:
            return s
    primary = getattr(engine, "strategy", None)
    if primary is not None and str(getattr(primary, "name", "") or "") == name:
        return primary
    return None


def arm_from_main_sl(
    engine: Any,
    *,
    strategy: Any = None,
    strategy_id: Any = None,
    instrument: Any = None,
    structure_id: Any = None,
    metadata_extras: Any = None,
    qty: Any = None,
    side: Any = None,
    price: Any = None,
    via_bus: bool = False,
    **_kwargs: Any,
) -> bool:
    """Arm a cost-wait after MAIN_SL. Returns True when a watch was armed."""
    if reentry_driven_by_bus(engine) and not via_bus:
        return False
    book = get_book(engine)
    if book is None:
        return False
    sid = str(structure_id or "").strip()
    if not sid:
        return False
    # Idempotent if the same structure_id is already armed.
    try:
        pending = getattr(book, "_watches", None)
        if isinstance(pending, dict) and sid in pending:
            return True
    except Exception:
        pass
    strat = strategy
    if strat is None:
        strat = resolve_strategy(engine, strategy_id)
    if strat is None or instrument is None:
        return False
    try:
        return bool(
            book.maybe_arm_from_main_sl(
                strategy=strat,
                instrument=instrument,
                structure_id=sid,
                metadata_extras=metadata_extras,
                qty=qty,
                side=side,
                price=price,
            )
        )
    except Exception as exc:
        logger.warning("reentry_at_cost arm failed: %s", exc)
        return False


def stop_on_main_opened(
    engine: Any,
    *,
    strategy: Any = None,
    strategy_id: Any = None,
    instrument: Any = None,
    trading_symbol: Any = None,
    via_bus: bool = False,
    **_kwargs: Any,
) -> None:
    """Drop watches once MAIN is open again on the contract."""
    if reentry_driven_by_bus(engine) and not via_bus:
        return
    book = get_book(engine)
    if book is None:
        return
    sid = str(
        strategy_id
        or (getattr(strategy, "name", None) if strategy is not None else None)
        or ""
    )
    try:
        book.on_position_opened(
            instrument=instrument,
            strategy_id=sid or None,
            trading_symbol=trading_symbol,
        )
    except Exception as exc:
        logger.warning("reentry_at_cost on_position_opened failed: %s", exc)


def cancel_for_structure(
    engine: Any, structure_id: Any, *, via_bus: bool = False
) -> None:
    if reentry_driven_by_bus(engine) and not via_bus:
        return
    book = get_book(engine)
    if book is None:
        return
    try:
        book.cancel_for_structure(str(structure_id or ""))
    except Exception:
        pass


def stop_for_flat(
    engine: Any,
    *,
    trading_symbol: Any = None,
    strategy_id: Any = None,
    structure_id: Any = None,
) -> None:
    """Cancel watches when broker confirms flat (manual exit / sync).

    Always allowed: this is not duplicated on the bus (no IntentFilled).
    """
    book = get_book(engine)
    if book is None:
        return
    try:
        book.stop_for_trading_symbol(
            trading_symbol=str(trading_symbol or "").strip() or None,
            strategy_id=str(strategy_id or "").strip() or None,
            structure_id=str(structure_id or "").strip() or None,
        )
    except Exception as exc:
        logger.warning(
            "reentry_at_cost stop_for_trading_symbol failed symbol=%s: %s",
            trading_symbol,
            exc,
        )


def tick_book(engine: Any, *, via_bus: bool = False) -> int:
    """Poll due watches; place when premium ≤ cost. Returns placed count."""
    if reentry_driven_by_bus(engine) and not via_bus:
        return 0
    book = get_book(engine)
    if book is None or not getattr(book, "has_pending", lambda: False)():
        return 0
    try:
        return int(book.tick() or 0)
    except Exception as exc:
        logger.warning("reentry_at_cost tick failed: %s", exc)
        return 0


def _instrument_from_payload(payload: dict, engine: Any) -> Any:
    inst = payload.get("instrument")
    if inst is not None:
        return inst
    sym = str(payload.get("symbol") or "").strip()
    if not sym:
        return None
    store = getattr(engine, "instrument_store", None) or getattr(
        getattr(engine, "order_router", None), "instrument_store", None
    )
    if store is None:
        return None
    get_fn = getattr(store, "get", None) or getattr(store, "get_by_trading_symbol", None)
    if not callable(get_fn):
        return None
    try:
        return get_fn(sym)
    except Exception:
        try:
            return get_fn(trading_symbol=sym)
        except Exception:
            return None


def _metadata_from_payload(payload: dict, engine: Any) -> Any:
    meta = payload.get("metadata_extras")
    if meta is not None:
        return meta
    intent_id = payload.get("intent_id")
    router = getattr(engine, "order_router", None)
    store = getattr(router, "intent_store", None) if router is not None else None
    if not intent_id or store is None:
        return None
    try:
        rec = store.get(str(intent_id)) or {}
    except Exception:
        return None
    return (rec.get("payload") or {}).get("strategy_meta")


class ReentryAtCostFillHandler:
    """IntentFilled → arm / stop reentry-at-cost watches."""

    def __init__(self, ctx: EngineEventContext) -> None:
        self._ctx = ctx

    def __call__(self, event: Event) -> None:
        engine = self._ctx.engine
        if get_book(engine) is None:
            return
        payload = event.payload or {}
        tag_u = str(payload.get("tag") or "").upper()
        action_u = str(payload.get("action") or "").upper()
        strategy_id = payload.get("strategy")
        structure_id = payload.get("structure_id")

        if tag_u == "MAIN_SL":
            instrument = _instrument_from_payload(payload, engine)
            arm_from_main_sl(
                engine,
                strategy_id=strategy_id,
                instrument=instrument,
                structure_id=structure_id,
                metadata_extras=_metadata_from_payload(payload, engine),
                qty=payload.get("qty"),
                side=payload.get("side"),
                price=payload.get("price"),
                via_bus=True,
            )
            return

        if tag_u in ("MAIN_EXIT", "MAIN_TARGET"):
            cancel_for_structure(engine, structure_id, via_bus=True)
            return

        # MAIN ENTRY fill (or ENTRY action on MAIN) → stop cost wait for contract.
        if tag_u == "MAIN" or action_u == "ENTRY":
            stop_on_main_opened(
                engine,
                strategy_id=strategy_id,
                instrument=_instrument_from_payload(payload, engine),
                trading_symbol=payload.get("symbol"),
                via_bus=True,
            )


class ReentryAtCostQuoteHandler:
    """QuoteUpdated → poll premium-to-cost watches (same cadence gate as book.tick)."""

    def __init__(self, ctx: EngineEventContext) -> None:
        self._ctx = ctx

    def __call__(self, event: Event) -> None:
        tick_book(self._ctx.engine, via_bus=True)


def register_reentry_at_cost_handlers(ctx: EngineEventContext) -> None:
    from core.events.types import EventType

    book = get_book(ctx.engine)
    if book is None:
        mark_reentry_bus_wired(ctx.engine, False)
        return

    ctx.bus.subscribe(
        EventType.INTENT_FILLED,
        ReentryAtCostFillHandler(ctx),
        priority=50,
        name="reentry_at_cost_fill",
    )
    ctx.bus.subscribe(
        EventType.QUOTE_UPDATED,
        ReentryAtCostQuoteHandler(ctx),
        priority=45,
        name="reentry_at_cost_quote_tick",
    )
    mark_reentry_bus_wired(ctx.engine, True)
    assert_reentry_path_xor(bus_wired=True, hooks_drive=False)
