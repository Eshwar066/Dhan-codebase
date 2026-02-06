import threading
import time
from collections import defaultdict
from logs.logger.trade_logger import TradeLogger
from datetime import datetime
import uuid
import pdb

# use
# How to Run Auto-Reconciliation
#   def recon_loop(pm, broker):
#     while True:
#         try:
#             broker_pos = broker.get_positions()
#             pm.reconcile_with_broker(broker_pos)

#         except Exception as e:
#             print("Recon error:", e)

#         time.sleep(180)  # 3 minutes

#   start It:
#     threading.Thread(
#     target=recon_loop,
#     args=(position_manager, broker),
#     daemon=True
#     ).start()

# ⭐ Important Rules (For Your Live System)
#     1️⃣ Pause trading on big drift
#     if abs(local_qty - broker_qty) > threshold:
#         pause_trading()

#     2️⃣ Reconcile on startup ALWAYS
#     Before first trade.

#     3️⃣ Log every correction
#     This helps debug broker/API issues.


# =========================
# INSTRUMENT
# =========================


class Instrument:
    def __init__(
        self,
        symbol,
        segment="EQ",  # EQ/FUT/OPT/CRYPTO/MCX
        lot_size=1,
        strike=None,
        option_type=None,
        expiry=None,
    ):
        self.symbol = symbol
        self.segment = segment
        self.lot_size = lot_size
        self.strike = strike
        self.option_type = option_type
        self.expiry = expiry


# =========================
# POSITION
# =========================
class Position:
    def __init__(self, instrument):
        self.instrument = instrument
        self.net_qty = 0
        self.avg_price = 0.0
        self.realized_pnl = 0.0

        self.trade_id = None
        self.entry_price = None
        self.entry_time = None

        self.mae = 0.0
        self.mfe = 0.0

        self.strategy = None
        self.structure_id = None
        self.tag = None

        self.last_updated = time.time()

    def update_fill(self, side, qty, price):
        signed_qty = qty if side == "BUY" else -qty

        # -------- ENTRY --------
        if self.net_qty == 0:
            self.trade_id = f"T-{uuid.uuid4().hex[:10]}"
            self.entry_price = price
            self.entry_time = time.time()
            self.mae = 0.0
            self.mfe = 0.0

        # -------- SAME DIRECTION --------
        if (
            self.net_qty == 0
            or (self.net_qty > 0 and signed_qty > 0)
            or (self.net_qty < 0 and signed_qty < 0)
        ):
            new_qty = self.net_qty + signed_qty

            self.avg_price = (
                (
                    (self.avg_price * abs(self.net_qty) + price * abs(signed_qty))
                    / abs(new_qty)
                )
                if new_qty != 0
                else 0
            )

            self.net_qty = new_qty

        # -------- CLOSING / REDUCING --------
        else:
            closing = min(abs(self.net_qty), abs(signed_qty))

            pnl = closing * (price - self.avg_price)
            if self.net_qty < 0:
                pnl *= -1

            pnl *= self.instrument.lot_size
            self.realized_pnl += pnl

            self.net_qty += signed_qty

            if self.net_qty == 0:
                self.avg_price = 0.0

        self.last_updated = time.time()


def update_risk_metrics(self, ltp):
    if self.net_qty == 0:
        return

    diff = ltp - self.entry_price
    if self.net_qty < 0:
        diff *= -1

    self.mfe = max(self.mfe, diff)
    self.mae = min(self.mae, diff)


# =========================
# POSITION MANAGER
# =========================


class PositionManager:
    def __init__(self, logger):
        self._lock = threading.Lock()
        self.logger = TradeLogger()
        # symbol → Position
        self.positions = {}
        # strategy → symbol → qty
        self.strategy_pos = defaultdict(lambda: defaultdict(int))

        self.last_recon_time = 0

    # ---------------------
    # LOCAL FILL UPDATE
    # ---------------------

    def on_fill(
        self,
        instrument,
        side,
        qty,
        price,
        intent_id=None,
        order_id=None,
        strategy=None,
        structure_id=None,
        tag=None,
        candle_ts=None,
    ):
        with self._lock:
            sym = instrument["SEM_CUSTOM_SYMBOL"]

            prev_qty = self.positions[sym].net_qty if sym in self.positions else 0

            if sym not in self.positions:
                self.positions[sym] = Position(instrument)

            pos = self.positions[sym]

            pos.update_fill(side, qty, price)

            new_qty = pos.net_qty

            if strategy:
                signed = qty if side == "BUY" else -qty
                self.strategy_pos[strategy][sym] += signed

            if pos.net_qty == 0:
                pos.strategy = strategy
                pos.structure_id = structure_id
                pos.tag = tag
        # -------- TRADE TYPE --------
        if prev_qty == 0 and new_qty != 0:
            trade_type = "ENTRY"
        elif prev_qty != 0 and new_qty == 0:
            trade_type = "EXIT"
        elif abs(new_qty) > abs(prev_qty):
            trade_type = "SCALE_IN"
        elif abs(new_qty) < abs(prev_qty):
            trade_type = "SCALE_OUT"
        elif prev_qty * new_qty < 0:
            trade_type = "REVERSAL"
        else:
            trade_type = "UNKNOWN"

        # -------- LOG --------
        if self.logger:
            row = {
                "candle_timestamp": (
                    candle_ts.isoformat()
                    if isinstance(candle_ts, datetime)
                    else candle_ts
                ),
                "execution_timestamp": datetime.now().isoformat(),
                "strategy": strategy,
                "symbol": sym,
                "trade_id": pos.trade_id,
                "trade_type": trade_type,
                "side": side,
                "qty": qty,
                "price": price,
                "net_qty_after": new_qty,
                "order_id": order_id,
                "intent_id": intent_id,
            }

            if trade_type == "EXIT":
                row["pnl"] = pos.realized_pnl
                row["mae"] = pos.mae
                row["mfe"] = pos.mfe

            self.logger.log(strategy=strategy, row=row)

    def has_open_structure(self, strategy: str, structure_id: str) -> bool:
        for pos in self.positions.values():
            if (
                pos.net_qty != 0
                and pos.strategy == strategy
                and pos.structure_id == structure_id
            ):
                return True
        return False

    # ---------------------
    # BROKER RECONCILIATION
    # ---------------------
    def reconcile_with_broker(self, broker_positions):
        """
        broker_positions format:
        {
            symbol: {
                "qty": int,
                "avg_price": float,
                "segment": str,
                "lot_size": int
            }
        }
        """

        with self._lock:
            self.last_recon_time = time.time()

            broker_symbols = set(broker_positions.keys())
            local_symbols = set(self.positions.keys())

            # 1) Sync broker → local
            for sym, bp in broker_positions.items():

                inst = Instrument(
                    symbol=sym,
                    segment=bp.get("segment", "EQ"),
                    lot_size=bp.get("lot_size", 1),
                )

                if sym not in self.positions:
                    # Ghost broker position
                    print(f"⚠ Ghost broker position detected: {sym}")

                    pos = Position(inst)
                    pos.net_qty = bp["qty"]
                    pos.avg_price = bp["avg_price"]

                    self.positions[sym] = pos
                    continue

                local = self.positions[sym]

                # Drift detection
                if (
                    local.net_qty != bp["qty"]
                    or abs(local.avg_price - bp["avg_price"]) > 0.5
                ):
                    print(f"⚠ Drift corrected: {sym}")

                    local.net_qty = bp["qty"]
                    local.avg_price = bp["avg_price"]
                    local.last_updated = time.time()

                if abs(local.net_qty - bp["qty"]) > threshold:
                    self.trading_paused = True

            # 2) Remove ghost locals
            for sym in local_symbols - broker_symbols:
                local = self.positions[sym]

                if local.net_qty != 0:
                    print(f"⚠ Ghost local removed: {sym}")

                self.positions.pop(sym)

    # ---------------------
    # POSITION CHECKS
    # ---------------------
    def get_qty(self, symbol):
        pos = self.positions.get(symbol)
        return pos.net_qty if pos else 0

    def is_long(self, symbol):
        return self.get_qty(symbol) > 0

    def is_short(self, symbol):
        return self.get_qty(symbol) < 0

    def is_flat(self, symbol):
        return self.get_qty(symbol) == 0

    # ---------------------
    # PnL
    # ---------------------
    def unrealized_pnl(self, symbol, ltp):
        pos = self.positions.get(symbol)
        if not pos or pos.net_qty == 0:
            return 0

        diff = ltp - pos.avg_price

        if pos.net_qty < 0:
            diff *= -1

        return diff * abs(pos.net_qty) * pos.instrument.lot_size

    def realized_pnl(self, symbol):
        pos = self.positions.get(symbol)
        return pos.realized_pnl if pos else 0

    # ---------------------
    # EXPOSURE
    # ---------------------
    def total_exposure(self, price_map):
        total = 0

        for sym, pos in self.positions.items():
            ltp = price_map.get(sym, pos.avg_price)

            total += abs(pos.net_qty) * ltp * pos.instrument["SEM_LOT_UNITS"]

        return total

    # ---------------------
    # SNAPSHOT
    # ---------------------
    def snapshot(self):
        snap = {}

        for sym, pos in self.positions.items():
            snap[sym] = {
                "segment": pos.instrument.segment,
                "qty": pos.net_qty,
                "avg_price": pos.avg_price,
                "realized_pnl": pos.realized_pnl,
            }

        return snap

    def get_open_positions(self, symbol=None, strategy=None):
        """
        Returns Position objects (internal truth)
        """
        positions = []

        for sym, pos in self.positions.items():
            if pos.net_qty == 0:
                continue

            if symbol and sym != symbol:
                continue

            if strategy:
                if self.strategy_pos[strategy][sym] == 0:
                    continue

            positions.append(pos)

        return positions
