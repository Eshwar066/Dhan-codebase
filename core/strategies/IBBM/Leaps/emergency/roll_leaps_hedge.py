"""
One-shot: roll LEAPS monthly hedge — BUY next-month hedge first, then EXIT old.

Order matters for margin: new long hedge on books before selling the current-month
hedge (avoids briefly unhedged MAIN).

Manual emergency tool only — not imported by live engine / strategy registry.

Usage (stop dhan-leaps-rsi.service first, run after market open):
  .venv/bin/python -m core.strategies.IBBM.Leaps.emergency.roll_leaps_hedge --dry-run
  .venv/bin/python -m core.strategies.IBBM.Leaps.emergency.roll_leaps_hedge
  .venv/bin/python -m core.strategies.IBBM.Leaps.emergency.roll_leaps_hedge --structure-id LEAPS_RSI:NIFTY:...

Flags:
  --dry-run         Print intended legs; place nothing
  --structure-id    Roll only this structure (repeatable)
  --use-calendar    Use strategy resolve_hedge_expiry (15th cutoff) instead of
                    always next-month expiry
  --no-wait         Do not wait for fills between buy and exit (not recommended)
"""

from __future__ import annotations

import logging
import sys
import time
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Sequence, Tuple
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

load_dotenv()

from run.config import ENGINE_JOBS, RUN_MODE, RunMode
from run.engine_config import configure_process_logging
from run.main import job_to_engine_config
from run.strategy_profiles import resolve_engine_job
from core.engine.factory import EngineFactory
from core.orderExecution.intent_store import IntentStatus
from core.orderExecution.order_router import OrderState
from core.utils.expiry_resolver import ExpiryResolver
from core.utils.price_tick import resolve_tick_size, round_by_tick_size

IST = ZoneInfo("Asia/Kolkata")
logger = logging.getLogger("leaps.emergency.roll_leaps_hedge")


def _price_map_for_intent(intent: Any, price: float) -> Dict[str, float]:
    p = float(price)
    out: Dict[str, float] = {}
    inst = getattr(intent, "instrument", None)
    if inst is None:
        return out
    if hasattr(inst, "place_order_symbol"):
        try:
            pos = inst.place_order_symbol()
        except Exception:
            pos = None
        if pos:
            out[str(pos)] = p
    for attr in ("trading_symbol", "custom_symbol"):
        val = getattr(inst, attr, None)
        if val:
            out[str(val)] = p
    return out


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
        trading_sym,
        engine.instrument_store,
        instrument=getattr(intent, "instrument", None),
    )
    mode = "ceil" if is_buy else "floor"
    rounded = round_by_tick_size(float(price), tick, floor_or_ceil=mode)
    return float(rounded if rounded is not None else price)


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


def _place(engine: Any, intent: Any, price: float, label: str) -> bool:
    pm = _price_map_for_intent(intent, price)
    try:
        intent.price = float(price)
    except Exception:
        pass
    logger.info(
        "Placing %s %s %s qty=%s @ %s",
        label,
        getattr(intent, "side", ""),
        engine._intent_place_order_symbol(intent, ""),
        getattr(intent, "qty", None),
        price,
    )
    result = engine.order_router.process_intent(intent, pm)
    ok = isinstance(result, dict) and result.get("ok")
    logger.info("Result %s: %s", label, result)
    return bool(ok)


def _wait_fills(engine: Any, intent_ids: List[str], timeout_sec: float = 120.0) -> bool:
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
    now_ist = datetime.now(IST)
    minute = 15
    hour = now_ist.hour if now_ist.minute >= 15 else max(9, now_ist.hour - 1)
    if now_ist.hour < 9 or (now_ist.hour == 9 and now_ist.minute < 15):
        hour, minute = 9, 15
    bar_open_ist = now_ist.replace(hour=hour, minute=minute, second=0, microsecond=0)
    bar_open_utc = bar_open_ist.astimezone(ZoneInfo("UTC")).replace(tzinfo=None)
    spot = engine.get_price_map(symbol) or 0.0
    if spot <= 0:
        try:
            candles = engine.data.get_latest_candles([symbol])
            row = (candles or {}).get(symbol) or {}
            if row.get("close"):
                spot = float(row["close"])
        except Exception:
            pass
    return {
        "symbol": symbol,
        "exchange": "INDEX",
        "timestamp": bar_open_utc,
        "open": float(spot),
        "high": float(spot),
        "low": float(spot),
        "close": float(spot),
        "volume": 0,
        "timeframe": "60",
        "bucket_ts": int(bar_open_ist.timestamp()),
    }


def _inst_expiry_date(inst: Any) -> Optional[date]:
    raw = getattr(inst, "expiry", None)
    if raw is None:
        return None
    try:
        import pandas as pd

        ts = pd.to_datetime(raw, errors="coerce")
        if ts is None or (hasattr(ts, "isna") and bool(ts.isna())):
            return None
        return ts.date() if hasattr(ts, "date") else date.fromisoformat(str(raw)[:10])
    except Exception:
        return None


def _next_month_hedge_expiry(strategy: Any, trade_date: date) -> date:
    exp_wd = int(getattr(strategy, "hedge_monthly_expiry_weekday", 1) or 1) % 7
    return ExpiryResolver.next_month_expiry(trade_date, weekday=exp_wd)


def _structures_to_roll(
    open_pos: Sequence[Any],
    structure_filter: Optional[Sequence[str]],
) -> List[Tuple[Any, Any]]:
    """Return (main, hedge) pairs that have both legs open."""
    by_sid: Dict[str, Dict[str, Any]] = {}
    for p in open_pos:
        sid = str(getattr(p, "structure_id", "") or "")
        if not sid:
            continue
        tag = str(getattr(p, "tag", "") or "").upper()
        if tag not in ("MAIN", "HEDGE"):
            continue
        if int(getattr(p, "net_qty", 0) or 0) == 0:
            continue
        by_sid.setdefault(sid, {})[tag] = p

    wanted = {str(s) for s in (structure_filter or []) if s}
    pairs: List[Tuple[Any, Any]] = []
    for sid, legs in sorted(by_sid.items()):
        if wanted and sid not in wanted:
            continue
        main = legs.get("MAIN")
        hedge = legs.get("HEDGE")
        if main is None or hedge is None:
            logger.warning(
                "Skip structure=%s (need MAIN+HEDGE; have %s)",
                sid,
                sorted(legs.keys()),
            )
            continue
        pairs.append((main, hedge))
    return pairs


def _recover_orphan_leaps_pairs(
    engine: Any,
    open_pos: Sequence[Any],
    *,
    structure_filter: Optional[Sequence[str]] = None,
) -> List[Tuple[Any, Any]]:
    """
    Broker reconcile often drops strategy/structure_id and tags both legs MAIN.

    Recover NIFTY LEAPS-style pairs: short option = MAIN, long same type = HEDGE.
    Mutates position objects in-place so create_hedge_* / get_hedge_for work.
    """
    nifty_opts = []
    for p in open_pos:
        if int(getattr(p, "net_qty", 0) or 0) == 0:
            continue
        inst = getattr(p, "instrument", None)
        sym = str(
            getattr(inst, "trading_symbol", None)
            or getattr(inst, "custom_symbol", None)
            or ""
        ).upper()
        if not (sym.startswith("NIFTY ") or sym.startswith("NIFTY-")):
            continue
        opt = str(getattr(inst, "option_type", "") or "").upper()
        if opt not in ("CE", "PE", "CALL", "PUT"):
            # Infer from symbol suffix
            if sym.endswith("-CE") or " CALL" in sym:
                opt = "CE"
            elif sym.endswith("-PE") or " PUT" in sym:
                opt = "PE"
            else:
                continue
        nifty_opts.append((p, opt))

    shorts = [(p, o) for p, o in nifty_opts if int(getattr(p, "net_qty", 0) or 0) < 0]
    longs = [(p, o) for p, o in nifty_opts if int(getattr(p, "net_qty", 0) or 0) > 0]
    if not shorts or not longs:
        return []

    pairs: List[Tuple[Any, Any]] = []
    used_longs: set[int] = set()
    wanted = {str(s) for s in (structure_filter or []) if s}

    for main, opt in shorts:
        # Prefer long with same option type; if multiple, prefer nearer expiry (current hedge).
        candidates = []
        for i, (hp, ho) in enumerate(longs):
            if i in used_longs:
                continue
            if ho != opt and not (
                {ho, opt} <= {"CE", "CALL"} or {ho, opt} <= {"PE", "PUT"}
            ):
                continue
            candidates.append((i, hp))
        if not candidates:
            logger.warning(
                "No long hedge candidate for short %s",
                getattr(getattr(main, "instrument", None), "trading_symbol", None),
            )
            continue
        candidates.sort(
            key=lambda t: (
                _inst_expiry_date(getattr(t[1], "instrument", None)) or date.max
            )
        )
        li, hedge = candidates[0]
        used_longs.add(li)

        # Repair metadata for OMS helpers.
        sid = str(getattr(main, "structure_id", "") or "") or (
            f"LEAPS_RSI:NIFTY:EMERGENCY_ROLL:"
            f"{getattr(getattr(main, 'instrument', None), 'strike', '')}:"
            f"{opt}"
        )
        if wanted and sid not in wanted and str(getattr(main, "structure_id", "") or "") not in wanted:
            # Allow filter match on repaired sid only when explicitly listed.
            if sid not in wanted:
                continue

        for pos, tag in ((main, "MAIN"), (hedge, "HEDGE")):
            try:
                pos.strategy = "LEAPS_RSI"
                pos.structure_id = sid
                pos.tag = tag
            except Exception:
                pass
            # Ensure instrument is a full Instrument (strike/expiry/option_type).
            inst = getattr(pos, "instrument", None)
            tsym = str(getattr(inst, "trading_symbol", "") or "")
            if inst is not None and (
                getattr(inst, "strike", None) in (None, 0, 0.0)
                or getattr(inst, "expiry", None) in (None, "")
                or not getattr(inst, "option_type", None)
            ):
                try:
                    # Parse compact Dhan symbol NIFTY-MonYYYY-strike-CE/PE
                    parts = tsym.split("-")
                    strike = float(parts[2]) if len(parts) >= 4 else 0.0
                    ot = parts[3] if len(parts) >= 4 else opt
                    resolved = engine.instrument_store.intent_creation_details(
                        tsym, "INDEX", None, ot, strike, prefer_monthly=True
                    )
                    if resolved is not None:
                        pos.instrument = resolved
                except Exception as exc:
                    logger.warning("Could not re-resolve instrument %s: %s", tsym, exc)

        logger.info(
            "Recovered orphan pair structure=%s MAIN=%s HEDGE=%s",
            sid,
            getattr(getattr(main, "instrument", None), "trading_symbol", None),
            getattr(getattr(hedge, "instrument", None), "trading_symbol", None),
        )
        pairs.append((main, hedge))
    return pairs


def _create_new_hedge_intent(
    strategy: Any,
    parent: Any,
    candle: dict,
    ctx: Any,
    *,
    target_expiry: date,
) -> Any:
    """Build next-month HEDGE BUY using strategy helpers; force target expiry."""

    def _forced_expiry(trade_date, parent_expiry=None):
        _ = trade_date, parent_expiry
        return target_expiry

    orig = strategy.resolve_hedge_expiry
    strategy.resolve_hedge_expiry = _forced_expiry  # type: ignore[method-assign]
    try:
        return strategy.create_hedge_intent(parent, candle, ctx)
    finally:
        strategy.resolve_hedge_expiry = orig  # type: ignore[method-assign]


def _describe_leg(engine: Any, intent: Any) -> str:
    inst = getattr(intent, "instrument", None)
    return (
        f"tag={getattr(intent, 'tag', None)} "
        f"side={getattr(intent, 'side', None)} "
        f"sym={engine._intent_place_order_symbol(intent, '')} "
        f"strike={getattr(inst, 'strike', None)} "
        f"expiry={getattr(inst, 'expiry', None)} "
        f"qty={getattr(intent, 'qty', None)}"
    )


def _roll_one(
    engine: Any,
    strategy: Any,
    main: Any,
    old_hedge: Any,
    candle: dict,
    ctx: Any,
    *,
    dry_run: bool,
    wait_fills: bool,
    use_calendar: bool,
) -> bool:
    sid = str(getattr(main, "structure_id", "") or "")
    trade_date = datetime.now(IST).date()
    if use_calendar:
        parent_exp = getattr(getattr(main, "instrument", None), "expiry", None)
        target_expiry = strategy.resolve_hedge_expiry(
            trade_date, parent_expiry=parent_exp
        )
    else:
        target_expiry = _next_month_hedge_expiry(strategy, trade_date)

    old_exp = _inst_expiry_date(getattr(old_hedge, "instrument", None))
    if old_exp is not None and old_exp.year == target_expiry.year and old_exp.month == target_expiry.month:
        logger.info(
            "structure=%s hedge already on target month %s — skip",
            sid,
            target_expiry,
        )
        return True

    new_hedge = _create_new_hedge_intent(
        strategy, main, candle, ctx, target_expiry=target_expiry
    )
    if new_hedge is None:
        logger.error("structure=%s could not build new hedge intent", sid)
        return False

    hedge_exit = strategy.create_hedge_exit_intent(main, candle, ctx)
    if hedge_exit is None:
        logger.error("structure=%s could not build HEDGE_EXIT for old hedge", sid)
        return False

    logger.info(
        "Roll plan structure=%s\n  1) BUY  %s\n  2) EXIT %s",
        sid,
        _describe_leg(engine, new_hedge),
        _describe_leg(engine, hedge_exit),
    )

    if dry_run:
        logger.info("DRY-RUN: not placing orders for %s", sid)
        return True

    # 1) Buy new-month hedge first (margin).
    buy_px = _resolve_entry_price(engine, new_hedge)
    if buy_px is None:
        logger.error("No entry price for new hedge %s", sid)
        return False
    if not _place(engine, new_hedge, buy_px, f"HEDGE_ROLL_BUY:{sid}"):
        return False
    buy_id = str(getattr(new_hedge, "intent_id", "") or "")
    if wait_fills and buy_id:
        logger.info("Waiting for new hedge fill…")
        if not _wait_fills(engine, [buy_id], timeout_sec=180):
            logger.error(
                "New hedge not filled — NOT exiting old hedge for %s (margin-safe)",
                sid,
            )
            return False

    # 2) Exit current-month hedge.
    exit_px = _resolve_exit_price(engine, hedge_exit)
    if exit_px is None:
        logger.error("No exit price for old hedge %s", sid)
        return False
    if not _place(engine, hedge_exit, exit_px, f"HEDGE_ROLL_EXIT:{sid}"):
        return False
    exit_id = str(getattr(hedge_exit, "intent_id", "") or "")
    if wait_fills and exit_id:
        logger.info("Waiting for old hedge exit fill…")
        if not _wait_fills(engine, [exit_id], timeout_sec=180):
            return False

    # Mark rolled so live engine does not double-roll same day if restarted.
    roll_key = (sid, trade_date)
    rolled = getattr(strategy, "rolled_hedges", None)
    if isinstance(rolled, set):
        rolled.add(roll_key)

    logger.info("Hedge rollover complete structure=%s → expiry %s", sid, target_expiry)
    return True


def _write_open_positions_csv(engine: Any) -> None:
    path = getattr(engine.position_manager, "open_positions_csv_path", None)
    logger_op = getattr(engine, "_open_positions_logger", None)
    if logger_op is None or path is None:
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


def main(argv: Optional[Sequence[str]] = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Emergency LEAPS hedge rollover (buy next month, then exit old)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print roll plan only; place no orders",
    )
    parser.add_argument(
        "--structure-id",
        action="append",
        default=[],
        help="Only roll this structure_id (repeatable)",
    )
    parser.add_argument(
        "--use-calendar",
        action="store_true",
        help="Use strategy 15th-cutoff expiry instead of always next month",
    )
    parser.add_argument(
        "--no-wait",
        action="store_true",
        help="Do not wait for fills between buy and exit (risky for margin)",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

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
    cfg.strategy_names = []
    cfg.strategy_name = "LEAPS_RSI"

    logger.info(
        "Building live engine stack (no main loop) dry_run=%s use_calendar=%s…",
        args.dry_run,
        args.use_calendar,
    )
    engine = EngineFactory.create_live_engine(cfg)
    strategy = engine.strategy

    logger.info("Reconciling positions…")
    engine.reconcile_positions_on_start()
    engine._subscribe_open_option_legs()

    open_pos = (
        engine.position_manager.get_open_positions(
            underlying="NIFTY", strategy="LEAPS_RSI"
        )
        or []
    )
    if not open_pos:
        # Broker reconcile may have cleared strategy=LEAPS_RSI; fall back to all NIFTY.
        open_pos = (
            engine.position_manager.get_open_positions(underlying="NIFTY") or []
        )
    logger.info(
        "Open legs: %s",
        [
            (
                getattr(p, "structure_id", None),
                getattr(p, "strategy", None),
                getattr(p, "tag", None),
                getattr(getattr(p, "instrument", None), "trading_symbol", None),
                getattr(getattr(p, "instrument", None), "expiry", None),
                getattr(p, "net_qty", None),
            )
            for p in open_pos
        ],
    )

    pairs = _structures_to_roll(open_pos, args.structure_id or None)
    if not pairs:
        logger.info(
            "No tagged MAIN+HEDGE pairs; trying orphan broker-reconcile recovery…"
        )
        pairs = _recover_orphan_leaps_pairs(
            engine, open_pos, structure_filter=args.structure_id or None
        )
    if not pairs:
        logger.info("No MAIN+HEDGE structures to roll")
        return 0

    candle = _synthetic_candle(engine, "NIFTY")
    ctx = engine.build_context_only(candle)

    ok_all = True
    for main, hedge in pairs:
        ok = _roll_one(
            engine,
            strategy,
            main,
            hedge,
            candle,
            ctx,
            dry_run=bool(args.dry_run),
            wait_fills=not bool(args.no_wait),
            use_calendar=bool(args.use_calendar),
        )
        if not ok:
            ok_all = False

    if not args.dry_run:
        broker = getattr(engine.order_router, "broker", None)
        if broker and hasattr(broker, "get_positions_for_recon"):
            try:
                engine.position_manager.reconcile_with_broker(
                    broker.get_positions_for_recon(), strategy="LEAPS_RSI"
                )
            except Exception as exc:
                logger.warning("post-roll reconcile failed: %s", exc)
        _write_open_positions_csv(engine)

    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main())
