import time
import pdb


# place this in live_engine.py
# # live_engine.py

# intent = strategy.generate_intent()

# intent_store.create(intent)

# if risk_manager.allow_intent(intent, price_map):

#     broker.place_order(intent)

#     intent_store.update(intent_id, "SENT")

# else:

#     intent_store.update(intent_id, "REJECTED")


class RiskManager:
    def __init__(
        self,
        position_manager,
        max_portfolio_exposure=10_000_000,
        max_symbol_exposure=2_000_000,
        max_qty_per_symbol=10_000,
        max_open_positions=20,
        cooldown_seconds=5,
    ):
        self.pm = position_manager

        # Limits
        self.max_portfolio_exposure = max_portfolio_exposure
        self.max_symbol_exposure = max_symbol_exposure
        self.max_qty_per_symbol = max_qty_per_symbol
        self.max_open_positions = max_open_positions

        # Anti-overtrading
        self.cooldown_seconds = cooldown_seconds
        self.last_trade_time = {}

    # -------------------------
    # MAIN CHECK
    # -------------------------
    def allow_intent(self, intent, price_map):
        """
        intent format:
        {
            "symbol": str,
            "side": BUY/SELL,
            "qty": int,
            "price": float,
            "instrument": Instrument,
            "strategy": str (optional)
        }
        """

        symbol = intent["symbol"]
        side = intent["side"]
        qty = intent["qty"]
        price = intent.get("price", 0)
        lot_size = intent.get("lot_size", 65)

        # 1️⃣ Cooldown check
        if not self._cooldown_ok(symbol):
            print(f"❌ Cooldown active {symbol}")
            return False

        # 2️⃣ Position count limit
        if self._open_positions_count() >= self.max_open_positions:
            print("❌ Max open positions reached")
            return False

        # 3️⃣ Per-symbol qty limit
        future_qty = abs(self.pm.get_qty(symbol)) + qty
        if future_qty > self.max_qty_per_symbol:
            print(f"❌ Qty limit breach {symbol}")
            return False

        # 4️⃣ No double-direction entries
        if not self._direction_ok(symbol, side):
            print(f"❌ Opposite position exists {symbol}")
            return False

        # 5️⃣ Symbol exposure check
        sym_exposure = future_qty * price * lot_size
        if sym_exposure > self.max_symbol_exposure:
            print(f"❌ Symbol exposure breach {symbol}")
            return False

        # 6️⃣ Portfolio exposure check
        portfolio_exposure = self.pm.total_exposure(price_map)
        new_exposure = portfolio_exposure + (qty * price * lot_size)

        if new_exposure > self.max_portfolio_exposure:
            print("❌ Portfolio exposure breach")
            return False

        # Passed all checks
        self.last_trade_time[symbol] = time.time()
        return True

    # -------------------------
    # HELPERS
    # -------------------------
    def _direction_ok(self, symbol, side):
        if side == "BUY" and self.pm.is_short(symbol):
            return False
        if side == "SELL" and self.pm.is_long(symbol):
            return False
        return True

    def _open_positions_count(self):
        return sum(1 for p in self.pm.positions.values() if p.net_qty != 0)

    def _cooldown_ok(self, symbol):
        last = self.last_trade_time.get(symbol, 0)
        return (time.time() - last) >= self.cooldown_seconds
