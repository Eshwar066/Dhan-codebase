"""Simulated broker for backtest."""

import uuid
import time
from datetime import datetime

from core.broker.base import BaseBroker
from core.models.order_intent import OrderIntent
from core.utils.instruments.instrument_store import Instrument


class SimulatedBroker(BaseBroker):
    def __init__(self, position_manager=None, intent_store=None, latency_ms=20):
        super().__init__(position_manager=position_manager, intent_store=intent_store)
        self.latency_ms = latency_ms

    def place_order(self, intent, execution_price=None, retries=0):
        order_id = f"SIM-{uuid.uuid4().hex[:10]}"
        if self.intent_store:
            self.intent_store.update(intent.intent_id, "SENT")
        if self.latency_ms:
            time.sleep(self.latency_ms / 1000)
        instrument = intent.instrument
        assert isinstance(instrument, Instrument), f"place_order expects Instrument, got {type(instrument)}"
        assert instrument.trading_symbol and instrument.custom_symbol
        if self.order_router:
            self.order_router.process_fill(
                instrument=instrument,
                side=intent.side,
                qty=intent.qty,
                price=float(execution_price),
                expected_price=getattr(intent, "price", None),
                order_id=order_id,
                intent_id=intent.intent_id,
                strategy=getattr(intent, "strategy", None),
                candle_ts=getattr(intent, "candle_ts", None),
                tag=getattr(intent, "tag", None),
                structure_id=getattr(intent, "structure_id", None),
                action=getattr(intent, "action", None),
            )
        else:
            self.position_manager.on_fill(
                instrument=instrument,
                side=intent.side,
                qty=intent.qty,
                price=float(execution_price),
                intent_id=intent.intent_id,
                order_id=order_id,
                strategy=getattr(intent, "strategy", None),
                candle_ts=getattr(intent, "candle_ts", None),
                tag=getattr(intent, "tag", None),
                structure_id=getattr(intent, "structure_id", None),
                action=getattr(intent, "action", None),
            )
            if self.intent_store:
                self.intent_store.update(intent.intent_id, "FILLED")
        return order_id

    def exit_position(self, trading_symbol, qty, side, segment="EQ", lot_size=1):
        exit_side = "SELL" if side == "BUY" else "BUY"
        # Minimal intent for simulated exit; real OrderIntent requires instrument
        intent = OrderIntent(
            intent_id=f"exit_{uuid.uuid4().hex[:6]}",
            instrument=Instrument(
                trading_symbol=trading_symbol,
                custom_symbol=trading_symbol,
                exchange="NSE",
                segment=segment,
                instrument_type="EQ",
                lot_size=lot_size,
            ),
            side=exit_side,
            qty=int(qty),
            price=0.0,
            order_type="MARKET",
            strategy="",
            structure_id="",
            trade_type="MARGIN",
            tag=None,
            symbol=trading_symbol,
            action="EXIT",
            candle_ts=datetime.now(),
        )
        return self.place_order(intent, execution_price=0.0)
