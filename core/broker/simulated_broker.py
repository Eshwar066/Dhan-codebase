import uuid
import time
import random
import pdb
from core.broker.base_broker import BaseBroker


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
    def place_order(self, intent):
        """
        Same contract as DhanBroker.place_order
        """

        order_id = f"SIM-{uuid.uuid4().hex[:10]}"

        # ---- intent lifecycle ----
        if self.intent_store:
            self.intent_store.update(intent["intent_id"], "SENT")

        # simulate exchange latency
        if self.latency_ms:
            time.sleep(self.latency_ms / 1000)

        fill_price = self._fill_price(intent)

        # ---- update position manager ----
        instrument = intent["instrument"]
        self.position_manager.on_fill(
            instrument=instrument,
            side=intent["side"],
            qty=intent["qty"],
            price=float(intent["price"]),
            intent_id=intent["intent_id"],
            order_id=order_id,
            strategy=intent["strategy"],
            candle_ts=intent["candle_ts"],
            tag=intent["tag"],
            structure_id=intent["structure_id"],
            action=intent.get("action"),
        )
        if self.intent_store:
            self.intent_store.update(intent["intent_id"], "FILLED")

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

        intent = {
            "intent_id": f"exit_{uuid.uuid4().hex[:6]}",
            "trading_symbol": trading_symbol,
            "side": exit_side,
            "qty": int(qty),
            "segment": segment,
            "lot_size": int(lot_size),
            "order_type": "MARKET",
            "trade_type": "MARGIN",
        }

        return self.place_order(intent)

    # =========================
    # FILL PRICE MODEL
    # =========================
    def _fill_price(self, intent):
        """
        Market realism hook
        """
        price = intent.get("price", 0)

        # fallback: last traded price from PM
        if not price:
            # dont have this
            # price = self.position_manager.last_price(intent["trading_symbol"])
            price = 1

        if intent.get("order_type") == "MARKET":
            slippage = random.uniform(-0.0005, 0.0005)  # ±5 bps
            return round(price * (1 + slippage), 2)

        return float(price)
