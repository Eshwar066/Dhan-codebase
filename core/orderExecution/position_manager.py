import logging
import os
import threading
import time
from collections import defaultdict
from logs.logger.trade_logger import TradeLogger
from datetime import datetime
import uuid
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
        self.intent_id = None
        self.on_structure_exit = None
        # Set when position is fully closed via a named path (e.g. LIQUIDATION)
        self.exit_reason = None

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
    def __init__(
        self,
        logger,
        open_positions_logger=None,
        open_positions_csv_path=None,
    ):
        self._lock = threading.Lock()
        self.logger = TradeLogger()
        self.open_positions_logger = open_positions_logger
        self.open_positions_csv_path = open_positions_csv_path

        # All Positions, using symbol
        self.positions = {}

        # strategy → symbol → qty  #strategy wise positions
        self.strategy_pos = defaultdict(lambda: defaultdict(int))

        self.last_recon_time = 0
        self.trading_paused = False
        # Set by engine: strategy.on_structure_exit (BacktestEngine/LiveEngine)
        self.on_structure_exit = None
        # Optional: liquidation / external fills (see OrderRouter._process_external_close_fill)
        self.on_forced_exit = None
        # Optional: engines wire these to place broker SL after MAIN entry fill and reversal entry after MAIN_EXIT fill.
        self.on_main_entry_fill = None
        self.on_main_exit_fill = None
        # Recent trade-led updates: skip broker qty overwrite briefly to avoid races with /v2/fills
        self._trade_led_symbol_ts = {}
        self._trade_led_baseline_qty = {}
        self._trade_led_grace_seconds = 6.0
        self._trade_led_extended_grace_seconds = 12.0
        # Partial liquidation bursts: debounce strategy on_forced_exit notifications
        self._forced_exit_partial_ts = {}
        self._forced_exit_debounce_seconds = 2.0
        # trading_symbol -> { strategy, structure_id, tag, intent_id, strategy_meta }
        self.position_metadata = {}
        # trading_symbol -> structure_id -> signed qty (MAIN ENTRY legs; EXIT w/ structure_id unwinds)
        self._structure_slices = defaultdict(dict)

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
        metadata_extras=None,
        exit_reason=None,
        execution_source=None,
    ):
        assert isinstance(instrument, Instrument), "on_fill expects Instrument"
        assert instrument.trading_symbol, "Instrument must have trading_symbol"
        assert instrument.custom_symbol, "Instrument must have custom_symbol"
        if not isinstance(instrument, Instrument):
            raise TypeError(f"on_fill expects Instrument, got {type(instrument)}")

        hook_main_entry = None
        hook_main_exit = None
        with self._lock:
            sym = instrument.trading_symbol
            lot_size = instrument.lot_size

            prev_qty = self.positions[sym].net_qty if sym in self.positions else 0

            if sym not in self.positions:
                self.positions[sym] = Position(instrument=instrument)

            pos = self.positions[sym]
            pos.update_fill(side, qty, price)

            new_qty = pos.net_qty
            if prev_qty == 0 and new_qty != 0:
                pos.exit_reason = None
            elif prev_qty != 0 and new_qty == 0 and exit_reason:
                pos.exit_reason = exit_reason

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

            # Always update strategy/structure_id/tag when provided (so positions get strategy name from fills)
            if strategy is not None:
                pos.strategy = strategy
            if structure_id is not None:
                pos.structure_id = structure_id
            if tag is not None:
                pos.tag = tag
            if (
                new_qty != 0
                and str(tag or "").upper() == "MAIN"
                and str(action or "").upper() == "ENTRY"
                and intent_id is not None
            ):
                pos.intent_id = intent_id

            if new_qty != 0:
                self._merge_position_metadata(
                    sym,
                    strategy=strategy,
                    structure_id=structure_id,
                    tag=tag,
                    intent_id=intent_id,
                    metadata_extras=metadata_extras,
                )
            else:
                self.position_metadata.pop(sym, None)

            act_u = str(action or "").upper()
            if new_qty == 0:
                self._structure_slices.pop(sym, None)
            elif structure_id and str(tag or "").upper() == "MAIN":
                iq = int(qty)
                signed = iq if side == "BUY" else -iq
                d = self._structure_slices.setdefault(sym, {})
                if act_u == "ENTRY":
                    d[str(structure_id)] = d.get(str(structure_id), 0) + signed
                elif act_u in ("EXIT", "FORCE_EXIT"):
                    sid = str(structure_id)
                    cur = d.get(sid, 0)
                    nxt = cur + signed
                    if nxt == 0:
                        d.pop(sid, None)
                    else:
                        d[sid] = nxt
                    if not d:
                        self._structure_slices.pop(sym, None)

            # -------- TRADE TYPE --------
            if action:
                au = str(action).upper()
                if au == "ENTRY" and prev_qty != 0 and new_qty != 0:
                    inc = qty if side == "BUY" else -qty
                    same_dir = (prev_qty > 0 and inc > 0) or (prev_qty < 0 and inc < 0)
                    trade_type = "SCALE_IN" if same_dir else action
                else:
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
                    "execution_source": execution_source or "",
                    # "order_id": order_id,
                    # "intent_id": intent_id,
                    # "trade_id": pos.trade_id,
                    # "execution_timestamp": datetime.now().isoformat(),
                    # "strategy": strategy,
                }

                if trade_type == "EXIT":
                    row["mae"] = pos.mae
                    row["mfe"] = pos.mfe
                    if getattr(pos, "exit_reason", None):
                        row["exit_reason"] = pos.exit_reason
                    if execution_source:
                        row["execution_source"] = execution_source

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
                        "exit_reason": getattr(pos, "exit_reason", None) or "",
                        "execution_source": execution_source or "",
                    }
                    self.logger.log_trade(trade_row)

                self.logger.log(strategy=strategy, row=row)

            if self.open_positions_logger is not None and prev_qty != new_qty:
                _pm = self.position_metadata.get(sym) or {}
                self.open_positions_logger.record_fill(
                    symbol=sym,
                    prev_qty=int(prev_qty),
                    new_qty=int(new_qty),
                    avg_price=float(pos.avg_price),
                    strategy=strategy,
                    structure_id=structure_id,
                    tag=tag,
                    intent_id=intent_id,
                    strategy_meta=_pm.get("strategy_meta"),
                )

            position_closed = prev_qty != 0 and new_qty == 0
            realized_pnl_for_risk = pos.realized_pnl if position_closed else 0.0

            if str(tag or "").upper() == "MAIN" and act_u == "ENTRY":
                inc = qty if side == "BUY" else -qty
                same_dir = (
                    prev_qty == 0
                    or (prev_qty > 0 and inc > 0)
                    or (prev_qty < 0 and inc < 0)
                )
                if same_dir:
                    hook_main_entry = {
                        "instrument": instrument,
                        "side": side,
                        "qty": qty,
                        "price": price,
                        "strategy": strategy,
                        "structure_id": structure_id,
                        "tag": tag,
                        "action": action,
                        "candle_ts": candle_ts,
                        "intent_id": intent_id,
                        "metadata_extras": metadata_extras,
                    }
            if prev_qty != 0 and new_qty == 0:
                if str(tag or "").upper() in ["MAIN_EXIT", "MAIN_SL"] and str(
                    action or ""
                ).upper() in ["EXIT", "FORCE_EXIT"]:
                    hook_main_exit = {
                        "instrument": instrument,
                        "side": side,
                        "qty": qty,
                        "price": price,
                        "strategy": strategy,
                        "structure_id": structure_id,
                        "tag": tag,
                        "action": action,
                        "candle_ts": candle_ts,
                        "intent_id": intent_id,
                        "metadata_extras": metadata_extras,
                    }

            result = (position_closed, realized_pnl_for_risk)

        if hook_main_entry and callable(getattr(self, "on_main_entry_fill", None)):
            try:
                self.on_main_entry_fill(**hook_main_entry)
            except Exception as e:
                if self.logger:
                    self.logger.log(
                        strategy=hook_main_entry.get("strategy"),
                        row={
                            "symbol": instrument.trading_symbol,
                            "trade_type": "HOOK_ERROR",
                            "side": "",
                            "qty": "",
                            "price": "",
                            "pnl": "",
                            "cumulative_pnl": "",
                            "net_qty_after": "",
                            "candle_timestamp": "",
                            "tag": "on_main_entry_fill",
                            "execution_source": str(e),
                        },
                    )
        if hook_main_exit and callable(getattr(self, "on_main_exit_fill", None)):
            try:
                self.on_main_exit_fill(**hook_main_exit)
            except Exception as e:
                if self.logger:
                    self.logger.log(
                        strategy=hook_main_exit.get("strategy"),
                        row={
                            "symbol": instrument.trading_symbol,
                            "trade_type": "HOOK_ERROR",
                            "side": "",
                            "qty": "",
                            "price": "",
                            "pnl": "",
                            "cumulative_pnl": "",
                            "net_qty_after": "",
                            "candle_timestamp": "",
                            "tag": "on_main_exit_fill",
                            "execution_source": str(e),
                        },
                    )
        return result

    def note_trade_led_fill(self, trading_symbol: str) -> None:
        """Mark symbol as recently updated from fills API; reconcile_with_broker skips overwrite briefly."""
        if not trading_symbol:
            return
        with self._lock:
            now = time.time()
            self._trade_led_symbol_ts[trading_symbol] = now
            pos = self.positions.get(trading_symbol)
            self._trade_led_baseline_qty[trading_symbol] = (
                int(pos.net_qty) if pos else 0
            )

    def should_emit_forced_exit(self, key: str, position_closed: bool) -> bool:
        """
        Debounce on_forced_exit for partial external/liquidation bursts; always emit on full close.
        """
        if not key:
            key = "_default"
        now = time.time()
        deb = float(getattr(self, "_forced_exit_debounce_seconds", 2.0))
        if position_closed:
            self._forced_exit_partial_ts.pop(key, None)
            return True
        last = self._forced_exit_partial_ts.get(key)
        if last is None or (now - last) >= deb:
            self._forced_exit_partial_ts[key] = now
            return True
        return False

    def _merge_position_metadata(
        self,
        sym: str,
        strategy=None,
        structure_id=None,
        tag=None,
        intent_id=None,
        metadata_extras=None,
    ) -> None:
        cur = dict(self.position_metadata.get(sym) or {})
        if strategy:
            cur["strategy"] = strategy
        if structure_id:
            cur["structure_id"] = structure_id
        if tag:
            cur["tag"] = tag
        if intent_id:
            cur["intent_id"] = intent_id
        if metadata_extras is not None:
            cur["strategy_meta"] = metadata_extras
        self.position_metadata[sym] = cur

    def get_position_metadata(self, trading_symbol: str):
        return self.position_metadata.get(trading_symbol)

    def rebuild_position_metadata_from_intent_store(self, intent_store) -> None:
        """Best-effort: FILLED ENTRY rows in store → position_metadata by instrument symbol."""
        if intent_store is None:
            return
        try:
            from core.orderExecution.intent_store import IntentStatus
        except ImportError:
            return

        best = {}  # sym -> (updated_at, meta dict)
        for intent_id, rec in intent_store.intents.items():
            st = rec.get("status")
            if st != IntentStatus.FILLED and getattr(st, "value", st) != "FILLED":
                continue
            payload = rec.get("payload") or {}
            if (rec.get("action") or payload.get("action") or "") != "ENTRY":
                continue
            inst = rec.get("instrument")
            sym = getattr(inst, "trading_symbol", None) or payload.get("symbol")
            if not sym:
                continue
            meta = {
                "tag": rec.get("tag") or payload.get("tag"),
                "structure_id": rec.get("structure_id") or payload.get("structure_id"),
                "intent_id": intent_id,
                "strategy": rec.get("strategy") or payload.get("strategy_id"),
                "strategy_meta": payload.get("strategy_meta"),
            }
            upd = float(rec.get("updated_at") or rec.get("created_at") or 0)
            prev = best.get(sym)
            if prev is None or upd >= prev[0]:
                best[sym] = (upd, meta)

        with self._lock:
            for sym, (_t, meta) in best.items():
                self.position_metadata[sym] = meta

    def get_structure_slice(self, trading_symbol: str, structure_id: str) -> int:
        if not trading_symbol or not structure_id:
            return 0
        with self._lock:
            return int(
                self._structure_slices.get(trading_symbol, {}).get(
                    str(structure_id), 0
                )
            )

    def has_structure_slice_open(self, trading_symbol: str, structure_id: str) -> bool:
        return self.get_structure_slice(trading_symbol, structure_id) != 0

    def rebuild_structure_slices_from_intent_store(self, intent_store) -> None:
        """Rebuild MAIN ENTRY slices from FILLED intents (intent-centric duplicate + risk guards)."""
        if intent_store is None:
            return
        try:
            from core.orderExecution.intent_store import IntentStatus
        except ImportError:
            return

        acc: dict = {}
        for intent_id, rec in intent_store.intents.items():
            st = rec.get("status")
            if st != IntentStatus.FILLED and getattr(st, "value", st) != "FILLED":
                continue
            payload = rec.get("payload") or {}
            if (rec.get("action") or payload.get("action") or "") != "ENTRY":
                continue
            tag = rec.get("tag") or payload.get("tag") or "MAIN"
            if str(tag).upper() != "MAIN":
                continue
            stid = rec.get("structure_id") or payload.get("structure_id")
            if not stid:
                continue
            inst = rec.get("instrument")
            sym = getattr(inst, "trading_symbol", None) if inst is not None else None
            if not sym and isinstance(inst, dict):
                sym = (
                    inst.get("trading_symbol")
                    or inst.get("tradingsymbol")
                    or inst.get("symbol")
                )
            if not sym:
                sym = payload.get("symbol")
            if not sym:
                continue
            side = (rec.get("side") or payload.get("side") or "").upper()
            try:
                q = int(rec.get("qty") or payload.get("qty") or 0)
            except (TypeError, ValueError):
                continue
            if q <= 0 or side not in ("BUY", "SELL"):
                continue
            signed = q if side == "BUY" else -q
            if sym not in acc:
                acc[sym] = {}
            skey = str(stid)
            acc[sym][skey] = acc[sym].get(skey, 0) + signed

        with self._lock:
            self._structure_slices.clear()
            for sym, slices in acc.items():
                self._structure_slices[sym] = dict(slices)

    def _merge_open_positions_csv_dict(self, file_meta: dict) -> None:
        for sym, meta in file_meta.items():
            cur = dict(self.position_metadata.get(sym) or {})
            for k, v in meta.items():
                if v not in (None, ""):
                    cur[k] = v
            self.position_metadata[sym] = cur

    def rebuild_position_metadata_from_open_positions_csv(self) -> None:
        """Merge metadata from logs/{engine_id}_open_positions.csv (strategy_meta, etc.)."""
        path = self.open_positions_csv_path
        if not path or not os.path.isfile(path):
            return
        try:
            from logs.logger.open_positions_logger import (
                load_position_metadata_from_csv,
            )
        except ImportError:
            return
        file_meta = load_position_metadata_from_csv(path)
        with self._lock:
            self._merge_open_positions_csv_dict(file_meta)

    def has_open_structure(self, strategy: str, structure_id: str, tag: str) -> bool:
        tag_u = str(tag or "").upper()
        sid = str(structure_id)
        for sym, pos in self.positions.items():
            if pos.net_qty == 0:
                continue
            if strategy and pos.strategy != strategy:
                continue
            if tag and str(pos.tag or "").upper() != tag_u:
                continue
            if self.get_structure_slice(sym, sid) != 0:
                return True
            if pos.structure_id is not None and str(pos.structure_id) == sid:
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
        file_meta = None
        if self.open_positions_csv_path and os.path.isfile(
            self.open_positions_csv_path
        ):
            try:
                from logs.logger.open_positions_logger import (
                    load_position_metadata_from_csv,
                )

                file_meta = load_position_metadata_from_csv(
                    self.open_positions_csv_path
                )
            except ImportError:
                file_meta = None

        with self._lock:
            if file_meta:
                self._merge_open_positions_csv_dict(file_meta)
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

                meta = self.position_metadata.get(sym, {}) or {}
                bqty = int(bp["qty"])
                if bqty != 0 and not meta:
                    logger.warning(
                        "Missing position metadata for %s during reconcile", sym
                    )

                tag_m = meta.get("tag")
                structure_id_m = meta.get("structure_id")
                intent_id_m = meta.get("intent_id")
                meta_strategy = meta.get("strategy")

                if sym not in self.positions:
                    pos = Position(inst)
                    pos.net_qty = bqty
                    pos.avg_price = float(bp.get("avg_price", 0))
                    pos.strategy = strategy or meta_strategy
                    pos.tag = tag_m
                    pos.structure_id = structure_id_m
                    pos.intent_id = intent_id_m
                    self.positions[sym] = pos
                    continue

                local = self.positions[sym]
                now = time.time()
                ts_led = self._trade_led_symbol_ts.get(sym)
                grace = float(getattr(self, "_trade_led_grace_seconds", 6.0))
                ext_grace = float(
                    getattr(self, "_trade_led_extended_grace_seconds", 12.0)
                )
                dt = (now - ts_led) if ts_led is not None else None
                soft_cap = (
                    max(2, int(drift_threshold)) if drift_threshold else 5
                )
                skip_qty_overwrite = False
                if ts_led is not None and dt is not None:
                    if dt < grace:
                        skip_qty_overwrite = True
                    elif dt < ext_grace:
                        if abs(int(local.net_qty) - int(bqty)) <= soft_cap:
                            skip_qty_overwrite = True
                if not skip_qty_overwrite and (
                    local.net_qty != bqty
                    or abs(local.avg_price - float(bp.get("avg_price", 0))) > 0.5
                ):
                    local.net_qty = bqty
                    local.avg_price = float(bp.get("avg_price", 0))
                    local.last_updated = time.time()
                if (
                    not skip_qty_overwrite
                    and abs(local.net_qty - bqty) > drift_threshold
                ):
                    self.trading_paused = True
                    logger.warning(
                        "Position drift above threshold: %s local_qty=%s broker_qty=%s threshold=%s",
                        sym,
                        local.net_qty,
                        bp.get("qty"),
                        drift_threshold,
                    )

                if not getattr(local, "tag", None):
                    local.tag = tag_m
                if not getattr(local, "structure_id", None):
                    local.structure_id = structure_id_m
                if not getattr(local, "intent_id", None):
                    local.intent_id = intent_id_m
                if not getattr(local, "strategy", None):
                    local.strategy = strategy or meta_strategy

            for sym in local_symbols - broker_symbols:
                self.positions.pop(sym, None)
                self.position_metadata.pop(sym, None)

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
            # print(">>positions Manager", self.positions, underlying, strategy)

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
                    symbol = (inst.custom_symbol or "").strip()

                    # Handle option format: C-BTC-78000-270326 / P-BTC-...
                    if "-" in symbol:
                        parts = symbol.split("-")
                        if len(parts) >= 2:
                            underlying_from_symbol = parts[1]  # BTC

                            # Compare with passed underlying (BTCUSD → BTC)
                            base_underlying = (
                                (underlying or "").replace("USD", "").strip()
                            )

                            by_custom = underlying_from_symbol == base_underlying
                if not (by_trading or by_custom):
                    continue

            positions.append(pos)

        return positions
