import logging
import os
import threading
import time
from collections import defaultdict
from typing import Any, Dict, Optional

import pandas as pd
from utils.logger.trade_logger import TradeLogger
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import uuid
from core.utils.instruments.instrument_store import Instrument

logger = logging.getLogger(__name__)

IST = ZoneInfo("Asia/Kolkata")


def _fill_clock_for_trade_log(fill_ts: Any) -> Optional[datetime]:
    """
    Normalize bar/fill time to **IST naive** for trade_log CSV display.

    Naive inputs are interpreted as UTC because the engine canonicalizes
    ``candle['timestamp']`` to naive UTC (see ``_normalize_candle_timestamp_utc_naive``).
    """
    if fill_ts is None:
        return None
    try:
        ts = pd.Timestamp(fill_ts)
    except (TypeError, ValueError):
        return None
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    return ts.tz_convert("Asia/Kolkata").tz_localize(None).to_pydatetime()

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
        # Backtest / bar clock for trade_log (when set, overrides wall-clock entry_time in CSV)
        self.entry_clock: Optional[datetime] = None

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

    def update_fill(self, side, qty, price, fill_ts=None):
        signed_qty = qty if side == "BUY" else -qty

        # -------- ENTRY --------
        if self.net_qty == 0:
            self.trade_id = f"T-{uuid.uuid4().hex[:10]}"
            self.entry_price = price
            if fill_ts is not None:
                self.entry_clock = _fill_clock_for_trade_log(fill_ts)
                try:
                    self.entry_time = float(pd.Timestamp(fill_ts).timestamp())
                except (TypeError, ValueError):
                    self.entry_time = time.time()
            else:
                # REST / broker fills often omit candle_ts — still stamp wall clock so
                # trade_log rows always have entry_time.
                self.entry_time = time.time()
                self.entry_clock = _fill_clock_for_trade_log(
                    datetime.now(tz=timezone.utc)
                )
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
        try:
            missing_candle_ts = candle_ts is None or bool(pd.isna(candle_ts))
        except (TypeError, ValueError):
            missing_candle_ts = candle_ts is None
        if missing_candle_ts:
            # REST fills can carry pandas.NaT. Hooks require a real timestamp for
            # slot keys, expiry selection, and deferred/re-entry intent creation.
            candle_ts = datetime.now(timezone.utc)

        hook_main_entry = None
        hook_main_exit = None
        with self._lock:
            sym = instrument.trading_symbol
            lot_size = instrument.lot_size

            prev_qty = self.positions[sym].net_qty if sym in self.positions else 0

            if sym not in self.positions:
                self.positions[sym] = Position(instrument=instrument)

            pos = self.positions[sym]
            pos.update_fill(side, qty, price, fill_ts=candle_ts)

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
                        exit_reason=exit_reason,
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

            _pm_meta_snapshot = None
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
                # Snapshot before pop — trade_log needs entry context on flat.
                _pm_meta_snapshot = (self.position_metadata.get(sym) or {}).get(
                    "strategy_meta"
                )
                if _pm_meta_snapshot is None and isinstance(metadata_extras, dict):
                    _pm_meta_snapshot = metadata_extras
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
                # PnL only on EXIT / broker FORCE_EXIT (SL); leave blank on ENTRY/SCALE_IN
                _exit_like = trade_type in ("EXIT", "FORCE_EXIT")
                pnl_val = pos.realized_pnl if _exit_like else ""
                cumulative_val = pos.cumulative_pnl if _exit_like else ""
                # CSV timestamps are rendered in IST (naive UTC inputs are converted).
                # Fallback to wall clock so REST fills without candle_ts still stamp a time.
                candle_ts_eff = candle_ts
                if candle_ts_eff is None:
                    candle_ts_eff = datetime.now(tz=timezone.utc)
                candle_ts_ist = _fill_clock_for_trade_log(candle_ts_eff)
                ts_str = (
                    candle_ts_ist.strftime("%Y-%m-%d %H:%M")
                    if candle_ts_ist is not None
                    else ""
                )
                row = {
                    "candle_timestamp": ts_str,
                    "tag": tag or "",
                    "symbol": sym,
                    "trade_type": trade_type,
                    "side": side,
                    "qty": qty,
                    "price": price,
                    "pnl": pnl_val,
                    "cumulative_pnl": cumulative_val,
                    "net_qty_after": new_qty,
                    "execution_source": execution_source or "",
                    # Always present so ENTRY/EXIT share one fixed TRADES_COLUMNS schema.
                    "mae": pos.mae if _exit_like else "",
                    "mfe": pos.mfe if _exit_like else "",
                    "exit_reason": (
                        (getattr(pos, "exit_reason", None) or "") if _exit_like else ""
                    ),
                }

                if _exit_like:
                    # Ensure identity fields exist even for positions adopted via reconcile.
                    if not getattr(pos, "trade_id", None):
                        pos.trade_id = f"T-{uuid.uuid4().hex[:10]}"
                    if getattr(pos, "entry_clock", None) is not None:
                        # entry_clock is already IST-naive (see _fill_clock_for_trade_log)
                        entry_time_str = pos.entry_clock.strftime("%Y-%m-%d %H:%M:%S")
                    elif pos.entry_time is not None:
                        entry_time_str = (
                            datetime.fromtimestamp(pos.entry_time, tz=timezone.utc)
                            .astimezone(IST)
                            .replace(tzinfo=None)
                            .strftime("%Y-%m-%d %H:%M:%S")
                        )
                    else:
                        entry_time_str = ""
                    if candle_ts_ist is not None:
                        exit_time_str = candle_ts_ist.strftime("%Y-%m-%d %H:%M:%S")
                    else:
                        exit_time_str = (
                            datetime.now(tz=timezone.utc)
                            .astimezone(IST)
                            .replace(tzinfo=None)
                            .strftime("%Y-%m-%d %H:%M:%S")
                        )
                    # Entry side: long position was entered with BUY, short with SELL
                    entry_side = "BUY" if prev_qty > 0 else "SELL"
                    entry_price_for_log = pos.entry_price
                    collected_points = ""
                    if entry_price_for_log is not None:
                        try:
                            collected_points = float(entry_price_for_log) - float(price)
                        except (TypeError, ValueError):
                            collected_points = ""
                    else:
                        logger.warning(
                            "Missing entry_price on exit fill; collected_points left blank for %s",
                            sym,
                        )

                    trade_row = {
                        "trade_id": pos.trade_id,
                        "entry_time": entry_time_str,
                        "exit_time": exit_time_str,
                        "side": entry_side,
                        "entry_price": entry_price_for_log
                        if entry_price_for_log is not None
                        else "",
                        "exit_price": price,
                        "qty": qty,
                        "pnl": pos.realized_pnl,
                        "collected_points": collected_points,
                        "symbol": sym,
                        "strategy": strategy or "GLOBAL",
                        "exit_reason": getattr(pos, "exit_reason", None) or "",
                        "execution_source": execution_source or "",
                    }
                    # Optional entry context from strategy_meta (LiquiditySweep etc.)
                    _pm_meta = _pm_meta_snapshot
                    if _pm_meta is None:
                        _pm_meta = (self.position_metadata.get(sym) or {}).get(
                            "strategy_meta"
                        )
                    if isinstance(_pm_meta, dict):
                        ls = _pm_meta.get("liquidity_sweep")
                        ctx_src = ls if isinstance(ls, dict) else _pm_meta
                        if isinstance(ctx_src, dict):
                            for _k in (
                                "swept_level",
                                "zone_side",
                                "zone_source",
                                "zone_bar_key",
                                "sweep_bar_key",
                            ):
                                if _k in ctx_src and ctx_src.get(_k) is not None:
                                    trade_row[_k] = ctx_src.get(_k)
                            # Prefer explicit aliases from liquidity_sweep payload
                            if isinstance(ls, dict):
                                if ls.get("zone_price") is not None:
                                    trade_row["swept_level"] = ls.get("zone_price")
                                for _k in (
                                    "zone_side",
                                    "zone_source",
                                    "zone_bar_key",
                                    "sweep_bar_key",
                                ):
                                    if ls.get(_k) is not None:
                                        trade_row[_k] = ls.get(_k)
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
            tag_u = str(tag or "").upper()
            act_exit = str(action or "").upper() in ("EXIT", "FORCE_EXIT")
            if prev_qty != 0 and act_exit and tag_u in (
                "MAIN_EXIT",
                "MAIN_SL",
                "MAIN_TARGET",
            ):
                # Full close, or partial MAIN_TARGET book (trail remainder stays open).
                if new_qty == 0 or tag_u == "MAIN_TARGET":
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
                    if new_qty != 0 and tag_u == "MAIN_TARGET":
                        pos.tag = "MAIN"

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
        """Best-effort: ENTRY rows in store (FILLED or pending GTT) → position_metadata by symbol."""
        if intent_store is None:
            return
        try:
            from core.orderExecution.intent_store import IntentStatus
        except ImportError:
            return

        best = {}  # sym -> (rank, updated_at, meta dict); rank 0=FILLED, 1=SENT
        for intent_id, rec in intent_store.intents.items():
            st = rec.get("status")
            is_filled = st == IntentStatus.FILLED or getattr(st, "value", st) == "FILLED"
            is_sent = st == IntentStatus.SENT or getattr(st, "value", st) == "SENT"
            is_validated = (
                st == IntentStatus.VALIDATED or getattr(st, "value", st) == "VALIDATED"
            )
            if not is_filled and not is_sent and not is_validated:
                continue
            payload = rec.get("payload") or {}
            if (rec.get("action") or payload.get("action") or "") != "ENTRY":
                continue
            tag = str(rec.get("tag") or payload.get("tag") or "MAIN").upper()
            if tag != "MAIN":
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
            rank = 0 if is_filled else 1
            upd = float(rec.get("updated_at") or rec.get("created_at") or 0)
            prev = best.get(sym)
            if prev is None or rank < prev[0] or (rank == prev[0] and upd >= prev[1]):
                best[sym] = (rank, upd, meta)

        with self._lock:
            for sym, (_rank, _t, meta) in best.items():
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

    @staticmethod
    def symbol_underlying_root(trading_symbol: str) -> str:
        """Best-effort underlying root (BANKNIFTY before NIFTY)."""
        compact = "".join(
            ch for ch in str(trading_symbol or "").upper() if ch.isalnum()
        )
        if compact.startswith("BANKNIFTY"):
            return "BANKNIFTY"
        if compact.startswith("FINNIFTY"):
            return "FINNIFTY"
        if compact.startswith("MIDCPNIFTY"):
            return "MIDCPNIFTY"
        if compact.startswith("NIFTY"):
            return "NIFTY"
        if compact.startswith("SENSEX"):
            return "SENSEX"
        if compact.startswith("BANKEX"):
            return "BANKEX"
        return ""

    # Strategy CSV / reconcile claim domains. Prevents e.g. BankNiftyBTST from
    # adopting bare NIFTY LEAPS legs after ownership metadata was lost.
    _STRATEGY_CLAIM_UNDERLYINGS: Dict[str, tuple] = {
        "BankNiftyBTST": ("BANKNIFTY",),
        "LEAPS_RSI": ("NIFTY",),
        "NiftySMA9Weekly": ("NIFTY",),
        "NiftyIntradayMagicalLine": ("NIFTY",),
    }

    @classmethod
    def strategy_may_claim_symbol(cls, strategy: Optional[str], trading_symbol: str) -> bool:
        strat = str(strategy or "").strip()
        if not strat:
            return False
        allowed = cls._STRATEGY_CLAIM_UNDERLYINGS.get(strat)
        if not allowed:
            return True
        root = cls.symbol_underlying_root(trading_symbol)
        return bool(root) and root in allowed

    @classmethod
    def _ownership_row_compatible_with_folder(
        cls, folder_name: str, trading_symbol: str, meta: dict
    ) -> bool:
        """Drop poisoned rows (e.g. NIFTY PE parked under BankNiftyBTST CSV)."""
        folder = str(folder_name or "").strip()
        strat = str((meta or {}).get("strategy") or "").strip()
        if strat and folder and strat != folder:
            # Strategy-named folders must not contribute another strategy's rows.
            if folder in cls._STRATEGY_CLAIM_UNDERLYINGS or strat in cls._STRATEGY_CLAIM_UNDERLYINGS:
                return False
        claim_strat = strat or folder
        if claim_strat and not cls.strategy_may_claim_symbol(claim_strat, trading_symbol):
            return False
        return True

    def _merge_open_positions_csv_dict(
        self, file_meta: dict, *, protect_existing_strategy: bool = True
    ) -> None:
        for sym, meta in file_meta.items():
            if not meta:
                continue
            cur = dict(self.position_metadata.get(sym) or {})
            cur_strat = str(cur.get("strategy") or "").strip()
            incoming_strat = str(meta.get("strategy") or "").strip()
            if (
                protect_existing_strategy
                and cur_strat
                and incoming_strat
                and cur_strat != incoming_strat
            ):
                # Another strategy's CSV must not steal ownership.
                continue
            for k, v in meta.items():
                if v in (None, ""):
                    continue
                existing = cur.get(k)
                if (
                    protect_existing_strategy
                    and k in ("strategy", "structure_id", "tag", "intent_id")
                    and existing not in (None, "")
                    and str(existing) != str(v)
                    and cur_strat
                    and incoming_strat
                    and cur_strat != incoming_strat
                ):
                    continue
                cur[k] = v
            self.position_metadata[sym] = cur

    def merge_ownership_from_all_strategy_open_positions_csvs(
        self, *, engine_id: Optional[str] = None, logs_root: str = "logs"
    ) -> int:
        """
        Multi-strategy engines store ownership in logs/{strategy}/{engine_id}_open_positions.csv
        while PM's primary path is usually the primary strategy dir. Merge ownership from
        every strategy CSV that shares this engine_id so overnight legs keep strategy/tag.
        """
        try:
            from utils.logger.open_positions_logger import (
                load_position_metadata_from_csv,
            )
        except ImportError as exc:
            logger.warning("open_positions_logger import failed: %s", exc)
            return 0

        eid = str(
            engine_id
            or (os.path.basename(self.open_positions_csv_path or "").replace(
                "_open_positions.csv", ""
            ))
            or ""
        ).strip()
        if not eid:
            return 0
        root = logs_root
        if not os.path.isdir(root):
            return 0
        merged = 0
        for name in os.listdir(root):
            strat_dir = os.path.join(root, name)
            if not os.path.isdir(strat_dir):
                continue
            path = os.path.join(strat_dir, f"{eid}_open_positions.csv")
            if not os.path.isfile(path):
                continue
            if self.open_positions_csv_path and os.path.abspath(
                path
            ) == os.path.abspath(self.open_positions_csv_path):
                continue
            file_meta = load_position_metadata_from_csv(path)
            if not file_meta:
                continue
            filtered = {
                sym: meta
                for sym, meta in file_meta.items()
                if self._ownership_row_compatible_with_folder(name, sym, meta or {})
            }
            skipped = len(file_meta) - len(filtered)
            if skipped:
                logger.warning(
                    "Skipping %s incompatible ownership row(s) from %s",
                    skipped,
                    path,
                )
            if not filtered:
                continue
            self._merge_open_positions_csv_dict(filtered)
            merged += len(filtered)
        # Also re-apply ownership onto any already-open positions that lost meta.
        applied = 0
        with self._lock:
            for sym, pos in list(self.positions.items()):
                if int(getattr(pos, "net_qty", 0) or 0) == 0:
                    continue
                meta = self.position_metadata.get(sym) or {}
                if not meta:
                    continue
                changed = False
                if not getattr(pos, "strategy", None) and meta.get("strategy"):
                    pos.strategy = meta.get("strategy")
                    changed = True
                if not getattr(pos, "structure_id", None) and meta.get("structure_id"):
                    pos.structure_id = meta.get("structure_id")
                    changed = True
                if not getattr(pos, "tag", None) and meta.get("tag"):
                    pos.tag = meta.get("tag")
                    changed = True
                if not getattr(pos, "intent_id", None) and meta.get("intent_id"):
                    pos.intent_id = meta.get("intent_id")
                    changed = True
                if changed:
                    applied += 1
                    if pos.strategy:
                        self.strategy_pos[pos.strategy][sym] = int(pos.net_qty)
        if applied:
            logger.info(
                "Restored ownership on %s open position(s) from strategy CSVs (engine=%s)",
                applied,
                eid,
            )
        return applied

    def rebuild_position_metadata_from_open_positions_csv(self) -> None:
        """Merge metadata from logs/{engine_id}_open_positions.csv (strategy_meta, etc.)."""
        path = self.open_positions_csv_path
        if not path or not os.path.isfile(path):
            return
        try:
            from utils.logger.open_positions_logger import (
                load_position_metadata_from_csv,
            )
        except ImportError as exc:
            logger.warning("open_positions_logger import failed: %s", exc)
            return
        file_meta = load_position_metadata_from_csv(path)
        with self._lock:
            self._merge_open_positions_csv_dict(file_meta)

    def rebuild_open_positions_from_open_positions_csv(
        self,
        instrument_store: Any,
        *,
        exchange: str = "NSE",
    ) -> int:
        """
        After restart, restore open legs into PM from the open-positions CSV snapshot
        when PM is flat but the log still shows an OPEN row (typical PAPER restart).
        """
        path = self.open_positions_csv_path
        if not path or not instrument_store:
            return 0
        try:
            from utils.logger.open_positions_logger import (
                read_open_positions_snapshot,
            )
        except ImportError as exc:
            logger.warning("open_positions_logger import failed: %s", exc)
            return 0
        snap = read_open_positions_snapshot(path)
        if not snap:
            return 0
        restored = 0
        with self._lock:
            for sym, row in snap.items():
                try:
                    nq = int(float(row.get("net_qty") or 0))
                except (TypeError, ValueError):
                    continue
                if nq == 0:
                    continue
                cur = self.positions.get(sym)
                if cur is not None and int(cur.net_qty or 0) != 0:
                    continue
                opt_type, strike = self._extract_option_hint(
                    sym, row.get("structure_id")
                )
                inst = instrument_store.intent_creation_details(
                    sym, exchange, None, opt_type, strike
                )
                if inst is None:
                    logger.warning(
                        "CSV restore: cannot resolve instrument for %s (exchange=%s)",
                        sym,
                        exchange,
                    )
                    continue
                try:
                    avg = float(row.get("avg_price") or 0)
                except (TypeError, ValueError):
                    avg = 0.0
                pos = Position(inst)
                pos.net_qty = nq
                pos.avg_price = avg
                pos.entry_price = avg
                pos.strategy = (row.get("strategy") or "").strip() or None
                pos.tag = (row.get("tag") or "").strip() or "MAIN"
                pos.structure_id = (row.get("structure_id") or "").strip() or None
                pos.intent_id = (row.get("intent_id") or "").strip() or None
                self.positions[sym] = pos
                sm_raw = (row.get("strategy_meta") or "").strip()
                strategy_meta = None
                if sm_raw:
                    try:
                        import json

                        strategy_meta = json.loads(sm_raw)
                    except json.JSONDecodeError:
                        strategy_meta = None
                self._merge_position_metadata(
                    sym,
                    strategy=pos.strategy,
                    structure_id=pos.structure_id,
                    tag=pos.tag,
                    intent_id=pos.intent_id,
                    metadata_extras=strategy_meta,
                )
                if pos.strategy:
                    self.strategy_pos[pos.strategy][sym] = int(nq)
                if pos.structure_id and str(pos.tag or "").upper() == "MAIN":
                    d = self._structure_slices.setdefault(sym, {})
                    d[str(pos.structure_id)] = nq
                restored += 1
        if restored:
            logger.info(
                "Restored %s open position(s) from %s", restored, path
            )
        return restored

    @staticmethod
    def _extract_option_hint(
        trading_symbol: str, structure_id: Optional[str]
    ) -> tuple[Optional[str], Optional[int]]:
        """Best-effort parse of (option_type, strike) from structure_id / trading_symbol.

        Helps ``intent_creation_details`` resolve via _resolve_option_row_fallback
        when expiry/option_type/strike were not persisted in the CSV row.
        """
        opt: Optional[str] = None
        strike: Optional[int] = None
        sid = str(structure_id or "")
        if sid:
            parts = sid.split(":")
            if len(parts) >= 6 and parts[4].upper() in ("CE", "PE"):
                opt = parts[4].upper()
                try:
                    strike = int(parts[5])
                except (TypeError, ValueError):
                    strike = None
        if opt is None or strike is None:
            ts = str(trading_symbol or "").upper().strip()
            tokens = ts.replace("-", " ").split()
            for tok in tokens:
                if tok in ("CE", "PE", "CALL", "PUT"):
                    opt = "CE" if tok in ("CE", "CALL") else "PE"
                elif strike is None:
                    try:
                        val = int(tok)
                        if val >= 100:
                            strike = val
                    except (TypeError, ValueError):
                        continue
        return opt, strike

    def _detect_hedge_position(
        self,
        sym: str,
        pos: "Position",
        broker_positions: Dict[str, Any],
        strategy: Optional[str] = None,
    ) -> bool:
        """
        Detect if a position is a HEDGE leg based on structure characteristics.

        Hedge is a LONG option with:
        - Same underlying, expiry, option_type as MAIN (short)
        - Strike offset by hedge_distance_points (CE: +, PE: -) from MAIN
        - Positive qty (long)

        This fixes metadata for positions loaded from broker where CSV has wrong tag.
        """
        if pos.net_qty <= 0:  # Hedge must be long
            return False

        if not pos.instrument:
            return False

        hedge_strike = getattr(pos.instrument, "strike", None)
        option_type = getattr(pos.instrument, "option_type", "")
        hedge_expiry = getattr(pos.instrument, "expiry", None)

        if hedge_strike is None or not option_type or hedge_expiry is None:
            return False

        try:
            hedge_strike_f = float(hedge_strike)
        except (TypeError, ValueError):
            return False

        # Standard hedge distance (could be configurable)
        hedge_distance = 500
        # Calculate expected MAIN strike from hedge strike
        if option_type.upper() in ("CE", "CALL"):
            expected_main_strike = hedge_strike_f - hedge_distance
        else:
            expected_main_strike = hedge_strike_f + hedge_distance

        # Look for matching MAIN position (short) in broker positions
        for b_sym, bp in broker_positions.items():
            b_qty = int(bp.get("qty") or 0)
            if b_qty >= 0:  # MAIN must be short
                continue

            b_opt, b_strike = self._extract_option_hint(b_sym, None)
            if b_opt is None or b_strike is None:
                continue

            if b_opt.upper() != option_type.upper():
                continue

            # Check if broker position strike matches expected MAIN strike
            if abs(float(b_strike) - expected_main_strike) > 1:
                continue

            # Check expiry match
            b_expiry = bp.get("expiry") or bp.get("expiry_date")
            if b_expiry and str(b_expiry) != str(hedge_expiry):
                continue

            # Found matching MAIN - this is HEDGE
            return True

        return False

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

    def has_open_main_leg(
        self,
        strategy: str,
        *,
        underlying: Optional[str] = None,
        structure_id: Optional[str] = None,
    ) -> bool:
        """
        True if an open MAIN already blocks a new entry for this LEAPS leg family.

        Exact ``structure_id`` match always blocks. Otherwise:
        - mini (no ``:QTR`` suffix): any non-QTR MAIN on the underlying, or a
          short MAIN with missing ``structure_id`` after broker reconcile
        - quarterly (``:QTR``): any MAIN whose structure ends with ``:QTR``, or
          a short MAIN with missing ``structure_id`` (safe after restart)

        Also matches broker-adopted shorts with empty strategy/tag/structure_id
        (common when reconcile runs with ``strategy=None`` and no open-positions CSV).

        Long legs without structure_id are treated as hedges and ignored.
        """
        sid_want = str(structure_id or "").strip()
        want_qtr = sid_want.endswith(":QTR")
        strat = str(strategy or "").strip()
        if sid_want and self.has_open_structure(
            strategy=strat, structure_id=sid_want, tag="MAIN"
        ):
            return True

        und = str(underlying or "").strip().upper()
        # Include strategy-owned legs and unowned broker-adopted legs for this underlying.
        candidates = list(self.get_open_positions(underlying=und or None, strategy=strat or None))
        if und:
            seen = {id(p) for p in candidates}
            for pos in self.get_open_positions(underlying=und, strategy=None):
                if id(pos) in seen:
                    continue
                pos_strat = str(getattr(pos, "strategy", None) or "").strip()
                if pos_strat and pos_strat != strat:
                    continue
                candidates.append(pos)

        for pos in candidates:
            if int(getattr(pos, "net_qty", 0) or 0) == 0:
                continue
            tag_u = str(getattr(pos, "tag", None) or "").upper()
            if tag_u.startswith("HEDGE"):
                continue
            if tag_u and tag_u != "MAIN" and not tag_u.startswith("MAIN_"):
                continue

            sid = str(getattr(pos, "structure_id", None) or "").strip()
            if sid:
                pos_strat = str(getattr(pos, "strategy", None) or "").strip()
                if pos_strat and strat and pos_strat != strat:
                    continue
                if sid_want and sid == sid_want:
                    return True
                is_qtr = sid.endswith(":QTR")
                if want_qtr and is_qtr:
                    return True
                if not want_qtr and not is_qtr:
                    return True
                continue

            # Broker-reconciled MAIN often loses strategy/structure_id after restart.
            # Short option = MAIN sell; long without sid = likely mis-tagged hedge.
            if int(pos.net_qty) < 0:
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
    def _claim_strategy_for_symbol(
        self,
        sym: str,
        *,
        meta_strategy: Optional[str],
        strategy: Optional[str],
        claim_underlying: Optional[str] = None,
    ) -> Optional[str]:
        """Resolve ownership stamp for a broker-adopted / empty-strategy leg.

        ``strategy`` is only applied when the symbol is in that strategy's claim
        domain (and optional ``claim_underlying`` filter). Prevents BankNiftyBTST
        exit reconcile from tagging orphan NIFTY LEAPS legs.
        """
        if meta_strategy:
            return meta_strategy
        strat = str(strategy or "").strip() or None
        if not strat:
            return None
        if claim_underlying:
            root = self.symbol_underlying_root(sym)
            if root != str(claim_underlying).strip().upper():
                return None
        if not self.strategy_may_claim_symbol(strat, sym):
            return None
        return strat

    def reconcile_with_broker(
        self,
        broker_positions,
        drift_threshold: int = 0,
        strategy: str = None,
        *,
        claim_underlying: Optional[str] = None,
    ):
        """
        Sync PositionManager to broker truth.
        broker_positions: { symbol: { "qty": int, "avg_price": float, "segment": str, "lot_size": int } }
        drift_threshold: if |local_qty - broker_qty| > this, set trading_paused.
        strategy: strategy name to associate with newly discovered positions
            (only when the symbol is in that strategy's claim domain).
        claim_underlying: optional hard filter (e.g. ``BANKNIFTY``) for ``strategy``.
        """
        file_meta = None
        if self.open_positions_csv_path and os.path.isfile(
            self.open_positions_csv_path
        ):
            try:
                from utils.logger.open_positions_logger import (
                    load_position_metadata_from_csv,
                )

                file_meta = load_position_metadata_from_csv(
                    self.open_positions_csv_path
                )
            except ImportError as exc:
                logger.warning(
                    "open_positions_logger import failed during reconcile: %s",
                    exc,
                )
                file_meta = None

        with self._lock:
            if file_meta:
                self._merge_open_positions_csv_dict(file_meta)
            # Multi-strategy: ownership often lives under logs/{strategy}/…, not
            # the primary LEAPS csv path. Merge before adopting bare broker legs.
            pass
        # Outside lock: scans filesystem then takes its own lock to apply.
        try:
            self.merge_ownership_from_all_strategy_open_positions_csvs()
        except Exception as exc:
            logger.warning("strategy open-positions CSV ownership merge failed: %s", exc)

        with self._lock:
            self.last_recon_time = time.time()
            # Empty broker book: zero local qty but KEEP ownership metadata.
            # LiveEngine only clears metadata on empty books during NSE hours
            # (09:15–15:30). Outside that window an empty/ambiguous response must
            # not make the strategy forget an overnight carry.
            if not broker_positions:
                open_local = [
                    s
                    for s, p in self.positions.items()
                    if int(getattr(p, "net_qty", 0) or 0) != 0
                ]
                if open_local:
                    logger.warning(
                        "Reconcile: empty broker book with %s open local leg(s); "
                        "zeroing local qty (retaining ownership metadata)",
                        len(open_local),
                    )
                    for sym in open_local:
                        pos = self.positions.get(sym)
                        if pos is None:
                            continue
                        self._merge_position_metadata(
                            sym,
                            strategy=getattr(pos, "strategy", None),
                            structure_id=getattr(pos, "structure_id", None),
                            tag=getattr(pos, "tag", None),
                            intent_id=getattr(pos, "intent_id", None),
                        )
                        strategy = getattr(pos, "strategy", None)
                        self.positions.pop(sym, None)
                        if strategy and strategy in self.strategy_pos:
                            self.strategy_pos[strategy].pop(sym, None)
                    return

            from core.utils.expiry_resolver import ExpiryResolver

            def _identity(sym: str) -> str:
                return ExpiryResolver.option_identity_key(sym)

            # Remap broker keys onto local engine symbols when compact vs
            # space-separated Dhan names differ but strike/side match.
            remapped: Dict[str, Any] = {}
            local_by_id: Dict[str, str] = {}
            for loc_sym in self.positions.keys():
                ik = _identity(loc_sym)
                if ik and ik not in local_by_id:
                    local_by_id[ik] = loc_sym
            for meta_sym in list(self.position_metadata.keys()):
                ik = _identity(meta_sym)
                if ik and ik not in local_by_id:
                    local_by_id[ik] = meta_sym

            for b_sym, bp in broker_positions.items():
                engine_sym = b_sym
                ik = _identity(b_sym)
                if ik and ik in local_by_id:
                    engine_sym = local_by_id[ik]
                if engine_sym in remapped and engine_sym != b_sym:
                    # Prefer non-zero qty if both forms appear.
                    try:
                        if abs(int(bp.get("qty") or 0)) <= abs(
                            int(remapped[engine_sym].get("qty") or 0)
                        ):
                            continue
                    except (TypeError, ValueError):
                        pass
                remapped[engine_sym] = bp
            broker_positions = remapped

            broker_symbols = set(broker_positions.keys())
            # Also treat identity-matched broker symbols as present.
            broker_identities = {
                _identity(s) for s in broker_symbols if _identity(s)
            }
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
                claim_strategy = self._claim_strategy_for_symbol(
                    sym,
                    meta_strategy=meta_strategy,
                    strategy=strategy,
                    claim_underlying=claim_underlying,
                )

                if sym not in self.positions:
                    pos = Position(inst)
                    pos.net_qty = bqty
                    pos.avg_price = float(bp.get("avg_price", 0))
                    pos.strategy = claim_strategy
                    pos.tag = tag_m or ("MAIN" if claim_strategy else None)
                    pos.structure_id = structure_id_m
                    pos.intent_id = intent_id_m
                    # Adopted broker legs must still produce complete trade_log rows on exit.
                    if bqty != 0:
                        pos.trade_id = f"T-{uuid.uuid4().hex[:10]}"
                        pos.entry_price = float(bp.get("avg_price", 0) or 0) or None
                        pos.entry_time = time.time()
                        pos.entry_clock = _fill_clock_for_trade_log(
                            datetime.now(tz=timezone.utc)
                        )
                    self.positions[sym] = pos

                    # Detect hedge position and fix metadata if CSV was wrong
                    if (
                        pos.net_qty > 0
                        and claim_strategy
                        and self._detect_hedge_position(sym, pos, broker_positions, claim_strategy)
                    ):
                        pos.tag = "HEDGE"
                        # Find the MAIN position to get its structure_id
                        for b_sym, bp in broker_positions.items():
                            b_qty = int(bp.get("qty") or 0)
                            if b_qty >= 0:
                                continue
                            b_opt, b_strike = self._extract_option_hint(b_sym, None)
                            if b_opt and b_strike:
                                main_strike = getattr(pos.instrument, "strike", None)
                                try:
                                    if main_strike is not None and abs(float(b_strike) - float(main_strike)) < 1:
                                        # Found MAIN - use its structure_id if available
                                        b_meta = self.position_metadata.get(b_sym, {})
                                        if b_meta.get("structure_id"):
                                            pos.structure_id = b_meta["structure_id"]
                                            pos.intent_id = b_meta.get("intent_id")
                                        break
                                except (TypeError, ValueError):
                                    pass
                        # Update position_metadata with corrected hedge info
                        self._merge_position_metadata(
                            sym,
                            strategy=pos.strategy,
                            structure_id=pos.structure_id,
                            tag="HEDGE",
                            intent_id=pos.intent_id,
                        )
                        logger.info(
                            "Reconcile: detected HEDGE leg for %s, fixed tag/structure_id",
                            sym,
                        )

                    if pos.strategy:
                        self.strategy_pos[pos.strategy][sym] = int(bqty)
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
                    # Broker flat: keep ownership metadata (cleared only on fill CLOSE).
                    if int(bqty) == 0 and int(local.net_qty or 0) != 0:
                        self._merge_position_metadata(
                            sym,
                            strategy=getattr(local, "strategy", None),
                            structure_id=getattr(local, "structure_id", None),
                            tag=getattr(local, "tag", None),
                            intent_id=getattr(local, "intent_id", None),
                        )
                        logger.warning(
                            "Reconcile: broker flat for %s (was qty=%s); "
                            "zeroing local qty but retaining ownership metadata",
                            sym,
                            local.net_qty,
                        )
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
                    local.tag = tag_m or (
                        "MAIN" if (claim_strategy or local.strategy) else None
                    )
                if not getattr(local, "structure_id", None):
                    local.structure_id = structure_id_m
                if not getattr(local, "intent_id", None):
                    local.intent_id = intent_id_m
                if not getattr(local, "strategy", None):
                    local.strategy = claim_strategy
                if int(local.net_qty or 0) != 0:
                    if not getattr(local, "trade_id", None):
                        local.trade_id = f"T-{uuid.uuid4().hex[:10]}"
                    if getattr(local, "entry_price", None) is None:
                        local.entry_price = float(bp.get("avg_price", 0) or 0) or None
                    if getattr(local, "entry_time", None) is None:
                        local.entry_time = time.time()
                    if getattr(local, "entry_clock", None) is None:
                        local.entry_clock = _fill_clock_for_trade_log(
                            datetime.now(tz=timezone.utc)
                        )
                if getattr(local, "strategy", None):
                    self.strategy_pos[local.strategy][sym] = int(local.net_qty)

            # Broker book omitted this symbol (or transient API hole). Drop local qty
            # tracking but NEVER clear ownership metadata — that is only removed on
            # fill CLOSE (on_fill → position_metadata.pop). Otherwise a false flat
            # + SYNC rewrite permanently loses structure_id and allows duplicate entries.
            for sym in local_symbols - broker_symbols:
                if _identity(sym) and _identity(sym) in broker_identities:
                    continue
                pos = self.positions.get(sym)
                if pos is not None:
                    self._merge_position_metadata(
                        sym,
                        strategy=getattr(pos, "strategy", None),
                        structure_id=getattr(pos, "structure_id", None),
                        tag=getattr(pos, "tag", None),
                        intent_id=getattr(pos, "intent_id", None),
                    )
                    logger.warning(
                        "Reconcile: symbol %s absent from broker book "
                        "(local_qty=%s); removing local position but retaining "
                        "ownership metadata until fill close",
                        sym,
                        getattr(pos, "net_qty", None),
                    )
                self.positions.pop(sym, None)

    def sync_symbol_flat_at_broker(
        self, trading_symbol: str, *, reason: str = "", clear_metadata: bool = False
    ) -> bool:
        """
        Broker confirms no open position (manual exit / no_open_position).
        Drop local qty. When ``clear_metadata=True`` (confirmed manual close),
        also drop ownership metadata so restart will not re-arm SL / restore CSV ghosts.
        """
        sym = str(trading_symbol or "").strip()
        if not sym:
            return False
        with self._lock:
            pos = self.positions.get(sym)
            meta = dict(self.position_metadata.get(sym) or {})
            had_qty = pos is not None and int(getattr(pos, "net_qty", 0) or 0) != 0
            if not had_qty and not meta:
                return False
            if pos is not None and not clear_metadata:
                self._merge_position_metadata(
                    sym,
                    strategy=getattr(pos, "strategy", None),
                    structure_id=getattr(pos, "structure_id", None),
                    tag=getattr(pos, "tag", None),
                    intent_id=getattr(pos, "intent_id", None),
                )
            qty_was = int(getattr(pos, "net_qty", 0) or 0) if pos is not None else 0
            strategy = (
                getattr(pos, "strategy", None) if pos is not None else meta.get("strategy")
            )
            if pos is not None:
                self.positions.pop(sym, None)
            self._structure_slices.pop(sym, None)
            if strategy:
                self.strategy_pos[strategy][sym] = 0
            if clear_metadata:
                self.position_metadata.pop(sym, None)
                logger.warning(
                    "Reconcile: broker flat for %s (was qty=%s); "
                    "removed local position and cleared ownership metadata%s",
                    sym,
                    qty_was,
                    f" ({reason})" if reason else "",
                )
            else:
                logger.warning(
                    "Reconcile: broker flat for %s (was qty=%s); "
                    "removing local position but retaining ownership metadata%s",
                    sym,
                    qty_was,
                    f" ({reason})" if reason else "",
                )
            return True

    def clear_ownership_metadata(self, trading_symbol: str) -> Optional[Dict[str, Any]]:
        """Drop ownership metadata for ``trading_symbol``; return the prior bucket."""
        sym = str(trading_symbol or "").strip()
        if not sym:
            return None
        with self._lock:
            return self.position_metadata.pop(sym, None)

    def ownership_snapshot(self, trading_symbol: str) -> Dict[str, Any]:
        sym = str(trading_symbol or "").strip()
        if not sym:
            return {}
        with self._lock:
            out = dict(self.position_metadata.get(sym) or {})
            pos = self.positions.get(sym)
            if pos is not None:
                if not out.get("strategy"):
                    out["strategy"] = getattr(pos, "strategy", None)
                if not out.get("structure_id"):
                    out["structure_id"] = getattr(pos, "structure_id", None)
                if not out.get("tag"):
                    out["tag"] = getattr(pos, "tag", None)
                if not out.get("intent_id"):
                    out["intent_id"] = getattr(pos, "intent_id", None)
            return {k: v for k, v in out.items() if v not in (None, "")}

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
                underlying_norm = (underlying or "").strip().upper()
                trading_symbol = (inst.trading_symbol or "").strip()
                custom_symbol = (getattr(inst, "custom_symbol", None) or "").strip()
                trading_upper = trading_symbol.upper()
                custom_upper = custom_symbol.upper()

                # Exact match (existing behavior)
                by_trading = trading_upper == underlying_norm
                by_custom = False

                # Prefix match for India-style symbols:
                # e.g. "NIFTY 30 JAN 24000 CALL" should match underlying "NIFTY".
                # Dhan compact: "BANKNIFTY-Jul2026-59700-CE" (hyphen, not space).
                by_prefix = (
                    trading_upper.startswith(f"{underlying_norm} ")
                    or trading_upper.startswith(f"{underlying_norm}-")
                    or custom_upper.startswith(f"{underlying_norm} ")
                    or custom_upper.startswith(f"{underlying_norm}-")
                )

                # Handle option format: C-BTC-78000-270326 / P-BTC-...
                # Also Dhan: BANKNIFTY-Jul2026-59700-CE → underlying is parts[0].
                if "-" in custom_symbol:
                    parts = custom_symbol.split("-")
                    if len(parts) >= 2:
                        # Delta crypto: C-BTC-... / P-BTC-...
                        if parts[0].strip().upper() in {"C", "P"} and len(parts) >= 2:
                            underlying_from_symbol = parts[1].strip().upper()
                        else:
                            underlying_from_symbol = parts[0].strip().upper()
                        base_underlying = underlying_norm.replace("USD", "").strip()
                        by_custom = underlying_from_symbol in {
                            underlying_norm,
                            base_underlying,
                        }

                if not (by_trading or by_custom):
                    if not by_prefix:
                        continue

            positions.append(pos)

        return positions
