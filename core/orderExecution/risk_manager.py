import time
import pdb


class RiskManager:
    def __init__(
        self,
        position_manager,
        max_portfolio_exposure=10000000,
        max_symbol_exposure=9000000,
        max_qty_per_symbol=10000,
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
    def allow_intent(self, intent, price_map, candle_ts=None):
        """
        intent: OrderIntent object
        """
        symbol = intent.instrument.trading_symbol
        side = intent.side
        qty = intent.qty
        price = intent.price or 0
        lot_size = getattr(intent, "lot_size", 65)
        strategy = getattr(intent, "strategy", None)
        structure_id = getattr(intent, "structure_id", None)
        tag = getattr(intent, "tag", None)
        action = getattr(intent, "action", "ENTRY")
        if action is None:
            raise ValueError(
                f"Intent {intent.intent_id} missing action " f"(ENTRY / EXIT / ROLL)"
            )

        # Exit/force exit always allowed
        if action in ("EXIT", "FORCE_EXIT"):
            return True

        # 0️⃣ STRUCTURE LOCK (🔥 IMPORTANT)
        if strategy and structure_id and action == "ENTRY" and tag == "MAIN":
            if self.pm.has_open_structure(
                structure_id=structure_id,
                tag="MAIN",
                strategy=strategy,
            ):
                print(f"❌ Structure already open {strategy} | {structure_id}")
                return False

        # 1️⃣ Cooldown check
        now_ts = self._get_event_time(candle_ts)
        if not self._cooldown_ok(symbol, now_ts):
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
        if not self._direction_ok(intent.instrument, side):
            print(f"❌ Opposite position exists {symbol}")
            return False

        # 5️⃣ Symbol exposure check
        sym_exposure = future_qty * price * lot_size
        # pdb.set_trace()
        if sym_exposure > self.max_symbol_exposure:
            print(f"❌ Symbol exposure breach {symbol},{sym_exposure}")
            return False

        # 6️⃣ Portfolio exposure check
        portfolio_exposure = self.pm.total_exposure(price_map)
        new_exposure = portfolio_exposure + (qty * price * lot_size)
        if new_exposure > self.max_portfolio_exposure:
            print("❌ Portfolio exposure breach")
            return False

        # Passed all checks
        key = (intent.strategy, intent.structure_id, intent.instrument.contract_key)
        self.last_trade_time[key] = now_ts
        return True

    # -------------------------
    # HELPERS
    # -------------------------
    def _direction_ok(self, instrument, side):
        for pos in self.pm.get_open_positions():
            if pos.instrument.contract_key != instrument.contract_key:
                continue

            if side == "BUY" and pos.net_qty < 0:
                return False

            if side == "SELL" and pos.net_qty > 0:
                return False

        return True

    def _open_positions_count(self):
        return sum(1 for p in self.pm.positions.values() if p.net_qty != 0)

    def _get_event_time(self, candle_ts):
        if candle_ts is None:
            return time.time()
        return candle_ts.timestamp()

    def _cooldown_ok(self, symbol, now_ts):
        last = self.last_trade_time.get(symbol, 0)
        return (now_ts - last) >= self.cooldown_seconds
