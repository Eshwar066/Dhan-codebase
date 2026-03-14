import logging
import threading
import time
from collections import defaultdict
from logs.logger.trade_logger import TradeLogger
from datetime import datetime
import uuid
import pdb
from core.utils.instruments.instrument_store import Instrument

logger = logging.getLogger(__name__)

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
# POSITION
# =========================
class Position:
    def __init__(self, instrument):
        self.instrument = instrument
        self.net_qty = 0
        self.avg_price = 0.0
        self.realized_pnl = 0.0
        self.cumulative_pnl = 0.0

        self.trade_id = None
        self.entry_price = None
        self.entry_time = None

        self.mae = 0.0
        self.mfe = 0.0

        self.strategy = None
        self.structure_id = None
        self.tag = None
        self.on_structure_exit = None

        self.last_updated = time.time()

    def __repr__(self):
        sym = (
            self.instrument.symbol
            if hasattr(self.instrument, "symbol")
            else str(self.instrument)
        )
        return f"<Position symbol={sym} qty={self.net_qty} avg={self.avg_price}>"

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
            self.realized_pnl = pnl
            self.cumulative_pnl += pnl

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

        # All Positions, using symbol
        self.positions = {}

        # strategy → symbol → qty  #strategy wise positions
        self.strategy_pos = defaultdict(lambda: defaultdict(int))

        self.last_recon_time = 0
        self.trading_paused = False
        # Set by engine: strategy.on_structure_exit (BacktestEngine/LiveEngine)
        self.on_structure_exit = None

    # ---------------------
    # LOCAL FILL UPDATE
    # ---------------------

    def on_fill(
        self,
        instrument: Instrument,
        side,
        qty,
        price,
        intent_id=None,
        order_id=None,
        strategy=None,
        structure_id=None,
        tag=None,
        candle_ts=None,
        action=None,
    ):
        assert isinstance(instrument, Instrument), "on_fill expects Instrument"
        assert instrument.trading_symbol, "Instrument must have trading_symbol"
        assert instrument.custom_symbol, "Instrument must have custom_symbol"
        if not isinstance(instrument, Instrument):
            raise TypeError(f"on_fill expects Instrument, got {type(instrument)}")

        with self._lock:
            sym = instrument.trading_symbol
            lot_size = instrument.lot_size

            prev_qty = self.positions[sym].net_qty if sym in self.positions else 0

            if sym not in self.positions:
                self.positions[sym] = Position(instrument=instrument)

            pos = self.positions[sym]
            pos.update_fill(side, qty, price)

            new_qty = pos.net_qty

            # 🔔 STRUCTURE EXIT HOOK (ONLY ON FULL MAIN EXIT) # used to remove state of rollover ids on full exit of position
            if prev_qty != 0 and new_qty == 0 and pos.tag == "MAIN":
                if callable(self.on_structure_exit):
                    self.on_structure_exit(
                        strategy=strategy,
                        structure_id=pos.structure_id,
                        instrument=instrument,
                        candle_ts=candle_ts,
                    )

            if strategy:
                signed = qty if side == "BUY" else -qty
                self.strategy_pos[strategy][sym] += signed

            if prev_qty == 0 and new_qty != 0:
                pos.intent_id = intent_id
            # Always update strategy/structure_id/tag when provided (so positions get strategy name from fills)
            if strategy is not None:
                pos.strategy = strategy
            if structure_id is not None:
                pos.structure_id = structure_id
            if tag is not None:
                pos.tag = tag

            if action == "ENTRY" and prev_qty != 0:
                raise RuntimeError(
                    f"ENTRY received for open position {sym}. Use SCALE_IN."
                )

            # -------- TRADE TYPE --------
            if action:
                trade_type = action
            else:
                # fallback only if action is missing (should not happen)
                if prev_qty == 0 and new_qty != 0:
                    trade_type = "ENTRY"
                elif prev_qty != 0 and new_qty == 0:
                    trade_type = "EXIT"
                else:
                    trade_type = "UNKNOWN"

            # -------- LOG --------
            if self.logger:
                # PnL only on EXIT; leave blank on ENTRY/SCALE_IN
                pnl_val = pos.realized_pnl if trade_type == "EXIT" else ""
                cumulative_val = pos.cumulative_pnl if trade_type == "EXIT" else ""
                row = {
                    "candle_timestamp": (
                        candle_ts.strftime("%Y-%m-%d %H:%M")
                        if isinstance(candle_ts, datetime)
                        else candle_ts
                    ),
                    "tag": tag,
                    "symbol": sym,
                    "trade_type": trade_type,
                    "side": side,
                    "qty": qty,
                    "price": price,
                    "pnl": pnl_val,
                    "cumulative_pnl": cumulative_val,
                    "net_qty_after": new_qty,
                    # "order_id": order_id,
                    # "intent_id": intent_id,
                    # "trade_id": pos.trade_id,
                    # "execution_timestamp": datetime.now().isoformat(),
                    # "strategy": strategy,
                }

                if trade_type == "EXIT":
                    row["mae"] = pos.mae
                    row["mfe"] = pos.mfe

                    # Log complete trade for performance analytics (trade log)
                    entry_time_str = (
                        datetime.fromtimestamp(pos.entry_time).strftime(
                            "%Y-%m-%d %H:%M:%S"
                        )
                        if pos.entry_time is not None
                        else ""
                    )
                    exit_time_str = (
                        candle_ts.strftime("%Y-%m-%d %H:%M:%S")
                        if candle_ts is not None and isinstance(candle_ts, datetime)
                        else datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    )
                    # Entry side: long position was entered with BUY, short with SELL
                    entry_side = "BUY" if prev_qty > 0 else "SELL"
                    trade_row = {
                        "trade_id": pos.trade_id,
                        "entry_time": entry_time_str,
                        "exit_time": exit_time_str,
                        "side": entry_side,
                        "entry_price": pos.entry_price,
                        "exit_price": price,
                        "qty": qty,
                        "pnl": pos.realized_pnl,
                        "symbol": sym,
                        "strategy": strategy or "GLOBAL",
                    }
                    self.logger.log_trade(trade_row)

                self.logger.log(strategy=strategy, row=row)

            position_closed = prev_qty != 0 and new_qty == 0
            realized_pnl_for_risk = pos.realized_pnl if position_closed else 0.0
            return (position_closed, realized_pnl_for_risk)

    def has_open_structure(self, strategy: str, structure_id: str, tag: str) -> bool:
        for pos in self.positions.values():
            if (
                pos.net_qty != 0
                and pos.strategy == strategy
                and pos.structure_id == structure_id
                and pos.tag == tag
            ):
                return True
        return False

    # Used while exiting positions
    def get_hedge_for(self, main_position):
        """
        Find hedge position linked to a main position.
        Matching is done via:
        - same strategy
        - same structure_id
        - tag == 'HEDGE'
        """
        for pos in self.positions.values():
            # pdb.set_trace()
            if pos.net_qty == 0:
                continue

            if pos.tag != "HEDGE":
                continue

            if pos.strategy != main_position.strategy:
                continue

            if pos.structure_id != main_position.structure_id:
                continue

            return pos

        return None

    # ---------------------
    # BROKER RECONCILIATION
    # ---------------------
    def reconcile_with_broker(
        self, broker_positions, drift_threshold: int = 0, strategy: str = None
    ):
        """
        Sync PositionManager to broker truth.
        broker_positions: { symbol: { "qty": int, "avg_price": float, "segment": str, "lot_size": int } }
        drift_threshold: if |local_qty - broker_qty| > this, set trading_paused.
        strategy: strategy name to associate with newly discovered positions.
        """
        with self._lock:
            self.last_recon_time = time.time()
            broker_symbols = set(broker_positions.keys())
            local_symbols = set(self.positions.keys())

            for sym, bp in broker_positions.items():
                segment = bp.get("segment", "EQ")
                lot_size = int(bp.get("lot_size", 1))
                inst = Instrument(
                    trading_symbol=sym,
                    custom_symbol=sym,
                    exchange=bp.get("exchange", ""),
                    segment=segment,
                    instrument_type=bp.get("instrument_type", "EQ"),
                    lot_size=lot_size,
                )

                if sym not in self.positions:
                    pos = Position(inst)
                    pos.net_qty = int(bp["qty"])
                    pos.avg_price = float(bp.get("avg_price", 0))
                    if strategy:
                        pos.strategy = strategy
                    self.positions[sym] = pos
                    continue

                local = self.positions[sym]
                if (
                    local.net_qty != int(bp["qty"])
                    or abs(local.avg_price - float(bp.get("avg_price", 0))) > 0.5
                ):
                    local.net_qty = int(bp["qty"])
                    local.avg_price = float(bp.get("avg_price", 0))
                    local.last_updated = time.time()
                if abs(local.net_qty - int(bp["qty"])) > drift_threshold:
                    self.trading_paused = True
                    logger.warning(
                        "Position drift above threshold: %s local_qty=%s broker_qty=%s threshold=%s",
                        sym,
                        local.net_qty,
                        bp.get("qty"),
                        drift_threshold,
                    )

            for sym in local_symbols - broker_symbols:
                self.positions.pop(sym, None)

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

            total += abs(pos.net_qty) * ltp * pos.instrument.lot_size

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

    def get_open_positions(self, underlying=None, strategy=None):
        positions = []
        for pos in self.positions.values():
            if pos.net_qty == 0:
                continue

            if strategy and pos.strategy != strategy:
                continue

            if underlying:
                # Match by trading_symbol (position key) so backtest symbol matches; fallback to custom_symbol
                inst = pos.instrument
                by_trading = (inst.trading_symbol or "").strip() == (
                    underlying or ""
                ).strip()
                by_custom = False
                if getattr(inst, "custom_symbol", None):
                    parts = (inst.custom_symbol or "").strip().split()
                    by_custom = (parts[0] == underlying.strip()) if parts else False
                if not (by_trading or by_custom):
                    continue

            positions.append(pos)

        return positions
