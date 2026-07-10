"""
One-shot: close open LEAPS_RSI structure and place a fresh ENTRY (hedge + main).

Manual emergency tool only — not imported by live engine / strategy registry.

Usage (stop dhan-leaps-rsi.service first):
  .venv/bin/python -m core.strategies.Leaps.emergency.force_leaps_cycle

  .venv/bin/python -m core.strategies.Leaps.emergency.force_leaps_cycle
.venv/bin/python -m core.strategies.Leaps.emergency.retry_leaps_main
"""

from __future__ import annotations

import logging
import sys
import time
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

load_dotenv()

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
logger = logging.getLogger("leaps.emergency.force_leaps_cycle")


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

    # Build price_map for all legs (custom + compact keys)
    price_map: Dict[str, float] = {}
    ordered: List[Any] = []
    # Ensure HEDGE before MAIN in bundle
    hedges = [i for i in intents if str(getattr(i, "tag", "")).upper() == "HEDGE"]
    mains = [i for i in intents if str(getattr(i, "tag", "")).upper() == "MAIN"]
    others = [
        i
        for i in intents
        if str(getattr(i, "tag", "")).upper() not in ("HEDGE", "MAIN")
    ]
    for intent in hedges + mains + others:
        px = _resolve_entry_price(engine, intent)
        if px is None or px <= 0:
            px = engine._positive_price(getattr(intent, "price", None))
        if px is None or px <= 0:
            raise RuntimeError(
                f"No entry price for {engine._intent_place_order_symbol(intent, '')}"
            )
        try:
            intent.price = float(px)
        except Exception:
            pass
        price_map.update(_price_map_for_intent(intent, float(px)))
        ordered.append(intent)

    structure_id = str(getattr(ordered[0], "structure_id", "") or "FORCE_ENTRY")
    bundle_item = {
        "intent_bundle": ordered,
        "price_map": price_map,
        "structure_id": structure_id,
        "strategy_id": strategy.name,
        "engine_id": getattr(engine, "engine_id", None),
        "idempotency_key": f"force_leaps|{structure_id}|{uuid.uuid4().hex[:8]}",
    }
    logger.info(
        "Placing hedge-gated ENTRY bundle legs=%s structure=%s",
        [(getattr(i, "tag", None), engine._intent_place_order_symbol(i, "")) for i in ordered],
        structure_id,
    )
    result = engine.order_router.process_intent_bundle(bundle_item)
    logger.info("Bundle result: %s", result)
    if not isinstance(result, dict) or not result.get("ok"):
        raise RuntimeError(f"Entry bundle failed: {result}")
    return [str(getattr(i, "intent_id", "")) for i in ordered if getattr(i, "intent_id", None)]


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
            engine.position_manager.reconcile_with_broker(bp, strategy="LEAPS_RSI")
        logger_op.record_broker_reconcile_snapshot(engine.position_manager)
        logger.info("Updated open positions CSV at %s", path)
    except Exception as exc:
        logger.exception("Failed to rewrite open positions CSV: %s", exc)


def main() -> int:
    configure_process_logging()
    if RUN_MODE != RunMode.LIVE:
        logger.error("RUN_MODE must be LIVE (got %s)", RUN_MODE)
        return 2

    job = None
    for j in ENGINE_JOBS:
        if j.get("engine_id") == "dhan_leaps_rsi":
            job = resolve_engine_job(j)
            break
    if not job:
        logger.error("dhan_leaps_rsi job not found")
        return 2

    cfg = job_to_engine_config(job)
    # Only LEAPS for this one-shot (avoid BankNiftyBTST side effects)
    cfg.strategy_names = []
    cfg.strategy_name = "LEAPS_RSI"

    logger.info("Building live engine stack (no main loop)…")
    engine = EngineFactory.create_live_engine(cfg)
    strategy = engine.strategy

    logger.info("Reconciling positions…")
    engine.reconcile_positions_on_start()
    engine._subscribe_open_option_legs()

    open_pos = engine.position_manager.get_open_positions(
        underlying="NIFTY", strategy="LEAPS_RSI"
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
                broker.get_positions_for_recon(), strategy="LEAPS_RSI"
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
