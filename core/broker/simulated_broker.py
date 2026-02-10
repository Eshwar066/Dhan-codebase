import uuid
import time
import random
import pdb
from core.broker.base_broker import BaseBroker
from core.models.order_intent import OrderIntent
from core.utils.instruments.instrument_store import Instrument


class SimulatedBroker(BaseBroker):
    def __init__(
        self,
        position_manager=None,
        intent_store=None,
        latency_ms=20,
    ):
        super().__init__(
            position_manager=position_manager,
            intent_store=intent_store,
        )
        self.latency_ms = latency_ms

    # =========================
    # PLACE ORDER (ENTRY / EXIT)
    # =========================
    def place_order(self, intent, execution_price):
        """
        intent: OrderIntent object
        """
        order_id = f"SIM-{uuid.uuid4().hex[:10]}"

        # ---- intent lifecycle ----
        if self.intent_store:
            self.intent_store.update(intent.intent_id, "SENT")

        # simulate exchange latency
        if self.latency_ms:
            time.sleep(self.latency_ms / 1000)

        # fill_price = self._fill_price(intent)

        # ---- update position manager ----
        instrument = intent.instrument
        assert isinstance(
            instrument, Instrument
        ), f"place_order expects Instrument, got {type(instrument)}"
        assert instrument.trading_symbol, "Instrument must have trading_symbol"
        assert instrument.custom_symbol, "Instrument must have custom_symbol"

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

    # =========================
    # EXIT POSITION (EXPLICIT)
    # =========================
    def exit_position(self, trading_symbol, qty, side, segment="EQ", lot_size=1):
        """
        Explicit exit helper
        Exit is STILL just an order
        """

        exit_side = "SELL" if side == "BUY" else "BUY"

        intent = OrderIntent(
            intent_id=f"exit_{uuid.uuid4().hex[:6]}",
            trading_symbol=trading_symbol,
            side=exit_side,
            qty=int(qty),
            segment=segment,
            lot_size=int(lot_size),
            order_type="MARKET",
            trade_type="MARGIN",
        )

        return self.place_order(intent)

    # =========================
    # FILL PRICE MODEL
    # =========================
    def _fill_price(self, intent):
        """
        Market realism hook
        """
        price = getattr(intent, "price", 0)

        # fallback: last traded price from PM
        if not price:
            # don't have this
            # price = self.position_manager.last_price(intent.trading_symbol)
            price = 1

        if getattr(intent, "order_type", None) == "MARKET":
            slippage = random.uniform(-0.0005, 0.0005)  # ±5 bps
            return round(price * (1 + slippage), 2)

        return float(price)
