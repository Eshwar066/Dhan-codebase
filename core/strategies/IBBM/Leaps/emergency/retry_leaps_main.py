"""Retry MAIN after hedge fill; flatten orphan hedge on insufficient funds.

Manual emergency tool only — not imported by live engine / strategy registry.

Usage (stop dhan-leaps-rsi.service first):
  .venv/bin/python -m core.strategies.IBBM.Leaps.emergency.retry_leaps_main
"""
from __future__ import annotations

import logging
import sys
import time
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

load_dotenv()

from run.config import ENGINE_JOBS
from run.engine_config import configure_process_logging
from run.main import job_to_engine_config
from run.strategy_profiles import resolve_engine_job
from core.engine.factory import EngineFactory
from core.models.order_intent import OrderIntent
from core.orderExecution.intent_store import IntentStatus
from core.orderExecution.position_manager import PositionManager

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("leaps.emergency.retry_leaps_main")
configure_process_logging()
IST = ZoneInfo("Asia/Kolkata")


def main() -> int:
    job = resolve_engine_job(
        next(j for j in ENGINE_JOBS if j.get("engine_id") == "dhan_leaps_rsi")
    )
    cfg = job_to_engine_config(job)
    cfg.strategy_names = []
    cfg.strategy_name = "LEAPS_RSI"
    engine = EngineFactory.create_live_engine(cfg)
    strategy = engine.strategy
    engine.reconcile_positions_on_start()
    engine._subscribe_open_option_legs()

    broker = engine.order_router.broker
    bp = (
        broker.get_positions_for_recon()
        if hasattr(broker, "get_positions_for_recon")
        else {}
    )
    log.info(
        "Broker positions: %s",
        {k: v.get("qty") for k, v in (bp or {}).items() if v.get("qty")},
    )

    time.sleep(5)

    now = datetime.now(IST)
    bar = now.replace(minute=15, second=0, microsecond=0)
    if now.minute < 15:
        bar = bar.replace(hour=max(9, now.hour - 1))
    spot = engine.get_price_map("NIFTY") or 25000
    candle = {
        "symbol": "NIFTY",
        "exchange": "INDEX",
        "timestamp": bar.astimezone(ZoneInfo("UTC")).replace(tzinfo=None),
        "open": spot,
        "high": spot,
        "low": spot,
        "close": spot,
        "volume": 0,
        "rsi": 55.0,
        "prev_rsi": 50.0,
        "timeframe": "60",
    }
    for attr in ("_entry_signaled_keys", "_evaluated_signal_keys"):
        bag = getattr(strategy, attr, None)
        if isinstance(bag, set):
            bag.clear()
    ctx = engine.build_context_only(candle)
    ctx.exchange = "INDEX"
    intents = strategy.on_candle(candle, ctx) or []
    if not isinstance(intents, list):
        intents = [intents]
    log.info(
        "Intents: %s",
        [
            (i.tag, i.side, i.instrument.trading_symbol, i.price)
            for i in intents
        ],
    )

    main_intent = next((i for i in intents if str(i.tag).upper() == "MAIN"), None)
    if main_intent is None:
        log.error("no MAIN intent")
        return 1

    def place(intent, price):
        trading = engine._intent_place_order_symbol(intent, "")
        pm = {trading: float(price)}
        ts = getattr(intent.instrument, "trading_symbol", None)
        if ts:
            pm[str(ts)] = float(price)
        try:
            intent.price = float(price)
        except Exception:
            pass
        log.info("Placing %s %s @ %s", intent.tag, trading, price)
        return engine.order_router.process_intent(intent, pm)

    def entry_price(intent):
        trading = engine._intent_place_order_symbol(intent, "")
        is_buy = str(intent.side).upper() == "BUY"
        px = (
            engine._entry_price_from_depth(trading, is_buy)
            or engine.get_price_map(trading)
            or intent.price
        )
        return float(px) if px and float(px) > 0 else None

    def exit_price(intent):
        trading = engine._intent_place_order_symbol(intent, "")
        is_sell = str(intent.side).upper() == "SELL"
        px = (
            engine._exit_price_from_depth(trading, is_sell)
            or engine.get_price_map(trading)
            or intent.price
        )
        return float(px) if px else None

    trading = engine._intent_place_order_symbol(main_intent, "")
    px = entry_price(main_intent)
    bid, ask = engine._get_bid_ask(trading)
    if bid:
        px = float(bid) - engine._get_tick_size(trading)
    if px is None:
        log.error("no MAIN price")
        return 1

    res = place(main_intent, px)
    log.info("MAIN result: %s", res)

    if not (isinstance(res, dict) and res.get("ok")):
        log.error("MAIN failed — flattening long option legs")
        bp2 = broker.get_positions_for_recon() if hasattr(broker, "get_positions_for_recon") else {}
        for sym, row in (bp2 or {}).items():
            qty = int(row.get("qty") or 0)
            if qty <= 0:
                continue
            opt, strike = PositionManager._extract_option_hint(sym, None)
            inst = engine.instrument_store.intent_creation_details(
                sym, "NSE", None, opt, strike
            )
            if inst is None:
                log.warning("cannot resolve %s", sym)
                continue
            lot = int(getattr(inst, "lot_size", 65) or 65)
            intent = OrderIntent(
                intent_id=uuid.uuid4().hex,
                instrument=inst,
                side="SELL",
                qty=max(1, qty // lot),
                price=None,
                order_type="LIMIT",
                strategy="LEAPS_RSI",
                structure_id="FORCE_FLATTEN",
                trade_type="MARGIN",
                tag="FORCE_EXIT",
                symbol="NIFTY",
                action="EXIT",
                candle_ts=candle["timestamp"],
            )
            ep = exit_price(intent)
            if ep is None:
                log.error("no exit price for %s", sym)
                continue
            r = place(intent, ep)
            log.info("Flatten %s: %s", sym, r)
            time.sleep(2)
            engine.order_router.sync_trades_from_broker()
        return 1

    iid = main_intent.intent_id
    for _ in range(30):
        engine.order_router.sync_trades_from_broker()
        rec = engine.order_router.intent_store.get(iid)
        if rec and rec.get("status") == IntentStatus.FILLED:
            log.info("MAIN filled")
            break
        time.sleep(2)
    else:
        log.warning("MAIN not confirmed filled yet")

    op = getattr(engine, "_open_positions_logger", None)
    if op and hasattr(broker, "get_positions_for_recon"):
        engine.position_manager.reconcile_with_broker(
            broker.get_positions_for_recon(), strategy="LEAPS_RSI"
        )
        op.record_broker_reconcile_snapshot(engine.position_manager)
        log.info("CSV updated")
    log.info("DONE")
    return 0


if __name__ == "__main__":
    sys.exit(main())
