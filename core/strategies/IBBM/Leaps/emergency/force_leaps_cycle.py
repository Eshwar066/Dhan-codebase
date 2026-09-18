"""
One-shot: close open LEAPS_RSI structure and place a fresh ENTRY (hedge + main).

Supports dual MAIN legs when strategy.yaml has both mini_leaps and quarterly_leaps
enabled — places one hedge-gated bundle per structure_id (mini + :QTR).

Manual emergency tool only — not imported by live engine / strategy registry.

Usage (stop dhan-leaps-rsi.service first):
  python -m core.strategies.IBBM.Leaps.emergency.force_leaps_cycle
  python -m core.strategies.IBBM.Leaps.emergency.force_leaps_cycle --entry-only

  --entry-only   Skip close cycle; place entry bundles for all enabled legs.
                 Useful after hours: LIMIT orders rest until market open.
"""

from __future__ import annotations

import logging
import sys
import time
import uuid
from datetime import datetime
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

load_dotenv()

import pandas as pd

from run.config import ENGINE_JOBS, RUN_MODE, RunMode
from run.engine_config import configure_process_logging
from run.main import job_to_engine_config
from run.strategy_profiles import resolve_engine_job
from core.engine.factory import EngineFactory
from core.models.order_intent import OrderIntent
from core.orderExecution.intent_store import IntentStatus
from core.orderExecution.order_router import OrderState
from core.utils.price_tick import resolve_tick_size, round_by_tick_size

IST = ZoneInfo("Asia/Kolkata")
LEAPS_STRATEGY_ID = "LEAPS_RSI"
logger = logging.getLogger("leaps.emergency.force_leaps_cycle")


def _resolve_leaps_engine_job():
    """Resolve ENGINE_JOBS entry that runs LEAPS_RSI (legacy dhan_leaps_rsi or combined dhan)."""
    for engine_id in ("dhan_leaps_rsi", "dhan"):
        for j in ENGINE_JOBS:
            if j.get("engine_id") != engine_id:
                continue
            strategies = list(j.get("strategies") or [])
            if engine_id == "dhan_leaps_rsi" or LEAPS_STRATEGY_ID in strategies:
                return resolve_engine_job(j)
    return None


def _leaps_strategy(engine: Any) -> Any:
    obj = getattr(engine, "_strategy_obj_for_name", None)
    if callable(obj):
        found = obj(LEAPS_STRATEGY_ID)
        if found is not None:
            return found
    if getattr(getattr(engine, "strategy", None), "name", None) == LEAPS_STRATEGY_ID:
        return engine.strategy
    raise RuntimeError(f"{LEAPS_STRATEGY_ID} strategy not loaded on engine")


def _price_map_for_intent(intent: Any, price: float) -> Dict[str, float]:
    p = float(price)
    out: Dict[str, float] = {}
    inst = getattr(intent, "instrument", None)
    if inst is not None:
        if hasattr(inst, "place_order_symbol"):
            try:
                pos = inst.place_order_symbol()
            except Exception:
                pos = None
            if pos:
                out[str(pos)] = p
        ts = getattr(inst, "trading_symbol", None)
        if ts:
            out[str(ts)] = p
        custom = getattr(inst, "custom_symbol", None)
        if custom:
            out[str(custom)] = p
    return out


def _resolve_exit_price(engine: Any, intent: Any) -> Optional[float]:
    trading_sym = engine._intent_place_order_symbol(intent, "")
    side = str(getattr(intent, "side", "") or "").upper()
    is_sell = side == "SELL"
    price = (
        engine._exit_price_from_depth(trading_sym, is_sell)
        or engine.get_price_map(trading_sym)
        or engine._positive_price(getattr(intent, "price", None))
    )
    if price is None:
        return None
    tick = engine._get_tick_size(trading_sym)
    mode = "floor" if is_sell else "ceil"
    rounded = round_by_tick_size(float(price), tick, floor_or_ceil=mode)
    return float(rounded if rounded is not None else price)


def _resolve_entry_price(engine: Any, intent: Any) -> Optional[float]:
    trading_sym = engine._intent_place_order_symbol(intent, "")
    side = str(getattr(intent, "side", "") or "").upper()
    is_buy = side == "BUY"
    price = (
        engine._entry_price_from_depth(trading_sym, is_buy)
        or engine.get_price_map(trading_sym)
        or engine._positive_price(getattr(intent, "price", None))
    )
    if price is None or float(price) <= 0:
        return None
    tick = resolve_tick_size(
        trading_sym, engine.instrument_store, instrument=getattr(intent, "instrument", None)
    )
    mode = "ceil" if is_buy else "floor"
    rounded = round_by_tick_size(float(price), tick, floor_or_ceil=mode)
    return float(rounded if rounded is not None else price)


def _place(engine: Any, intent: Any, price: float, label: str) -> bool:
    pm = _price_map_for_intent(intent, price)
    try:
        intent.price = float(price)
    except Exception:
        pass
    logger.info(
        "Placing %s %s %s qty=%s @ %s keys=%s",
        label,
        getattr(intent, "side", ""),
        engine._intent_place_order_symbol(intent, ""),
        getattr(intent, "qty", None),
        price,
        list(pm.keys()),
    )
    result = engine.order_router.process_intent(intent, pm)
    ok = isinstance(result, dict) and result.get("ok")
    logger.info("Result %s: %s", label, result)
    return bool(ok)


def _wait_fills(engine: Any, intent_ids: List[str], timeout_sec: float = 90.0) -> bool:
    deadline = time.time() + timeout_sec
    pending = set(intent_ids)
    while pending and time.time() < deadline:
        try:
            engine.order_router.sync_trades_from_broker()
        except Exception as exc:
            logger.warning("sync_trades_from_broker: %s", exc)
        try:
            engine.order_router.verify_open_orders_with_broker()
        except Exception as exc:
            logger.warning("verify_open_orders: %s", exc)
        done = []
        for iid in list(pending):
            rec = engine.order_router.intent_store.get(iid)
            st = rec.get("status") if rec else None
            ost = engine.order_router._order_state.get(iid)
            if st == IntentStatus.FILLED or ost == OrderState.FILLED:
                done.append(iid)
                logger.info("FILLED %s", iid)
        for iid in done:
            pending.discard(iid)
        if pending:
            time.sleep(2.0)
    if pending:
        logger.error("Timed out waiting for fills: %s", sorted(pending))
        return False
    return True


def _synthetic_candle(engine: Any, symbol: str = "NIFTY") -> Dict[str, Any]:
    """Build a closed-looking candle with RSI that drives LEAPS entry from live spot."""
    now_ist = datetime.now(IST)
    # Align to last completed NSE hourly open (09:15, 10:15, ...)
    minute = 15 if now_ist.minute >= 15 else 15
    hour = now_ist.hour if now_ist.minute >= 15 else max(9, now_ist.hour - 1)
    if now_ist.hour < 9 or (now_ist.hour == 9 and now_ist.minute < 15):
        hour, minute = 9, 15
    bar_open_ist = now_ist.replace(hour=hour, minute=minute, second=0, microsecond=0)
    # Candle timestamp stored as naive UTC in engine paths for scheduled/live
    bar_open_utc = bar_open_ist.astimezone(ZoneInfo("UTC")).replace(tzinfo=None)

    spot = engine.get_price_map(symbol) or 0.0
    # Fetch recent candles for RSI if possible
    rsi = None
    prev_rsi = None
    try:
        candles = engine.data.get_latest_candles([symbol])
        row = (candles or {}).get(symbol) or {}
        rsi = row.get("rsi")
        prev_rsi = row.get("prev_rsi")
        if spot <= 0 and row.get("close"):
            spot = float(row["close"])
    except Exception as exc:
        logger.warning("Could not load RSI candles: %s", exc)

    # Force a clear entry regime: if RSI unknown, use PUT regime (matches ~53 from log).
    if rsi is None or prev_rsi is None:
        rsi, prev_rsi = 55.0, 50.0
    else:
        rsi = float(rsi)
        prev_rsi = float(prev_rsi)
        # Nudge across threshold so on_candle / should_evaluate paths are unambiguous
        if rsi >= 42:
            rsi, prev_rsi = max(rsi, 53.0), min(prev_rsi, 50.0)
        else:
            rsi, prev_rsi = min(rsi, 30.0), max(prev_rsi, 35.0)

    return {
        "symbol": symbol,
        "timestamp": bar_open_utc,
        "open": float(spot),
        "high": float(spot),
        "low": float(spot),
        "close": float(spot),
        "volume": 0,
        "rsi": float(rsi),
        "prev_rsi": float(prev_rsi),
        "timeframe": "60",
        "bucket_ts": int(bar_open_ist.timestamp()),
    }


def _force_close(engine: Any, strategy: Any) -> List[str]:
    symbol = "NIFTY"
    candle = _synthetic_candle(engine, symbol)
    # Force exit condition regardless of RSI
    candle["rsi"] = 60.0
    candle["prev_rsi"] = 50.0
    ctx = engine.build_context_only(candle)
    open_pos = engine.position_manager.get_open_positions(
        underlying=symbol, strategy=strategy.name
    ) or []
    mains = [
        p
        for p in open_pos
        if str(getattr(p, "tag", "") or "").upper() == "MAIN"
        and int(getattr(p, "net_qty", 0) or 0) != 0
    ]
    if not mains:
        # Fallback: any non-zero LEAPS leg treated as close targets
        logger.warning("No MAIN tagged positions; closing all open LEAPS legs directly")
        placed: List[str] = []
        for pos in open_pos:
            nq = int(getattr(pos, "net_qty", 0) or 0)
            if nq == 0:
                continue
            inst = getattr(pos, "instrument", None)
            if inst is None:
                continue
            side = "BUY" if nq < 0 else "SELL"
            lot = int(getattr(inst, "lot_size", 65) or 65)
            qty_lots = max(1, abs(nq) // lot)
            intent = OrderIntent(
                intent_id=uuid.uuid4().hex,
                instrument=inst,
                side=side,
                qty=qty_lots,
                price=None,
                order_type="LIMIT",
                strategy=strategy.name,
                structure_id=str(getattr(pos, "structure_id", "") or "FORCE"),
                trade_type="MARGIN",
                tag="FORCE_EXIT",
                symbol=symbol,
                action="EXIT",
                candle_ts=candle["timestamp"],
            )
            px = _resolve_exit_price(engine, intent)
            if px is None:
                raise RuntimeError(f"No exit price for {inst.trading_symbol}")
            if not _place(engine, intent, px, "FORCE_EXIT"):
                raise RuntimeError(f"Failed to place exit for {inst.trading_symbol}")
            placed.append(intent.intent_id)
        return placed

    placed_ids: List[str] = []
    for main in mains:
        # Bypass should_exit — call on_position_exit directly
        intents = strategy.on_position_exit(main, candle, ctx) or []
        for intent in intents:
            px = _resolve_exit_price(engine, intent)
            if px is None:
                raise RuntimeError(
                    f"No exit price for {engine._intent_place_order_symbol(intent, '')}"
                )
            if not _place(engine, intent, px, str(getattr(intent, "tag", "EXIT"))):
                raise RuntimeError(f"Exit place failed for {intent.intent_id}")
            placed_ids.append(intent.intent_id)
    return placed_ids


def _order_bundle_legs(intents: List[Any]) -> List[Any]:
    """HEDGE before MAIN within one structure bundle."""
    hedges = [i for i in intents if str(getattr(i, "tag", "")).upper() == "HEDGE"]
    mains = [i for i in intents if str(getattr(i, "tag", "")).upper() == "MAIN"]
    others = [
        i
        for i in intents
        if str(getattr(i, "tag", "")).upper() not in ("HEDGE", "MAIN")
    ]
    return hedges + mains + others


def _group_entry_intents_by_structure(intents: List[Any]) -> Dict[str, List[Any]]:
    bundles: Dict[str, List[Any]] = {}
    for intent in intents:
        stid = str(getattr(intent, "structure_id", "") or "").strip()
        if not stid:
            stid = "FORCE_ENTRY"
        bundles.setdefault(stid, []).append(intent)
    return bundles


def _place_entry_bundle(
    engine: Any,
    strategy: Any,
    structure_id: str,
    intents: List[Any],
) -> Tuple[List[str], Dict[str, Any]]:
    ordered = _order_bundle_legs(intents)
    price_map: Dict[str, float] = {}
    for intent in ordered:
        px = _resolve_entry_price(engine, intent)
        if px is None or px <= 0:
            px = engine._positive_price(getattr(intent, "price", None))
        if px is None or px <= 0:
            raise RuntimeError(
                f"No entry price for {engine._intent_place_order_symbol(intent, '')} "
                f"structure={structure_id}"
            )
        try:
            intent.price = float(px)
        except Exception:
            pass
        price_map.update(_price_map_for_intent(intent, float(px)))

    bundle_item = {
        "intent_bundle": ordered,
        "price_map": price_map,
        "structure_id": structure_id,
        "strategy_id": strategy.name,
        "engine_id": getattr(engine, "engine_id", None),
        "idempotency_key": f"force_leaps|{structure_id}|{uuid.uuid4().hex[:8]}",
    }
    logger.info(
        "Placing hedge-gated ENTRY bundle structure=%s legs=%s",
        structure_id,
        [
            (getattr(i, "tag", None), engine._intent_place_order_symbol(i, ""))
            for i in ordered
        ],
    )
    result = engine.order_router.process_intent_bundle(bundle_item)
    logger.info("Bundle result structure=%s: %s", structure_id, result)
    if not isinstance(result, dict) or not result.get("ok"):
        raise RuntimeError(f"Entry bundle failed structure={structure_id}: {result}")
    intent_ids = [
        str(getattr(i, "intent_id", ""))
        for i in ordered
        if getattr(i, "intent_id", None)
    ]
    return intent_ids, result


def _force_entry(engine: Any, strategy: Any) -> List[str]:
    symbol = "NIFTY"
    candle = _synthetic_candle(engine, symbol)
    candle["exchange"] = "INDEX"
    # Clear one-shot guards so forced entry is allowed
    for attr in ("_entry_signaled_keys", "_evaluated_signal_keys"):
        bag = getattr(strategy, attr, None)
        if isinstance(bag, set):
            bag.clear()

    ctx = engine.build_context_only(candle)
    ctx.exchange = "INDEX"

    intents = strategy.on_candle(candle, ctx)
    if not intents:
        # If RSI mid-band somehow, force PUT regime
        candle["rsi"], candle["prev_rsi"] = 55.0, 50.0
        for attr in ("_entry_signaled_keys", "_evaluated_signal_keys"):
            bag = getattr(strategy, attr, None)
            if isinstance(bag, set):
                bag.clear()
        intents = strategy.on_candle(candle, ctx)
    if not intents:
        raise RuntimeError("strategy.on_candle returned no entry intents")
    if not isinstance(intents, list):
        intents = [intents]

    logger.info(
        "on_candle produced %s intent(s) across %s structure(s): %s",
        len(intents),
        len(_group_entry_intents_by_structure(intents)),
        [
            (
                getattr(i, "structure_id", None),
                getattr(i, "tag", None),
                engine._intent_place_order_symbol(i, ""),
            )
            for i in intents
        ],
    )

    placed_ids: List[str] = []
    for structure_id, group in _group_entry_intents_by_structure(intents).items():
        ids, _ = _place_entry_bundle(engine, strategy, structure_id, group)
        placed_ids.extend(ids)
    if not placed_ids:
        raise RuntimeError("No entry intents placed")
    return placed_ids


def _force_main_exit_only(engine: Any, strategy: Any) -> List[str]:
    """Close MAIN leg(s) only — keep HEDGE open."""
    symbol = "NIFTY"
    candle = _synthetic_candle(engine, symbol)
    ctx = engine.build_context_only(candle)
    open_pos = engine.position_manager.get_open_positions(
        underlying=symbol, strategy=strategy.name
    ) or []
    mains = [
        p
        for p in open_pos
        if str(getattr(p, "tag", "") or "").upper() == "MAIN"
        and int(getattr(p, "net_qty", 0) or 0) != 0
    ]
    if not mains:
        logger.warning("No open MAIN to exit")
        return []

    placed_ids: List[str] = []
    for main in mains:
        intents = strategy.on_position_exit(main, candle, ctx) or []
        for intent in intents:
            if str(getattr(intent, "tag", "") or "").upper() != "MAIN_EXIT":
                logger.info(
                    "Skipping %s during MAIN-only exit (hedge preserved)",
                    getattr(intent, "tag", None),
                )
                continue
            px = _resolve_exit_price(engine, intent)
            if px is None:
                raise RuntimeError(
                    f"No exit price for {engine._intent_place_order_symbol(intent, '')}"
                )
            if not _place(engine, intent, px, "MAIN_EXIT"):
                raise RuntimeError(f"MAIN exit place failed for {intent.intent_id}")
            placed_ids.append(intent.intent_id)
    return placed_ids


def _open_main_positions(engine: Any, strategy: Any) -> List[Any]:
    return [
        p
        for p in (
            engine.position_manager.get_open_positions(
                underlying="NIFTY", strategy=strategy.name
            )
            or []
        )
        if str(getattr(p, "tag", "") or "").upper() == "MAIN"
        and int(getattr(p, "net_qty", 0) or 0) != 0
    ]


def _force_main_entry_only(
    engine: Any, strategy: Any, *, max_attempts: int = 4
) -> List[str]:
    """Place quarterly MAIN ENTRY only (HEDGE already open)."""
    from core.utils.expiry_resolver import ExpiryResolver
    from core.utils.option_chain_snapshot_log import load_option_chain_snapshot

    symbol = "NIFTY"
    last_err = "could not build MAIN intent"
    for attempt in range(1, max_attempts + 1):
        strategy._last_option_chain = None
        strategy._snapshot_expiry_pref = "QUARTERLY"
        strategy._leaps_snapshot_logged_slots = set()
        strategy._leaps_hedge_snapshot_logged_slots = set()
        for attr in ("_entry_signaled_keys", "_evaluated_signal_keys"):
            bag = getattr(strategy, attr, None)
            if isinstance(bag, set):
                bag.clear()

        candle = _synthetic_candle(engine, symbol)
        candle["exchange"] = "INDEX"
        ctx = engine.build_context_only(candle)
        ctx.exchange = "INDEX"

        rsi = float(candle.get("rsi") or 55.0)
        if rsi < 32:
            option_type, regime = "CALL", "RSI_LT_32"
        else:
            option_type, regime = "PUT", "RSI_GT_52"
        structure_id = f"{strategy.build_structure_id(candle, regime)}:QTR"
        trade_date = pd.Timestamp(candle["timestamp"]).date()
        want_exp = ExpiryResolver.quarterly_target_expiry_date(trade_date)

        # Warm QUARTERLY chain; fall back to on-disk Dec snapshot if Dhan snaps weekly.
        try:
            strategy.fetch_option_chain(candle, ctx, option_type, expiry_pref="QUARTERLY")
        except Exception as exc:
            logger.warning("fetch_option_chain QUARTERLY: %s", exc)
        chain_exp = strategy._expiry_from_option_chain()
        if chain_exp != want_exp:
            snap_date = datetime.now(IST).strftime("%Y-%m-%d")
            seeded = None
            for snap_time in ("14-15", "13-15", "12-15", "11-15", "10-15", "09-45", "08-45"):
                seeded = load_option_chain_snapshot(
                    snapshot_date=snap_date,
                    snapshot_time=snap_time,
                    snapshot_target="leaps_rsi_quarterly",
                    ctx_symbol=symbol,
                    ctx_exchange=str(ctx.exchange or "INDEX"),
                )
                if seeded and ExpiryResolver.as_calendar_date(seeded.get("expiry")) == want_exp:
                    strategy._last_option_chain = seeded
                    chain_exp = want_exp
                    logger.info(
                        "Seeded QUARTERLY chain from snapshot %s %s expiry=%s",
                        snap_date,
                        snap_time,
                        want_exp,
                    )
                    break
            if chain_exp != want_exp:
                last_err = f"chain expiry={chain_exp} != want={want_exp}"
                logger.warning("MAIN entry attempt %s/%s: %s", attempt, max_attempts, last_err)
                time.sleep(3)
                continue

        ctx.selected_expiry = want_exp
        orig_can_reuse = strategy._can_reuse_cached_option_chain
        orig_snap_params = strategy._find_strike_snapshot_params

        def _reuse_seeded_chain(ctx_obj, expiry_pref=None):
            if str(expiry_pref or "").upper() == "QUARTERLY":
                cached_exp = strategy._expiry_from_option_chain()
                if cached_exp == want_exp:
                    return True
            return orig_can_reuse(ctx_obj, expiry_pref)

        strategy._can_reuse_cached_option_chain = _reuse_seeded_chain
        strategy._find_strike_snapshot_params = lambda *args, **kwargs: {}
        intent_store = getattr(ctx, "intent_store", None)
        orig_has_entry = orig_has_pending = None
        if intent_store is not None:
            orig_has_entry = intent_store.has_entry_for_structure
            orig_has_pending = intent_store.has_pending_intent
            intent_store.has_entry_for_structure = lambda *a, **k: False
            intent_store.has_pending_intent = lambda *a, **k: False
        try:
            legs = strategy._build_entry_intents(
                candle,
                ctx,
                option_type,
                structure_id=structure_id,
                expiry_pref="QUARTERLY",
                leg_label="quarterly",
            )
        finally:
            strategy._can_reuse_cached_option_chain = orig_can_reuse
            strategy._find_strike_snapshot_params = orig_snap_params
            if intent_store is not None and orig_has_entry is not None:
                intent_store.has_entry_for_structure = orig_has_entry
                intent_store.has_pending_intent = orig_has_pending
        if not legs:
            last_err = "_build_entry_intents returned nothing"
            logger.warning("MAIN entry attempt %s/%s: %s", attempt, max_attempts, last_err)
            time.sleep(3)
            continue

        mains = [i for i in legs if str(getattr(i, "tag", "") or "").upper() == "MAIN"]
        if not mains:
            last_err = "no MAIN leg in built intents"
            logger.warning("MAIN entry attempt %s/%s: %s", attempt, max_attempts, last_err)
            time.sleep(3)
            continue

        main = mains[0]
        sym = engine._intent_place_order_symbol(main, "")
        exp = getattr(getattr(main, "instrument", None), "expiry", None)
        logger.info(
            "MAIN entry attempt %s/%s: %s expiry=%s structure=%s",
            attempt,
            max_attempts,
            sym,
            exp,
            getattr(main, "structure_id", None),
        )
        if exp and ExpiryResolver.as_calendar_date(exp) != want_exp:
            last_err = f"built MAIN expiry {exp} != want {want_exp}"
            logger.warning("MAIN entry attempt %s/%s: %s", attempt, max_attempts, last_err)
            time.sleep(3)
            continue

        px = _resolve_entry_price(engine, main)
        if px is None or px <= 0:
            last_err = f"no entry price for {sym}"
            logger.warning("MAIN entry attempt %s/%s: %s", attempt, max_attempts, last_err)
            time.sleep(3)
            continue
        if not _place(engine, main, px, "MAIN"):
            raise RuntimeError(f"MAIN entry place failed for {sym}")
        return [main.intent_id]
    raise RuntimeError(f"Could not place Dec quarterly MAIN: {last_err}")


def _main_reroll(engine: Any, strategy: Any) -> int:
    open_pos = engine.position_manager.get_open_positions(
        underlying="NIFTY", strategy=LEAPS_STRATEGY_ID
    ) or []
    logger.info(
        "Open before MAIN reroll: %s",
        [
            (
                getattr(getattr(p, "instrument", None), "trading_symbol", None),
                getattr(p, "tag", None),
                getattr(p, "net_qty", None),
            )
            for p in open_pos
        ],
    )
    mains = _open_main_positions(engine, strategy)
    if not mains:
        logger.info("No MAIN open — proceeding to MAIN entry only")
    else:
        exit_ids = _force_main_exit_only(engine, strategy)
        if exit_ids:
            logger.info("Waiting for MAIN exit fills…")
            if not _wait_fills(engine, exit_ids, timeout_sec=120):
                return 1
        broker = engine.order_router.broker
        if hasattr(broker, "get_positions_for_recon"):
            engine.position_manager.reconcile_with_broker(
                broker.get_positions_for_recon(), strategy=LEAPS_STRATEGY_ID
            )
        if _open_main_positions(engine, strategy):
            logger.error("MAIN still open after exit — aborting entry")
            return 1

    logger.info("Placing Dec quarterly MAIN (hedge unchanged)…")
    entry_ids = _force_main_entry_only(engine, strategy)
    logger.info("Waiting for MAIN entry fill…")
    ok_fills = _wait_fills(engine, entry_ids, timeout_sec=120)
    if not ok_fills:
        logger.warning("MAIN entry fill not confirmed; updating CSV anyway")
    _write_open_positions_csv(engine)
    logger.info("MAIN reroll complete")
    return 0


def _synthetic_parent_from_main(main: Any, strategy: Any, candle: dict) -> OrderIntent:
    """Minimal parent SELL intent so create_hedge_intent can derive hedge strike/expiry."""
    inst = getattr(main, "instrument", None)
    if inst is None:
        raise RuntimeError("MAIN position has no instrument")
    iid = str(getattr(main, "intent_id", "") or "").strip() or uuid.uuid4().hex
    return OrderIntent(
        intent_id=iid,
        instrument=inst,
        side="SELL",
        qty=1,
        price=float(getattr(main, "avg_price", 0) or 0),
        order_type="LIMIT",
        strategy=strategy.name,
        structure_id=str(getattr(main, "structure_id", "") or ""),
        trade_type="MARGIN",
        tag="MAIN",
        symbol=str(candle.get("symbol") or "NIFTY"),
        action="ENTRY",
        candle_ts=candle["timestamp"],
    )


def _orphan_long_hedge_from_broker(engine: Any, main: Any) -> Optional[Tuple[str, dict]]:
    """Find untagged long option on broker matching MAIN option type (orphan hedge)."""
    broker = getattr(getattr(engine, "order_router", None), "broker", None)
    if broker is None or not hasattr(broker, "get_positions_for_recon"):
        return None
    main_inst = getattr(main, "instrument", None)
    main_opt = str(getattr(main_inst, "option_type", "") or "").upper()
    want_pe = main_opt in ("PE", "PUT")
    want_ce = main_opt in ("CE", "CALL")
    try:
        bp = broker.get_positions_for_recon() or {}
    except Exception:
        return None
    candidates: List[Tuple[str, dict]] = []
    for sym, row in bp.items():
        qty = int((row or {}).get("qty") or 0)
        if qty <= 0:
            continue
        su = str(sym or "").upper()
        if want_pe and "PE" not in su:
            continue
        if want_ce and "CE" not in su:
            continue
        if want_pe and "CE" in su and "PE" not in su.replace("CE", ""):
            continue
        candidates.append((str(sym), row))
    if not candidates:
        return None
    # Prefer same structure_id symbol from CSV meta if present; else nearest expiry long.
    candidates.sort(key=lambda x: x[0])
    return candidates[0]


def _manual_hedge_exit_intent(
    engine: Any,
    strategy: Any,
    main: Any,
    candle: dict,
    *,
    trading_symbol: str,
    net_qty: int,
) -> Optional[OrderIntent]:
    from core.orderExecution.position_manager import PositionManager

    opt, strike = PositionManager._extract_option_hint(trading_symbol, None)
    inst = engine.instrument_store.intent_creation_details(
        trading_symbol,
        str(candle.get("exchange") or "INDEX"),
        None,
        opt,
        strike,
        prefer_monthly=True,
    )
    if inst is None:
        return None
    lot = int(getattr(inst, "lot_size", 65) or 65)
    qty_lots = max(1, abs(int(net_qty)) // lot)
    return OrderIntent(
        intent_id=uuid.uuid4().hex,
        instrument=inst,
        side="SELL",
        qty=qty_lots,
        price=None,
        order_type="LIMIT",
        strategy=strategy.name,
        structure_id=str(getattr(main, "structure_id", "") or ""),
        trade_type="MARGIN",
        tag="HEDGE_EXIT",
        symbol=str(candle.get("symbol") or "NIFTY"),
        action="EXIT",
        candle_ts=candle["timestamp"],
    )


def _find_hedge_for_main(
    engine: Any, ctx: Any, main: Any, open_pos: List[Any]
) -> Optional[Any]:
    hedge = ctx.position_store.get_hedge_for(main)
    if hedge is not None and int(getattr(hedge, "net_qty", 0) or 0) != 0:
        return hedge
    sid = str(getattr(main, "structure_id", "") or "")
    for pos in open_pos:
        if str(getattr(pos, "tag", "") or "").upper() != "HEDGE":
            continue
        if sid and str(getattr(pos, "structure_id", "") or "") != sid:
            continue
        if int(getattr(pos, "net_qty", 0) or 0) != 0:
            return pos
    orphan = _orphan_long_hedge_from_broker(engine, main)
    if orphan is None:
        return None
    sym, row = orphan
    logger.warning(
        "Using orphan broker hedge %s qty=%s (not tagged in PM)",
        sym,
        (row or {}).get("qty"),
    )
    return SimpleNamespace(
        instrument=getattr(main, "instrument", None),
        net_qty=int((row or {}).get("qty") or 0),
        trading_symbol=sym,
        _orphan_broker=True,
        _orphan_row=row,
    )


def _hedge_strike_reroll(engine: Any, strategy: Any) -> int:
    """Replace mis-struck hedge with 500-grid OTM leg; buy new hedge before exiting old."""
    symbol = "NIFTY"
    candle = _synthetic_candle(engine, symbol)
    candle["exchange"] = "INDEX"
    ctx = engine.build_context_only(candle)
    ctx.exchange = "INDEX"

    open_pos = engine.position_manager.get_open_positions(
        underlying=symbol, strategy=LEAPS_STRATEGY_ID
    ) or []
    logger.info(
        "Open before hedge strike reroll: %s",
        [
            (
                getattr(getattr(p, "instrument", None), "trading_symbol", None),
                getattr(getattr(p, "instrument", None), "strike", None),
                getattr(p, "tag", None),
                getattr(p, "net_qty", None),
            )
            for p in open_pos
        ],
    )

    mains = _open_main_positions(engine, strategy)
    if not mains:
        logger.error("No open MAIN — cannot reroll hedge")
        return 1

    placed_any = False
    for main in mains:
        hedge = _find_hedge_for_main(engine, ctx, main, open_pos)
        if hedge is None or int(getattr(hedge, "net_qty", 0) or 0) == 0:
            logger.error(
                "No hedge for structure=%s — skip",
                getattr(main, "structure_id", None),
            )
            return 1

        main_inst = getattr(main, "instrument", None)
        hedge_inst = getattr(hedge, "instrument", None)
        if getattr(hedge, "_orphan_broker", False):
            sym = str(getattr(hedge, "trading_symbol", "") or "")
            from core.orderExecution.position_manager import PositionManager

            opt, strike = PositionManager._extract_option_hint(sym, None)
            hedge_inst = engine.instrument_store.intent_creation_details(
                sym,
                str(candle.get("exchange") or "INDEX"),
                None,
                opt,
                strike,
                prefer_monthly=True,
            )
        want_strike = strategy.calculate_hedge_strike(
            getattr(main_inst, "strike", 0),
            getattr(main_inst, "option_type", ""),
        )
        have_strike = int(getattr(hedge_inst, "strike", 0) or 0)
        sid = str(getattr(main, "structure_id", "") or "")
        if have_strike == int(want_strike):
            logger.info(
                "structure=%s hedge strike already correct (%s) — skip",
                sid,
                want_strike,
            )
            continue

        logger.info(
            "structure=%s hedge strike fix: MAIN=%s hedge %s→%s",
            sid,
            getattr(main_inst, "strike", None),
            have_strike,
            want_strike,
        )

        parent = _synthetic_parent_from_main(main, strategy, candle)
        new_hedge = strategy.create_hedge_intent(parent, candle, ctx)
        if new_hedge is None:
            logger.error("structure=%s could not build new hedge intent", sid)
            return 1
        if getattr(hedge, "_orphan_broker", False):
            hedge_exit = _manual_hedge_exit_intent(
                engine,
                strategy,
                main,
                candle,
                trading_symbol=str(getattr(hedge, "trading_symbol", "") or ""),
                net_qty=int(getattr(hedge, "net_qty", 0) or 0),
            )
        else:
            hedge_exit = strategy.create_hedge_exit_intent(main, candle, ctx)
        if hedge_exit is None:
            logger.error("structure=%s could not build hedge exit intent", sid)
            return 1

        buy_px = _resolve_entry_price(engine, new_hedge)
        if buy_px is None:
            logger.error("No entry price for new hedge structure=%s", sid)
            return 1
        if not _place(engine, new_hedge, buy_px, "HEDGE_STRIKE_BUY"):
            return 1
        placed_any = True
        buy_id = str(getattr(new_hedge, "intent_id", "") or "")
        if buy_id:
            logger.info("Waiting for new hedge fill…")
            if not _wait_fills(engine, [buy_id], timeout_sec=120):
                logger.error("New hedge not filled — NOT exiting old hedge (margin-safe)")
                return 1

        exit_px = _resolve_exit_price(engine, hedge_exit)
        if exit_px is None:
            logger.error("No exit price for old hedge structure=%s", sid)
            return 1
        if not _place(engine, hedge_exit, exit_px, "HEDGE_EXIT"):
            return 1
        exit_id = str(getattr(hedge_exit, "intent_id", "") or "")
        if exit_id:
            logger.info("Waiting for old hedge exit fill…")
            if not _wait_fills(engine, [exit_id], timeout_sec=120):
                logger.warning("Old hedge exit not confirmed; updating CSV anyway")

    if not placed_any:
        logger.info("All hedge strikes already correct — nothing to do")
        return 0

    broker = engine.order_router.broker
    if hasattr(broker, "get_positions_for_recon"):
        engine.position_manager.reconcile_with_broker(
            broker.get_positions_for_recon(), strategy=LEAPS_STRATEGY_ID
        )
    _write_open_positions_csv(engine)
    logger.info("Hedge strike reroll complete")
    return 0


def _write_open_positions_csv(engine: Any) -> None:
    path = getattr(engine.position_manager, "open_positions_csv_path", None)
    logger_op = getattr(engine, "_open_positions_logger", None)
    if logger_op is None or path is None:
        logger.warning("No open_positions logger; skip CSV rewrite")
        return
    try:
        broker = getattr(engine.order_router, "broker", None)
        if broker and hasattr(broker, "get_positions_for_recon"):
            bp = broker.get_positions_for_recon()
            engine.position_manager.reconcile_with_broker(bp, strategy=LEAPS_STRATEGY_ID)
        logger_op.record_broker_reconcile_snapshot(engine.position_manager)
        logger.info("Updated open positions CSV at %s", path)
    except Exception as exc:
        logger.exception("Failed to rewrite open positions CSV: %s", exc)


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Force LEAPS close + dual-structure entry")
    parser.add_argument(
        "--entry-only",
        action="store_true",
        help="Skip close cycle; place fresh entry bundles for all enabled legs",
    )
    parser.add_argument(
        "--main-reroll",
        action="store_true",
        help="Exit open MAIN only and enter fresh quarterly MAIN (keep HEDGE)",
    )
    parser.add_argument(
        "--hedge-reroll",
        action="store_true",
        help="Fix hedge strike to 500-grid OTM from MAIN (buy new, then exit old)",
    )
    args = parser.parse_args()

    configure_process_logging()
    if RUN_MODE != RunMode.LIVE:
        logger.error("RUN_MODE must be LIVE (got %s)", RUN_MODE)
        return 2

    job = _resolve_leaps_engine_job()
    if not job:
        logger.error("No ENGINE_JOBS entry with %s (dhan_leaps_rsi or dhan)", LEAPS_STRATEGY_ID)
        return 2

    cfg = job_to_engine_config(job)
    # Only LEAPS for this one-shot (avoid NiftyDOS / other co-located strategies)
    cfg.strategy_names = []
    cfg.strategy_name = LEAPS_STRATEGY_ID

    logger.info("Building live engine stack (no main loop)…")
    engine = EngineFactory.create_live_engine(cfg)
    strategy = _leaps_strategy(engine)
    logger.info(
        "Enabled legs: mini_leaps=%s quarterly_leaps=%s",
        getattr(strategy, "mini_leaps_enabled", None),
        getattr(strategy, "quarterly_leaps_enabled", None),
    )

    logger.info("Reconciling positions…")
    engine.reconcile_positions_on_start()
    engine._subscribe_open_option_legs()

    if args.main_reroll:
        return _main_reroll(engine, strategy)

    if args.hedge_reroll:
        return _hedge_strike_reroll(engine, strategy)

    if args.entry_only:
        logger.info("Entry-only mode — skipping close cycle")
    else:
        open_pos = engine.position_manager.get_open_positions(
            underlying="NIFTY", strategy=LEAPS_STRATEGY_ID
        ) or []
        logger.info(
            "Open before close: %s",
            [
                (
                    getattr(getattr(p, "instrument", None), "trading_symbol", None),
                    getattr(p, "tag", None),
                    getattr(p, "net_qty", None),
                )
                for p in open_pos
            ],
        )

        if open_pos:
            exit_ids = _force_close(engine, strategy)
            if exit_ids:
                logger.info("Waiting for exit fills…")
                if not _wait_fills(engine, exit_ids, timeout_sec=120):
                    return 1
            # Re-sync PM to broker
            broker = engine.order_router.broker
            if hasattr(broker, "get_positions_for_recon"):
                engine.position_manager.reconcile_with_broker(
                    broker.get_positions_for_recon(), strategy=LEAPS_STRATEGY_ID
                )
        else:
            logger.info("No open LEAPS positions to close")

        # Skip entry if still holding (partial close)
        still_open = [
            p
            for p in (
                engine.position_manager.get_open_positions(
                    underlying="NIFTY", strategy="LEAPS_RSI"
                )
                or []
            )
            if int(getattr(p, "net_qty", 0) or 0) != 0
        ]
        if still_open:
            logger.error(
                "Still open after exit attempt: %s — skipping entry",
                [
                    (
                        getattr(getattr(p, "instrument", None), "trading_symbol", None),
                        getattr(p, "net_qty", None),
                    )
                    for p in still_open
                ],
            )
            return 1

    logger.info("Placing new LEAPS entry…")
    entry_ids = _force_entry(engine, strategy)
    logger.info("Waiting for entry fills…")
    # Entries may rest as LIMIT — wait a bit, then accept SENT as success for restart
    ok_fills = _wait_fills(engine, entry_ids, timeout_sec=90)
    if not ok_fills:
        logger.warning("Entry fills not all confirmed; continuing to update CSV / restart")

    _write_open_positions_csv(engine)
    logger.info("Force LEAPS cycle complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
