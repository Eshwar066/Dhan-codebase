import json
import logging
import time
import uuid
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Set, Tuple, Union

# Trade-led OMS: positions are updated only from trade events (fills), not from order state.

import pdb
import datetime

logger = logging.getLogger(__name__)

try:
    from core.utils.json_numeric import round_json_floats
except ImportError:
    round_json_floats = None  # type: ignore

from core.broker.internal.dhan.mappings import dhan_correlation_id, format_broker_failure_for_log
from core.orderExecution.bracket_orders import BRACKET_TAGS, BracketLegRegistry
from core.orderExecution.gtt_fallback_book import GttFallbackBook, GttFallbackWatch
from core.orderExecution.reentry_at_cost_book import ReentryAtCostBook
from core.orderExecution.intent_store import IntentStatus, IntentStore
from core.models.order_intent import OrderIntent


class OrderState(str, Enum):
    """
    Local order state cache. Reconciliation only corrects drift; broker calls
    (find_order_by_client_id) are used only when we don't already have terminal state.
    """

    NEW = "NEW"  # Intent created, not yet sent
    SENT = "SENT"  # Sent to broker, ack not confirmed
    OPEN = "OPEN"  # Seen on broker open list (or acked)
    PARTIAL = "PARTIAL"  # Partially filled
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


# Terminal states: no need to poll broker for these
_TERMINAL_ORDER_STATES: Set[OrderState] = {
    OrderState.FILLED,
    OrderState.CANCELLED,
    OrderState.REJECTED,
    OrderState.EXPIRED,
}


class OrderRouter:
    def __init__(
        self,
        risk_manager,
        broker,
        intent_store,
        position_manager=None,
        slippage_model=None,
        engine_logger=None,
        instrument_store=None,  # Added for symbol resolution during adoption
        circuit_breaker_threshold: int = 5,
        slippage_threshold_pct: float = None,
        engine_id: Optional[str] = None,
        strategy_id: Optional[str] = None,
        known_strategies: Optional[Iterable[str]] = None,
        # Orphan fill sync (no intent match): ignore stale / pre-session broker rows
        max_orphan_fill_age_seconds: Optional[float] = 300,
        reject_orphan_fills_before_oms_session: bool = True,
        reject_orphan_fill_if_predates_position_open: bool = True,
    ):
        self.risk = risk_manager
        self.broker = broker
        self.intent_store = intent_store
        self.position_manager = position_manager
        self.slippage_model = slippage_model or (lambda price: price)
        self.engine_logger = engine_logger
        self.instrument_store = instrument_store
        self.circuit_breaker_threshold = circuit_breaker_threshold
        self.slippage_threshold_pct = slippage_threshold_pct
        self.engine_id = engine_id
        self.event_bus = None
        self.strategy_id = strategy_id
        self._known_strategies: List[str] = []
        seen_strats: Set[str] = set()
        for raw in [strategy_id, *(known_strategies or [])]:
            sid = str(raw or "").strip()
            if sid and sid not in seen_strats:
                seen_strats.add(sid)
                self._known_strategies.append(sid)
        self.max_orphan_fill_age_seconds = max_orphan_fill_age_seconds
        self.reject_orphan_fills_before_oms_session = (
            reject_orphan_fills_before_oms_session
        )
        self.reject_orphan_fill_if_predates_position_open = (
            reject_orphan_fill_if_predates_position_open
        )
        self._consecutive_failures = 0
        # Order state cache: intent_id -> OrderState. Persisted to logs/order_state_{engine_id}.json.
        self._order_state: Dict[str, OrderState] = {}
        self._order_state_log: List[Dict[str, Any]] = []
        self._order_state_log_max = 5000
        # Trade-led: only apply each trade once; positions = f(trades), not f(order state)
        self._processed_trade_ids: Set[str] = set()
        self._processed_trade_ids_max = 10000
        # Reconciliation guard for cumulative partial-fill handling:
        # intent_id -> last cumulative filled quantity already applied to PM.
        self._last_applied_filled_by_intent: Dict[str, float] = {}
        # Pending FORCE_EXIT watchdog threshold (seconds).
        self._force_exit_pending_max_wait_sec: float = 300.0
        # EXTERNAL_CLOSE: additive confidence (see _external_close_confidence_score)
        self._orphan_close_score_threshold = 6
        self._orphan_close_suspect_floor = 5
        _logs_root = Path(__file__).resolve().parents[2] / "logs"
        _safe_id = (engine_id or "default").replace(" ", "_").replace("/", "_")
        self._order_state_engine_id = _safe_id
        self._logs_root = _logs_root
        self._legacy_order_state_file = (
            _logs_root
            / str(self.strategy_id or "GLOBAL").replace(" ", "_").replace("/", "_")
            / f"order_state_{_safe_id}.json"
        )
        self._load_order_state()
        self._rebuild_order_state_cache()
        # Fills before this instant are ignored for orphan EXTERNAL_CLOSE / LIQUIDATION / ADL paths.
        self._oms_session_start_unix = time.time()
        self.bracket_registry = BracketLegRegistry()
        self.gtt_fallback_book = GttFallbackBook(
            self,
            instrument_store=instrument_store,
            engine_logger=engine_logger,
        )
        self.reentry_at_cost_book = ReentryAtCostBook(
            self,
            instrument_store=instrument_store,
            engine_logger=engine_logger,
        )
        # Optional: (bundle_item, intents, price_map) -> None; refreshes limit prices from live depth.
        self.bundle_price_refresher: Optional[
            Callable[[Dict[str, Any], List[Any], Dict[str, float]], None]
        ] = None
        # Optional: broker reports no_open_position on bracket/SL placement (manual exit sync).
        self.on_broker_no_open_position: Optional[
            Callable[..., None]
        ] = None

    def reset_oms_session_boundary(self) -> None:
        """Call when starting a new trading session (same process) to tighten orphan fill acceptance."""
        self._oms_session_start_unix = time.time()

    def _intent_strategy_id(
        self, intent_id: Optional[str], default: Optional[str] = None
    ) -> Optional[str]:
        sid = default or self.strategy_id
        if not intent_id or self.intent_store is None:
            return sid
        rec = self.intent_store.get(str(intent_id))
        if not rec:
            return sid
        payload = rec.get("payload") or {}
        return (
            rec.get("strategy")
            or payload.get("strategy_id")
            or sid
        )

    def _intent_execution_mode(self, intent_rec: Dict[str, Any]) -> str:
        if not intent_rec:
            return ""
        payload = intent_rec.get("payload") or {}
        strategy_meta = (
            payload.get("strategy_meta")
            or intent_rec.get("strategy_meta")
            or {}
        )
        if isinstance(strategy_meta, dict):
            mode = strategy_meta.get("execution_mode")
            if mode:
                return str(mode).strip().upper()
        return str(payload.get("execution_mode") or "").strip().upper()

    def _intent_is_gtt(self, intent_rec: Dict[str, Any]) -> bool:
        return self._intent_execution_mode(intent_rec) in ("GTT", "HYBRID_GTT")

    def _intent_is_hybrid_gtt(self, intent: Any) -> bool:
        extras = getattr(intent, "metadata_extras", None) or {}
        if isinstance(extras, dict):
            return str(extras.get("execution_mode") or "").upper() == "HYBRID_GTT"
        return False

    def _intent_trading_symbol(self, intent_rec: Dict[str, Any]) -> str:
        if not isinstance(intent_rec, dict):
            return ""
        inst = intent_rec.get("instrument")
        sym = self._instrument_trading_symbol(inst)
        if sym:
            return sym
        payload = intent_rec.get("payload") or {}
        return str(payload.get("symbol") or intent_rec.get("symbol") or "").strip()

    def find_entry_intent_for_symbol(
        self, trading_symbol: str, *, include_sent: bool = True
    ) -> Optional[Dict[str, Any]]:
        """Best-match MAIN ENTRY intent for a symbol (FILLED, else pending SENT/VALIDATED)."""
        if not self.intent_store or not trading_symbol:
            return None
        sym_u = str(trading_symbol).strip().upper()
        best: Optional[tuple] = None  # (rank, updated_at, rec)
        statuses = [IntentStatus.FILLED]
        if include_sent:
            statuses.extend([IntentStatus.SENT, IntentStatus.VALIDATED])
        for st in statuses:
            rank = 0 if st == IntentStatus.FILLED else 1
            for rec in self.intent_store.list_by_status(st):
                payload = rec.get("payload") or {}
                if str(payload.get("action") or rec.get("action") or "").upper() != "ENTRY":
                    continue
                tag = str(rec.get("tag") or payload.get("tag") or "MAIN").upper()
                if tag != "MAIN":
                    continue
                tsym = self._intent_trading_symbol(rec).upper()
                if tsym != sym_u:
                    continue
                upd = float(rec.get("updated_at") or rec.get("created_at") or 0)
                if best is None or rank < best[0] or (rank == best[0] and upd >= best[1]):
                    best = (rank, upd, rec)
        return best[2] if best else None

    def _apply_gtt_fill_from_intent(
        self, intent_rec: Dict[str, Any], *, price: float, qty_lots: int, order_id: Any
    ) -> bool:
        """Apply a discovered GTT fill and run MAIN entry hooks (SL placement)."""
        intent_id = str(intent_rec.get("intent_id") or "")
        if not intent_id:
            return False
        if self._order_state.get(intent_id) in _TERMINAL_ORDER_STATES:
            return True
        instrument = intent_rec.get("instrument")
        if not instrument:
            return False
        payload = intent_rec.get("payload") or {}
        side = str(intent_rec.get("side") or payload.get("side") or "BUY").upper()
        qty_lots = max(1, int(qty_lots))
        price = float(price)
        if price <= 0:
            return False
        sym = self._instrument_trading_symbol(instrument)
        if not sym or not self.position_manager:
            return False
        local_units = int(self.position_manager.get_qty(sym))
        lot_size = max(
            1,
            int(getattr(instrument, "lot_size", 0) or payload.get("lot_size") or 1),
        )
        broker_units = qty_lots * lot_size
        signed_broker = broker_units if side == "BUY" else -broker_units
        trade_id = f"GTT_SYNC:{intent_id}:{order_id or ''}:{qty_lots}:{price}"
        if (
            local_units != 0
            and local_units == signed_broker
            and not self._terminal_fill_reflected_in_pm(
                instrument,
                side,
                qty_lots,
                "ENTRY",
                intent_id,
                structure_id=intent_rec.get("structure_id")
                or payload.get("structure_id"),
            )
        ):
            if self.engine_logger:
                self.engine_logger.log(
                    "oms",
                    f"GTT fill adopt {sym} intent_id={intent_id} "
                    f"(broker qty already in PM; attaching metadata + SL)",
                    strategy_id=self._intent_strategy_id(intent_id),
                    intent_id=intent_id,
                )
            self._adopt_main_entry_shadow_fill(
                instrument=instrument,
                intent=intent_rec,
                intent_id=intent_id,
                side=side,
                qty=qty_lots,
                price=price,
                order_id=order_id,
                trade_id=trade_id,
            )
            return True
        trade = {
            "trade_id": trade_id,
            "id": trade_id,
            "order_id": str(order_id or intent_rec.get("broker_order_id") or ""),
            "intent_id": intent_id,
            "client_order_id": intent_id,
            "tag": intent_id,
            "price": price,
            "size": float(qty_lots),
            "side": side,
            "action": "ENTRY",
            "execution_source": "GTT_RECON",
        }
        if self.process_trade(trade):
            book = getattr(self, "gtt_fallback_book", None)
            if book is not None:
                book.on_fill(intent_id)
            if self.engine_logger:
                self.engine_logger.log(
                    "oms",
                    f"GTT fill synced for {sym} intent_id={intent_id}",
                    strategy_id=self._intent_strategy_id(intent_id),
                    intent_id=intent_id,
                )
            return True
        return False

    def _try_sync_gtt_intent_fill(self, intent_rec: Dict[str, Any]) -> bool:
        """Poll Forever order book / fills API for a single pending GTT intent."""
        if not self._intent_is_gtt(intent_rec):
            return False
        intent_id = str(intent_rec.get("intent_id") or "")
        if not intent_id:
            return False
        if self._order_state.get(intent_id) in _TERMINAL_ORDER_STATES:
            return True

        order = None
        if hasattr(self.broker, "find_forever_order_by_client_id"):
            try:
                order = self.broker.find_forever_order_by_client_id(intent_id)
            except Exception:
                order = None
        if not order and hasattr(self.broker, "find_order_by_client_id"):
            try:
                raw = self.broker.find_order_by_client_id(intent_id)
                if raw:
                    order = self._normalize_broker_order_for_recon(raw)
            except Exception:
                order = None

        if order:
            status = (order.get("status") or "").lower()
            filled = float(order.get("filled_size") or 0)
            size = float(order.get("size") or 0)
            if status == "filled" or (size > 0 and filled >= size):
                payload = intent_rec.get("payload") or {}
                inst = intent_rec.get("instrument")
                lot_size = max(
                    1,
                    int(
                        getattr(inst, "lot_size", 0)
                        or payload.get("lot_size")
                        or 1
                    ),
                )
                qty_lots = max(1, int(round(filled / lot_size))) if filled else 1
                price = float(
                    order.get("average_fill_price")
                    or intent_rec.get("price")
                    or payload.get("price")
                    or 0
                )
                return self._apply_gtt_fill_from_intent(
                    intent_rec,
                    price=price,
                    qty_lots=qty_lots,
                    order_id=order.get("order_id"),
                )

        fill_info = None
        if hasattr(self.broker, "get_fill_for_client_order_id"):
            try:
                fill_info = self.broker.get_fill_for_client_order_id(intent_id)
            except Exception:
                fill_info = None
        if not fill_info and intent_rec.get("broker_order_id") and hasattr(
            self.broker, "get_fill_by_order_id"
        ):
            try:
                fill_info = self.broker.get_fill_by_order_id(
                    str(intent_rec["broker_order_id"])
                )
            except Exception:
                fill_info = None
        if fill_info and float(fill_info.get("price") or 0) > 0:
            payload = intent_rec.get("payload") or {}
            inst = intent_rec.get("instrument")
            lot_size = max(
                1,
                int(getattr(inst, "lot_size", 0) or payload.get("lot_size") or 1),
            )
            raw_size = float(fill_info.get("size") or 0)
            qty_lots = max(1, int(round(raw_size / lot_size))) if raw_size else 1
            return self._apply_gtt_fill_from_intent(
                intent_rec,
                price=float(fill_info["price"]),
                qty_lots=qty_lots,
                order_id=fill_info.get("order_id"),
            )
        return False

    def _sync_gtt_pending_fills(self, local_pending: List[Dict[str, Any]]) -> int:
        """Sync fills for pending GTT ENTRY intents; returns count applied."""
        applied = 0
        for rec in local_pending:
            if not self._intent_is_gtt(rec):
                continue
            payload = rec.get("payload") or {}
            if str(payload.get("action") or rec.get("action") or "").upper() != "ENTRY":
                continue
            if self._try_sync_gtt_intent_fill(rec):
                applied += 1
        return applied

    def adopt_pending_entries_from_broker_positions(
        self, broker_positions: Dict[str, Any]
    ) -> int:
        """
        When broker holds qty for a symbol with a pending GTT ENTRY intent locally,
        apply the fill (or adopt linkage) so MAIN_SL can be armed.
        """
        if not broker_positions or not self.intent_store:
            return 0
        local_pending = self.intent_store.list_by_status(
            IntentStatus.SENT
        ) + self.intent_store.list_by_status(IntentStatus.VALIDATED)
        applied = 0
        for rec in local_pending:
            if not self._intent_is_gtt(rec):
                continue
            payload = rec.get("payload") or {}
            if str(payload.get("action") or rec.get("action") or "").upper() != "ENTRY":
                continue
            sym = self._intent_trading_symbol(rec)
            if not sym:
                continue
            bp = broker_positions.get(sym)
            if not bp:
                for b_sym, row in broker_positions.items():
                    if str(b_sym).strip().upper() == sym.upper():
                        bp = row
                        break
            if not bp:
                continue
            try:
                broker_units = int(bp.get("qty") or 0)
            except (TypeError, ValueError):
                continue
            if broker_units == 0:
                continue
            side = str(rec.get("side") or payload.get("side") or "BUY").upper()
            if side == "BUY" and broker_units <= 0:
                continue
            if side == "SELL" and broker_units >= 0:
                continue
            inst = rec.get("instrument")
            lot_size = max(
                1,
                int(
                    getattr(inst, "lot_size", 0)
                    or bp.get("lot_size")
                    or payload.get("lot_size")
                    or 1
                ),
            )
            qty_lots = max(1, abs(broker_units) // lot_size)
            price = float(
                bp.get("avg_price")
                or rec.get("price")
                or payload.get("price")
                or 0
            )
            if self._apply_gtt_fill_from_intent(
                rec,
                price=price,
                qty_lots=qty_lots,
                order_id=rec.get("broker_order_id"),
            ):
                applied += 1
        return applied

    def _promote_seeded_intent_to_filled(self, intent_id: str) -> None:
        """Move a CSV-seeded intent through VALIDATED → SENT → FILLED."""
        rec = self.intent_store.get(intent_id)
        if not rec:
            return
        cur = rec.get("status")
        if isinstance(cur, str):
            cur = IntentStatus(cur)
        if cur == IntentStatus.FILLED:
            return
        if cur == IntentStatus.CREATED:
            self.intent_store.update(intent_id, IntentStatus.VALIDATED)
            cur = IntentStatus.VALIDATED
        if cur == IntentStatus.VALIDATED:
            self.intent_store.update(intent_id, IntentStatus.SENT)
            cur = IntentStatus.SENT
        if cur in (IntentStatus.SENT, IntentStatus.ACKED):
            self.intent_store.update(
                intent_id, IntentStatus.FILLED, order_state=OrderState.FILLED
            )

    def seed_filled_intents_from_open_positions_csv(
        self, csv_path: Optional[str] = None
    ) -> int:
        """
        Create FILLED ENTRY intents from open-positions CSV rows (manual / recovered legs).
        Enables structure_id + tag linkage for LEAPS after restart.
        """
        path = csv_path or getattr(self.position_manager, "open_positions_csv_path", None)
        if not path or not self.intent_store:
            return 0
        try:
            from utils.logger.open_positions_logger import read_open_positions_snapshot
        except ImportError:
            return 0
        snap = read_open_positions_snapshot(path)
        if not snap:
            return 0
        seeded = 0
        for sym, row in snap.items():
            strategy = (row.get("strategy") or self.strategy_id or "").strip()
            structure_id = (row.get("structure_id") or "").strip()
            tag = (row.get("tag") or "MAIN").strip().upper()
            if not strategy or not structure_id:
                continue
            try:
                nq = int(float(row.get("net_qty") or 0))
            except (TypeError, ValueError):
                continue
            if nq == 0:
                continue
            intent_id = (row.get("intent_id") or "").strip()
            if not intent_id:
                intent_id = f"seed_{tag.lower()}_{sym[-12:].replace('-', '')}"[:30]
            if self.intent_store.exists(intent_id):
                self._promote_seeded_intent_to_filled(intent_id)
                if self._order_state.get(intent_id) != OrderState.FILLED:
                    self._set_order_state(
                        intent_id,
                        OrderState.FILLED,
                        action="seed_from_csv",
                        message="Open position CSV seed",
                    )
                seeded += 1
                continue
            side = "SELL" if nq < 0 else "BUY"
            qty = abs(nq)
            try:
                avg = float(row.get("avg_price") or 0)
            except (TypeError, ValueError):
                avg = 0.0
            inst = None
            if self.instrument_store:
                from core.orderExecution.position_manager import PositionManager

                opt, strike = PositionManager._extract_option_hint(sym, structure_id)
                inst = self.instrument_store.intent_creation_details(
                    sym, "NSE", None, opt, strike
                )
            payload = {
                "symbol": sym,
                "side": side,
                "qty": qty,
                "price": avg,
                "action": "ENTRY",
                "strategy": strategy,
                "strategy_id": strategy,
                "structure_id": structure_id,
                "tag": tag,
                "engine_id": self.engine_id,
            }
            self.intent_store.create(payload=payload, intent_id=intent_id)
            self.intent_store.update(intent_id, IntentStatus.VALIDATED)
            self._promote_seeded_intent_to_filled(intent_id)
            rec = self.intent_store.get(intent_id)
            if rec and inst is not None:
                rec["instrument"] = inst
                rec["side"] = side
                rec["qty"] = qty
                rec["tag"] = tag
                rec["structure_id"] = structure_id
                rec["action"] = "ENTRY"
            self._set_order_state(
                intent_id,
                OrderState.FILLED,
                action="seed_from_csv",
                message=f"Seeded FILLED {tag} from open-positions CSV",
            )
            seeded += 1
        return seeded

    @staticmethod
    def _broker_tag_matches_intent(intent_id: str, broker_tag: str) -> bool:
        tag = str(broker_tag or "").strip()
        iid = str(intent_id or "").strip()
        if not tag or not iid:
            return False
        if tag == iid:
            return True
        return tag == dhan_correlation_id(iid)

    def _intent_matched_on_broker_open(
        self,
        intent_id: str,
        broker_order_id: Optional[str],
        broker_tags: Set[str],
        broker_order_ids: Set[str],
    ) -> bool:
        iid = str(intent_id or "").strip()
        if not iid:
            return False
        if iid in broker_tags:
            return True
        dhan_cid = dhan_correlation_id(iid)
        if dhan_cid in broker_tags:
            return True
        if broker_order_id and str(broker_order_id) in broker_order_ids:
            return True
        return False

    def _resolve_intent_id_from_broker_order(
        self, order: Dict[str, Any], local_pending: List[Dict[str, Any]]
    ) -> Optional[str]:
        tag = str(order.get("tag") or order.get("correlationId") or "").strip()
        oid = str(order.get("order_id") or order.get("orderId") or "").strip()
        for rec in local_pending:
            iid = str(rec.get("intent_id") or "").strip()
            if not iid:
                continue
            if tag and self._broker_tag_matches_intent(iid, tag):
                return iid
            if oid and str(rec.get("broker_order_id") or "") == oid:
                return iid
        return None

    def _merge_forever_orders_for_recon(
        self,
        broker_open: List[Dict[str, Any]],
        local_pending: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        if not hasattr(self.broker, "get_forever_open_orders"):
            return broker_open
        try:
            forever_raw = self.broker.get_forever_open_orders() or []
        except Exception as exc:
            logger.warning("Failed to fetch forever open orders: %s", exc)
            return broker_open
        merged = list(broker_open)
        for o in forever_raw:
            if not isinstance(o, dict):
                continue
            norm = self._normalize_broker_order_for_recon(o)
            resolved = self._resolve_intent_id_from_broker_order(norm, local_pending)
            if resolved:
                norm["tag"] = resolved
            merged.append(norm)
        return merged

    def _log_oms_step(
        self,
        step: str,
        intent: Any,
        *,
        ok: bool = True,
        message: str = "",
        intent_strategy_id: Optional[str] = None,
        account_id: Optional[str] = None,
        **extra: Any,
    ) -> None:
        """Structured OMS pipeline step for engine JSON log (event_type=oms)."""
        if not self.engine_logger:
            return
        sym = ""
        if getattr(intent, "instrument", None) is not None:
            sym = getattr(intent.instrument, "trading_symbol", None) or ""
        intent_id = getattr(intent, "intent_id", None)
        strategy_id = (
            intent_strategy_id
            or getattr(intent, "strategy", None)
            or self.strategy_id
        )
        parts = [
            f"OMS step={step}",
            f"ok={ok}",
            f"intent_id={intent_id}",
        ]
        if sym:
            parts.append(f"symbol={sym}")
        tag = getattr(intent, "tag", None)
        if tag:
            parts.append(f"tag={tag}")
        action = getattr(intent, "action", None)
        if action:
            parts.append(f"action={action}")
        side = getattr(intent, "side", None)
        if side:
            parts.append(f"side={side}")
        if message:
            parts.append(f"msg={message}")
        for key in (
            "required_margin",
            "available",
            "shortfall",
            "span_margin",
            "exec_price",
            "qty",
            "reason",
            "order_id",
            "attempt",
            "broker_error",
            "broker_error_code",
            "broker_error_message",
            "broker_error_type",
            "broker_payload",
        ):
            if key in extra and extra[key] is not None:
                parts.append(f"{key}={extra[key]}")
        self.engine_logger.log(
            "oms",
            " | ".join(parts),
            intent_id=intent_id,
            strategy_id=strategy_id,
            account_id=account_id,
            symbol=sym or None,
            oms_step=step,
            oms_ok=ok,
            **{k: v for k, v in extra.items() if v is not None},
        )

    def _safe_strategy_dir(self, strategy_id: Optional[str]) -> str:
        return str(strategy_id or self.strategy_id or "GLOBAL").replace(
            " ", "_"
        ).replace("/", "_")

    def _order_state_file_for_strategy(self, strategy_id: str) -> Path:
        sid = self._safe_strategy_dir(strategy_id)
        path = self._logs_root / sid / f"order_state_{self._order_state_engine_id}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def _order_state_files_to_load(self) -> List[Path]:
        paths: List[Path] = []
        seen: Set[str] = set()
        legacy = getattr(self, "_legacy_order_state_file", None)
        if legacy is not None:
            paths.append(legacy)
            seen.add(str(legacy))
        for sid in self._known_strategies:
            p = self._order_state_file_for_strategy(sid)
            key = str(p)
            if key not in seen:
                paths.append(p)
                seen.add(key)
        if not paths and self.strategy_id:
            p = self._order_state_file_for_strategy(self.strategy_id)
            if str(p) not in seen:
                paths.append(p)
        return paths

    @staticmethod
    def _read_order_state_file(path: Path) -> Tuple[Dict[str, OrderState], List[Dict[str, Any]]]:
        states: Dict[str, OrderState] = {}
        log_entries: List[Dict[str, Any]] = []
        if not path.exists():
            return states, log_entries
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                return states, log_entries
            if "states" in data:
                for intent_id, val in data["states"].items():
                    try:
                        states[str(intent_id)] = (
                            OrderState(val) if isinstance(val, str) else val
                        )
                    except (ValueError, TypeError):
                        pass
                log_entries = list(data.get("log") or [])
            else:
                for intent_id, val in data.items():
                    try:
                        states[str(intent_id)] = (
                            OrderState(val) if isinstance(val, str) else val
                        )
                    except (ValueError, TypeError):
                        pass
        except (json.JSONDecodeError, OSError):
            pass
        return states, log_entries

    def _load_order_state(self) -> None:
        """Load intent_id -> OrderState from per-strategy logs/{strategy}/order_state_{engine}.json."""
        merged_states: Dict[str, OrderState] = {}
        merged_log: List[Dict[str, Any]] = []
        for path in self._order_state_files_to_load():
            states, log_entries = self._read_order_state_file(path)
            merged_states.update(states)
            merged_log.extend(log_entries)
        self._order_state = merged_states
        self._order_state_log = merged_log[-self._order_state_log_max :]

    def _persist_order_state(self) -> None:
        """Write order states split by strategy into logs/{strategy_id}/order_state_{engine_id}.json."""
        if not self._order_state:
            targets = list(self._known_strategies) or (
                [self.strategy_id] if self.strategy_id else []
            )
        else:
            targets = set(self._known_strategies)
            for intent_id in self._order_state:
                targets.add(self._intent_strategy_id(intent_id) or self.strategy_id or "GLOBAL")
            targets = sorted(targets)
        if not targets and self.strategy_id:
            targets = [self.strategy_id]
        states_all = {
            k: (v.value if isinstance(v, OrderState) else v)
            for k, v in self._order_state.items()
        }
        log_all = getattr(self, "_order_state_log", [])
        for strategy_id in targets:
            sid = strategy_id or self.strategy_id or "GLOBAL"
            strat_states = {
                k: v
                for k, v in states_all.items()
                if (self._intent_strategy_id(k) or self.strategy_id or "GLOBAL") == sid
            }
            strat_log = [
                e
                for e in log_all
                if not e.get("intent_id")
                or (self._intent_strategy_id(str(e.get("intent_id"))) or self.strategy_id or "GLOBAL")
                == sid
            ]
            if not strat_states and not strat_log:
                continue
            path = self._order_state_file_for_strategy(sid)
            try:
                data = {"states": strat_states, "log": strat_log}
                to_save = round_json_floats(data) if round_json_floats else data
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(to_save, f, indent=2)
            except OSError:
                pass

    def _set_order_state(
        self,
        intent_id: str,
        state: OrderState,
        action: Optional[str] = None,
        message: Optional[str] = None,
    ) -> None:
        """Update in-memory cache, append detailed log entry, and persist to JSON."""
        self._order_state[intent_id] = state
        state_val = state.value if isinstance(state, OrderState) else state
        entry = {
            "timestamp": datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%f")[
                :-3
            ]
            + "Z",
            "intent_id": intent_id,
            "state": state_val,
            "action": action or "set",
            "message": message or "",
        }
        log = getattr(self, "_order_state_log", [])
        log.append(entry)
        if len(log) > getattr(self, "_order_state_log_max", 500):
            self._order_state_log = log[-self._order_state_log_max :]
        else:
            self._order_state_log = log
        self._persist_order_state()

    def prune_terminal_order_states(
        self, *, keep_recent_seconds: float = 6 * 3600, max_terminal: int = 2_000
    ) -> int:
        """Drop old terminal order-state entries to bound RAM/JSON growth."""
        now = time.time()
        # Prefer timestamps from the rolling state log when available.
        last_ts: Dict[str, float] = {}
        for entry in getattr(self, "_order_state_log", []) or []:
            iid = entry.get("intent_id")
            if not iid:
                continue
            ts_raw = entry.get("timestamp")
            try:
                if isinstance(ts_raw, str) and ts_raw.endswith("Z"):
                    dt = datetime.datetime.strptime(ts_raw[:19], "%Y-%m-%dT%H:%M:%S")
                    last_ts[str(iid)] = dt.replace(tzinfo=datetime.timezone.utc).timestamp()
            except (TypeError, ValueError):
                continue

        to_drop: List[str] = []
        terminal_ids = [
            iid
            for iid, st in list(self._order_state.items())
            if st in _TERMINAL_ORDER_STATES
        ]
        for iid in terminal_ids:
            ts = last_ts.get(iid, 0.0)
            if keep_recent_seconds > 0 and ts and (now - ts) < keep_recent_seconds:
                continue
            if not ts:
                # No timestamp — still candidates once over soft cap.
                continue
            to_drop.append(iid)

        if len(terminal_ids) > max_terminal:
            # Force-drop oldest unknown-ts terminals beyond soft cap.
            surplus = [
                iid for iid in terminal_ids if iid not in to_drop and iid not in last_ts
            ]
            surplus.extend(
                sorted(
                    [iid for iid in terminal_ids if iid in last_ts],
                    key=lambda i: last_ts.get(i, 0.0),
                )
            )
            need = len(terminal_ids) - max_terminal
            for iid in surplus:
                if need <= 0:
                    break
                if iid not in to_drop:
                    to_drop.append(iid)
                    need -= 1

        for iid in to_drop:
            self._order_state.pop(iid, None)
            filled_map = getattr(self, "_last_applied_filled_by_intent", None)
            if isinstance(filled_map, dict):
                filled_map.pop(iid, None)
        if to_drop:
            self._persist_order_state()
            logger.info("OrderRouter pruned %s terminal order-state entr(y/ies)", len(to_drop))
        return len(to_drop)

    def _rebuild_order_state_cache(self) -> None:
        """Merge IntentStore order states into _order_state (e.g. after restart). Then persist."""
        if not hasattr(self.intent_store, "get_all_order_states"):
            return
        for intent_id, order_state_val in self.intent_store.get_all_order_states():
            try:
                self._order_state[intent_id] = (
                    OrderState(order_state_val)
                    if isinstance(order_state_val, str)
                    else order_state_val
                )
            except (ValueError, TypeError):
                pass
        # Append one log entry for this rebuild (no single intent_id)
        log = getattr(self, "_order_state_log", [])
        log.append(
            {
                "timestamp": datetime.datetime.utcnow().strftime(
                    "%Y-%m-%dT%H:%M:%S.%f"
                )[:-3]
                + "Z",
                "intent_id": "",
                "state": "",
                "action": "cache_rebuild",
                "message": "Merged order states from intent_store at startup",
            }
        )
        if len(log) > getattr(self, "_order_state_log_max", 500):
            self._order_state_log = log[-self._order_state_log_max :]
        else:
            self._order_state_log = log
        self._reconcile_stale_bracket_order_states_on_startup()
        self._persist_order_state()

    def _persisted_sent_has_filled_bracket_sibling(self, sent_intent_id: str) -> bool:
        """True when another bracket leg from the same bundle is FILLED in persisted state."""
        log = getattr(self, "_order_state_log", [])
        sent_ts = None
        for entry in log:
            if (
                entry.get("intent_id") == sent_intent_id
                and entry.get("action") == "order_placed"
            ):
                sent_ts = str(entry.get("timestamp") or "")
                break
        if not sent_ts:
            return False
        try:
            sent_epoch = datetime.datetime.fromisoformat(
                sent_ts.replace("Z", "+00:00")
            ).timestamp()
        except (TypeError, ValueError):
            return False
        for entry in log:
            if entry.get("action") != "order_placed":
                continue
            other_id = str(entry.get("intent_id") or "")
            if not other_id or other_id == sent_intent_id:
                continue
            other_ts = str(entry.get("timestamp") or "")
            try:
                other_epoch = datetime.datetime.fromisoformat(
                    other_ts.replace("Z", "+00:00")
                ).timestamp()
            except (TypeError, ValueError):
                continue
            if abs(other_epoch - sent_epoch) > 30.0:
                continue
            if self._order_state.get(other_id) == OrderState.FILLED:
                return True
        return False

    def _reconcile_stale_bracket_order_states_on_startup(self) -> None:
        """Clear stale SENT bracket legs after restart when sibling already FILLED."""
        if self.intent_store:
            for status in (IntentStatus.SENT, IntentStatus.VALIDATED):
                for rec in self.intent_store.list_by_status(status):
                    self._try_resolve_cancelled_bracket_sibling(rec)
        for sent_id in list(self._order_state.keys()):
            if self._order_state.get(sent_id) != OrderState.SENT:
                continue
            if self.intent_store and self.intent_store.exists(sent_id):
                rec = self.intent_store.get(sent_id)
                if rec and self._try_resolve_cancelled_bracket_sibling(rec):
                    continue
            if self._persisted_sent_has_filled_bracket_sibling(sent_id):
                self._mark_intent_cancelled(
                    sent_id,
                    action="startup_sibling_filled_oco",
                    message="Persisted SENT bracket leg; sibling already FILLED",
                )

    def _mark_intent_cancelled(
        self, intent_id: str, *, action: str, message: str
    ) -> None:
        self._set_order_state(
            intent_id, OrderState.CANCELLED, action=action, message=message
        )
        if self.intent_store:
            self.intent_store.update(
                intent_id, IntentStatus.CANCELLED, order_state=OrderState.CANCELLED
            )

    def _intent_is_terminal_filled(self, intent_id: str) -> bool:
        if self._order_state.get(intent_id) == OrderState.FILLED:
            return True
        rec = self.intent_store.get(intent_id) if self.intent_store else None
        if not rec:
            return False
        st = rec.get("status")
        return str(getattr(st, "value", st)).upper() == "FILLED"

    def _maybe_cancel_bracket_sibling_after_exit(
        self,
        position_closed: bool,
        tag_fill: str,
        structure_id: Optional[str],
    ) -> None:
        tag_u = str(tag_fill or "").upper()
        stid = str(structure_id or "").strip()
        if not position_closed or not stid or tag_u not in BRACKET_TAGS:
            return
        self.bracket_registry.cancel_sibling(
            stid,
            tag_u,
            broker=self.broker,
            order_router=self,
            reason="sibling_fill",
        )
        self.bracket_registry.clear_structure(stid)

    def _try_resolve_cancelled_bracket_sibling(
        self, intent_record: Dict[str, Any]
    ) -> bool:
        """Resolve missing bracket leg when sibling filled and exchange OCO removed it."""
        intent_id = str(intent_record.get("intent_id") or "")
        if not intent_id:
            return False
        payload = intent_record.get("payload") or {}
        tag_u = str(intent_record.get("tag") or payload.get("tag") or "").upper()
        if tag_u not in BRACKET_TAGS:
            return False
        stid = intent_record.get("structure_id") or payload.get("structure_id")
        if not stid:
            return False
        other_tag = "MAIN_TARGET" if tag_u == "MAIN_SL" else "MAIN_SL"
        sibling_filled = False
        sib = self.bracket_registry.get_sibling(str(stid), tag_u)
        if sib and sib.get("intent_id"):
            sibling_filled = self._intent_is_terminal_filled(str(sib["intent_id"]))
        if not sibling_filled and self.intent_store:
            for rec in self.intent_store.list_by_status(IntentStatus.FILLED):
                rec_stid = rec.get("structure_id") or (rec.get("payload") or {}).get(
                    "structure_id"
                )
                if str(rec_stid or "") != str(stid):
                    continue
                rec_tag = str(
                    rec.get("tag") or (rec.get("payload") or {}).get("tag") or ""
                ).upper()
                if rec_tag == other_tag:
                    sibling_filled = True
                    break
        if not sibling_filled:
            return False
        self._mark_intent_cancelled(
            intent_id,
            action="sibling_filled_oco",
            message=f"Bracket sibling {other_tag} filled; leg removed on exchange",
        )
        return True

    def _find_broker_order_for_intent(
        self, intent_record: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        intent_id = str(intent_record.get("intent_id") or "")
        order = None
        if intent_id and hasattr(self.broker, "find_order_by_client_id"):
            try:
                order = self.broker.find_order_by_client_id(intent_id)
            except Exception:
                order = None
        broker_oid = intent_record.get("broker_order_id")
        if not order and broker_oid:
            find_by_id = getattr(self.broker, "find_order_by_id", None)
            if callable(find_by_id):
                try:
                    order = find_by_id(str(broker_oid))
                except Exception:
                    order = None
        return order

    @staticmethod
    def _is_retryable_broker_error(exc: Exception) -> bool:
        msg = str(exc or "").lower()
        if "dh-906" in msg or "dh-907" in msg or "market is closed" in msg:
            return False
        retry_tokens = (
            "timeout",
            "temporarily",
            "connection reset",
            "connection aborted",
            "connection error",
            "503",
            "502",
            "504",
            "gateway",
            "rate limit",
        )
        return any(token in msg for token in retry_tokens)

    @staticmethod
    def _broker_failure_log_fields(
        broker_fail: Optional[Dict[str, Any]],
        *,
        default: str = "Broker place_order returned None",
    ) -> Dict[str, Any]:
        info = format_broker_failure_for_log(broker_fail, default=default)
        return {
            "fail_detail": info["display_message"],
            "reason": info["reason"],
            "retryable": info["retryable"],
            "broker_error": info["display_message"],
            "broker_error_code": info.get("error_code"),
            "broker_error_message": info.get("error_message"),
            "broker_error_type": info.get("error_type"),
        }

    @staticmethod
    def _failure_is_no_open_position(
        fail: Optional[Dict[str, Any]], message: str = ""
    ) -> bool:
        parts = [
            str((fail or {}).get("error_code") or ""),
            str((fail or {}).get("reason") or ""),
            str((fail or {}).get("message") or ""),
            message,
        ]
        return "no_open_position" in " ".join(parts).lower()

    @staticmethod
    def _intent_trading_symbol(intent: Any) -> str:
        inst = getattr(intent, "instrument", None)
        return str(getattr(inst, "trading_symbol", None) or "").strip()

    def _intent_is_broker_flat_sync_candidate(self, intent: Any) -> bool:
        action_u = str(getattr(intent, "action", "") or "").upper()
        tag_u = str(getattr(intent, "tag", "") or "").upper()
        return action_u in ("FORCE_EXIT", "EXIT") or tag_u in (
            "MAIN_SL",
            "MAIN_TARGET",
        )

    def _handle_broker_no_open_position(
        self,
        intents: List[Any],
        *,
        message: str,
        bundle_item: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Position already flat at broker; sync PM and stop bracket/reentry retries."""
        primary = intents[0] if intents else None
        trading_sym = self._intent_trading_symbol(primary) if primary else ""
        structure_id = getattr(primary, "structure_id", None) if primary else None
        strategy_id = (
            getattr(primary, "strategy_id", None)
            or (bundle_item or {}).get("strategy_id")
            or self.strategy_id
        )
        for intent in intents:
            self.intent_store.update(
                intent.intent_id,
                IntentStatus.CANCELLED,
                order_state=OrderState.CANCELLED,
            )
            self._set_order_state(
                intent.intent_id,
                OrderState.CANCELLED,
                action="broker_flat_sync",
                message=message,
            )
        handler = self.on_broker_no_open_position
        if callable(handler):
            try:
                handler(
                    trading_symbol=trading_sym,
                    structure_id=structure_id,
                    strategy_id=strategy_id,
                    message=message,
                )
            except Exception as exc:
                logger.warning(
                    "on_broker_no_open_position failed symbol=%s sid=%s: %s",
                    trading_sym,
                    structure_id,
                    exc,
                )
        if self.engine_logger:
            self.engine_logger.log(
                "reconciliation",
                (
                    f"BROKER_FLAT_SYNC trading_symbol={trading_sym} "
                    f"structure_id={structure_id} reason=no_open_position "
                    f"detail={message}"
                ),
                symbol=trading_sym or None,
                structure_id=structure_id,
                strategy_id=strategy_id,
            )
        return {
            "ok": True,
            "retryable": False,
            "reason": "broker_flat_synced",
        }

    @staticmethod
    def _coerce_positive_exec_price(price: Any) -> Optional[float]:
        if price is None:
            return None
        try:
            p = float(price)
        except (TypeError, ValueError):
            return None
        if p != p or p <= 0:
            return None
        return p

    @staticmethod
    def _lookup_price_map(
        price_map: Optional[Dict[str, Any]], intent: Any, trading_sym: str = ""
    ) -> Optional[float]:
        """Resolve price from map using trading_symbol and/or place_order_symbol keys."""
        if not price_map:
            return None
        keys: List[str] = []
        if trading_sym:
            keys.append(str(trading_sym).strip())
        inst = getattr(intent, "instrument", None)
        if inst is not None:
            ts = getattr(inst, "trading_symbol", None)
            if ts:
                keys.append(str(ts).strip())
            if hasattr(inst, "place_order_symbol"):
                try:
                    pos = inst.place_order_symbol()
                except Exception:
                    pos = None
                if pos:
                    keys.append(str(pos).strip())
            custom = getattr(inst, "custom_symbol", None)
            if custom:
                keys.append(str(custom).strip())
        seen: Set[str] = set()
        for key in keys:
            if not key or key in seen:
                continue
            seen.add(key)
            val = price_map.get(key)
            if val is None:
                # Case-insensitive fallback for Dhan custom symbols.
                for mk, mv in price_map.items():
                    if str(mk).strip().upper() == key.upper():
                        val = mv
                        break
            coerced = OrderRouter._coerce_positive_exec_price(val)
            if coerced is not None:
                return coerced
        return None

    def process_intent(
        self,
        intent,
        price_map,
        idempotency_key=None,
        raise_on_retryable_failure: bool = False,
        skip_margin_check: bool = False,
        bundle_margin_result: Optional[Dict[str, Any]] = None,
        defer_broker_place: bool = False,
    ):
        intent_engine_id = getattr(intent, "engine_id", None) or self.engine_id
        intent_strategy_id = (
            getattr(intent, "strategy_id", None)
            or getattr(intent, "strategy_name", None)
            or getattr(intent, "strategy", None)
            or self.strategy_id
        )
        sym = (
            getattr(intent.instrument, "trading_symbol", None)
            if getattr(intent, "instrument", None)
            else ""
        )
        side = getattr(intent, "side", "")
        qty_lots = int(getattr(intent, "qty", 0) or 0)
        lot_size = int(
            getattr(getattr(intent, "instrument", None), "lot_size", 0) or 0
        ) or 1
        qty_units = qty_lots * lot_size
        qty = qty_lots  # intent + logs use lots; Dhan maps to qty_units at broker
        action = getattr(intent, "action", "ENTRY")

        self._log_oms_step(
            "process_start",
            intent,
            ok=True,
            intent_strategy_id=intent_strategy_id,
            qty=qty_lots,
            qty_units=qty_units,
            lot_size=lot_size,
        )

        if not self.risk.allow_intent(
            intent, price_map, candle_ts=getattr(intent, "candle_ts", None)
        ):
            self._log_oms_step(
                "risk_check",
                intent,
                ok=False,
                message="Risk manager did not allow intent",
                intent_strategy_id=intent_strategy_id,
                reason="risk_rejected",
            )
            self.intent_store.update(
                intent.intent_id, IntentStatus.REJECTED, order_state=OrderState.REJECTED
            )
            self._set_order_state(
                intent.intent_id,
                OrderState.REJECTED,
                action="risk_rejected",
                message="Risk manager did not allow intent",
            )
            if self.engine_logger:
                self.engine_logger.log(
                    "order_failed",
                    f"ORDER_FAILED intent_id={intent.intent_id} reason=risk_rejected",
                    intent_id=intent.intent_id,
                    strategy_id=intent_strategy_id,
                    symbol=sym,
                    side=side,
                    qty=qty,
                )
            return {"ok": False, "retryable": False, "reason": "risk_rejected"}
        self._log_oms_step(
            "risk_check",
            intent,
            ok=True,
            intent_strategy_id=intent_strategy_id,
        )

        # Fix 3: Intent Deduplication (scoped by engine_id + strategy_id to support multi-engine/multi-strategy)
        if getattr(intent, "action", "") == "EXIT":
            pending = self.intent_store.list_by_status(
                IntentStatus.SENT
            ) + self.intent_store.list_by_status(IntentStatus.VALIDATED)
            symbol = (
                intent.instrument.trading_symbol
                if hasattr(intent, "instrument")
                else ""
            )
            for p in pending:
                p_payload = p.get("payload", {})
                if (
                    p_payload.get("symbol") == symbol
                    and p_payload.get("action") == "EXIT"
                    and p_payload.get("engine_id") == intent_engine_id
                    and p_payload.get("strategy_id") == intent_strategy_id
                ):
                    self._log_oms_step(
                        "duplicate_exit_skip",
                        intent,
                        ok=True,
                        message=f"Exit for {symbol} already in flight",
                        intent_strategy_id=intent_strategy_id,
                        reason="duplicate_exit",
                    )
                    return {"ok": True, "retryable": False, "reason": "duplicate_exit"}

        # Resolve execution price: always prefer price_map (engine updates it with best bid/ask).
        # Engine may key by place_order_symbol (Dhan SEM_CUSTOM_SYMBOL) while intent.instrument
        # uses compact trading_symbol — try both.
        exec_price = None
        if price_map:
            exec_price = self._lookup_price_map(price_map, intent, sym)
        if exec_price is None:
            exec_price = intent.price
        exec_price = self._coerce_positive_exec_price(exec_price)
        if exec_price is None:
            self._log_oms_step(
                "price_resolve",
                intent,
                ok=False,
                message=f"No price for {sym!r}",
                intent_strategy_id=intent_strategy_id,
                reason="no_price",
            )
            raise ValueError(
                f"No price available for intent {intent.intent_id} (price_map has no "
                f"positive entry for {sym!r} and intent.price is missing or <= 0)"
            )

        exec_price = self.slippage_model(exec_price)
        sym = intent.instrument.trading_symbol if hasattr(intent, "instrument") else sym
        self._log_oms_step(
            "price_resolve",
            intent,
            ok=True,
            intent_strategy_id=intent_strategy_id,
            exec_price=exec_price,
            qty=qty,
        )

        # ENTRY → check margin. EXIT / FORCE_EXIT → NEVER check margin (otherwise you cannot close positions).
        if action not in ("EXIT", "FORCE_EXIT"):
            if skip_margin_check and bundle_margin_result is not None:
                funds_check = bundle_margin_result
                self._log_oms_step(
                    "margin_check",
                    intent,
                    ok=True,
                    message=f"Bundle margin pre-approved ({funds_check.get('message') or 'ok'})",
                    intent_strategy_id=intent_strategy_id,
                    exec_price=exec_price,
                    qty=qty_lots,
                    qty_units=qty_units,
                    lot_size=lot_size,
                    required_margin=funds_check.get("required_margin"),
                    available=funds_check.get("available"),
                    shortfall=0,
                    span_margin=funds_check.get("span_margin"),
                )
            elif skip_margin_check:
                funds_check = None
                self._log_oms_step(
                    "margin_check",
                    intent,
                    ok=True,
                    message="Margin check skipped (bundle pre-approved)",
                    intent_strategy_id=intent_strategy_id,
                    exec_price=exec_price,
                    qty=qty,
                )
            else:
                funds_check = getattr(
                    self.broker, "check_funds_before_order", lambda _i, _p: None
                )(intent, exec_price)
                if funds_check is None:
                    self._log_oms_step(
                        "margin_check",
                        intent,
                        ok=True,
                        message="Margin check skipped (broker returned None)",
                        intent_strategy_id=intent_strategy_id,
                        exec_price=exec_price,
                        qty=qty,
                    )
                else:
                    margin_ok = bool(funds_check.get("ok", True))
                    margin_msg = funds_check.get("message") or ""
                    self._log_oms_step(
                        "margin_check",
                        intent,
                        ok=margin_ok,
                        message=margin_msg or ("margin_ok" if margin_ok else "insufficient_funds"),
                        intent_strategy_id=intent_strategy_id,
                        exec_price=exec_price,
                        qty=qty_lots,
                        qty_units=qty_units,
                        lot_size=lot_size,
                        required_margin=funds_check.get("required_margin"),
                        available=funds_check.get("available"),
                        shortfall=funds_check.get("shortfall"),
                        span_margin=funds_check.get("span_margin"),
                        reason="insufficient_funds" if not margin_ok else None,
                    )
            if (
                not skip_margin_check
                and funds_check is not None
                and funds_check.get("ok") is False
            ):
                shortfall = funds_check.get("shortfall", 0)
                msg = funds_check.get("message") or "Insufficient funds"
                req = funds_check.get("required_margin")
                avail = funds_check.get("available")
                if self.engine_logger:
                    self.engine_logger.log(
                        "order_failed",
                        f"ORDER_FAILED intent_id={intent.intent_id} reason=insufficient_funds "
                        f"required_margin={req} available={avail} shortfall={shortfall} | {msg}",
                        symbol=sym,
                        side=side,
                        qty=qty,
                        intent_id=intent.intent_id,
                        strategy_id=intent_strategy_id,
                        required_margin=req,
                        available=avail,
                        shortfall=shortfall,
                        span_margin=funds_check.get("span_margin"),
                        exec_price=exec_price,
                    )
                self.intent_store.update(
                    intent.intent_id, IntentStatus.REJECTED, order_state=OrderState.REJECTED
                )
                self._set_order_state(
                    intent.intent_id,
                    OrderState.REJECTED,
                    action="insufficient_funds",
                    message=msg,
                )
                return {"ok": False, "retryable": False, "reason": "insufficient_funds"}
        else:
            self._log_oms_step(
                "margin_check",
                intent,
                ok=True,
                message="Margin check skipped for EXIT/FORCE_EXIT",
                intent_strategy_id=intent_strategy_id,
                exec_price=exec_price,
            )

        # Ensure intent exists in store (for fill sync and stale exit refresh)
        if not self.intent_store.exists(intent.intent_id):
            payload = {
                "symbol": sym,
                "side": side,
                "qty": qty,
                "action": getattr(intent, "action", "ENTRY"),
                "order_type": getattr(intent, "order_type", None),
                "engine_id": intent_engine_id,
                "strategy_id": intent_strategy_id,
                "structure_id": getattr(intent, "structure_id", None),
                "tag": getattr(intent, "tag", None),
            }
            _extras = getattr(intent, "metadata_extras", None)
            if _extras is not None:
                payload["strategy_meta"] = _extras
            self.intent_store.create(
                payload=payload,
                intent_id=intent.intent_id,
                idempotency_key=(
                    idempotency_key
                    if idempotency_key is not None
                    else getattr(intent, "idempotency_key", None)
                ),
            )
            rec = self.intent_store.get(intent.intent_id)
            if rec:
                if hasattr(intent, "instrument"):
                    rec["instrument"] = intent.instrument
                rec["strategy"] = intent_strategy_id
                rec["structure_id"] = getattr(intent, "structure_id", None)
                rec["tag"] = getattr(intent, "tag", None)
                rec["action"] = getattr(intent, "action", "ENTRY")

        # Keep intent record metadata in sync when intent already existed (e.g. idempotency retry)
        rec = self.intent_store.get(intent.intent_id)
        if rec:
            rec["strategy"] = intent_strategy_id
            rec["structure_id"] = getattr(intent, "structure_id", None)
            rec["tag"] = getattr(intent, "tag", None)
            rec["action"] = getattr(intent, "action", "ENTRY")
            rec["order_type"] = getattr(intent, "order_type", None)
            if hasattr(intent, "instrument"):
                rec["instrument"] = intent.instrument
            pay = rec.get("payload") or {}
            pay["order_type"] = getattr(intent, "order_type", None)
            if getattr(intent, "structure_id", None) is not None:
                pay["structure_id"] = intent.structure_id
            if getattr(intent, "tag", None) is not None:
                pay["tag"] = intent.tag
            _extras = getattr(intent, "metadata_extras", None)
            if _extras is not None:
                pay["strategy_meta"] = _extras
            rec["payload"] = pay

        # Fix 1: Persistence Before Flight
        self.intent_store.update(intent.intent_id, IntentStatus.VALIDATED)
        self._log_oms_step(
            "intent_validated",
            intent,
            ok=True,
            intent_strategy_id=intent_strategy_id,
            exec_price=exec_price,
            qty=qty,
        )

        self._log_oms_step(
            "place_order_start",
            intent,
            ok=True,
            intent_strategy_id=intent_strategy_id,
            exec_price=exec_price,
            qty=qty,
        )
        if defer_broker_place:
            return {"ok": True, "retryable": False, "reason": "deferred"}
        tag_bracket = str(getattr(intent, "tag", "") or "").upper()
        stid_bracket = getattr(intent, "structure_id", None)
        if tag_bracket == "MAIN_EXIT" and stid_bracket:
            self.bracket_registry.cancel_all_for_structure(
                str(stid_bracket),
                broker=self.broker,
                order_router=self,
                reason="MAIN_EXIT",
            )
        try:
            order_id = self.broker.place_order(intent, execution_price=exec_price)
        except Exception as e:
            broker_fail = getattr(self.broker, "_last_place_order_failure", None) or {}
            if not broker_fail:
                from core.broker.internal.dhan.mappings import parse_dhan_api_error

                parsed = parse_dhan_api_error(e)
                broker_fail = {
                    "message": parsed.get("display_message") or str(e),
                    "error_code": parsed.get("error_code"),
                    "error_type": parsed.get("error_type"),
                    "error_message": parsed.get("error_message"),
                }
            fail_fields = self._broker_failure_log_fields(broker_fail, default=str(e))
            retryable = (
                fail_fields["retryable"]
                if fail_fields.get("retryable") is not None
                else self._is_retryable_broker_error(e)
            )
            self._consecutive_failures += 1
            self._log_oms_step(
                "place_order",
                intent,
                ok=False,
                message=fail_fields["fail_detail"],
                intent_strategy_id=intent_strategy_id,
                exec_price=exec_price,
                reason=fail_fields["reason"],
                broker_payload=broker_fail.get("payload"),
                **{
                    k: fail_fields[k]
                    for k in (
                        "broker_error",
                        "broker_error_code",
                        "broker_error_message",
                        "broker_error_type",
                    )
                },
            )
            if self.engine_logger:
                self.engine_logger.log(
                    "order_failed",
                    (
                        f"ORDER_FAILED intent_id={intent.intent_id} "
                        f"reason={fail_fields['reason']} "
                        f"error={fail_fields['fail_detail']}"
                    ),
                    symbol=sym,
                    side=side,
                    qty=qty,
                    intent_id=getattr(intent, "intent_id", None),
                    strategy_id=intent_strategy_id,
                    broker_payload=broker_fail.get("payload"),
                    broker_error=fail_fields["broker_error"],
                    broker_error_code=fail_fields.get("broker_error_code"),
                    broker_error_message=fail_fields.get("broker_error_message"),
                    broker_error_type=fail_fields.get("broker_error_type"),
                )
            # Always terminalize before any raise so order-state checks do not
            # treat this intent as forever-missing on the broker open book.
            self.intent_store.update(
                intent.intent_id,
                IntentStatus.REJECTED,
                order_state=OrderState.REJECTED,
            )
            self._set_order_state(
                intent.intent_id,
                OrderState.REJECTED,
                action="broker_error",
                message=f"place_order failed: {e}",
            )
            if retryable and raise_on_retryable_failure:
                raise RuntimeError(
                    f"retryable_broker_error: {fail_fields['fail_detail']}"
                ) from e
            if (
                self._consecutive_failures >= self.circuit_breaker_threshold
                and self.risk
            ):
                self.risk.trigger_kill_switch("broker_failure")
                if self.engine_logger:
                    self.engine_logger.broker_circuit_breaker_triggered(
                        "broker_failure"
                    )
            return {"ok": False, "retryable": retryable, "reason": "broker_error"}

        if order_id is None:
            self._consecutive_failures += 1
            broker_fail = getattr(self.broker, "_last_place_order_failure", None) or {}
            fail_fields = self._broker_failure_log_fields(broker_fail)
            fail_payload = broker_fail.get("payload")
            fail_msg = fail_fields["fail_detail"]
            if fail_payload:
                fail_msg = f"{fail_msg} | payload={fail_payload}"
            retryable = bool(fail_fields.get("retryable", True))
            if self._failure_is_no_open_position(
                broker_fail, fail_msg
            ) and self._intent_is_broker_flat_sync_candidate(intent):
                return self._handle_broker_no_open_position(
                    [intent],
                    message=fail_msg,
                )
            self._log_oms_step(
                "place_order",
                intent,
                ok=False,
                message=fail_msg,
                intent_strategy_id=intent_strategy_id,
                exec_price=exec_price,
                reason=fail_fields["reason"],
                broker_error=fail_fields["broker_error"],
                broker_error_code=fail_fields.get("broker_error_code"),
                broker_error_message=fail_fields.get("broker_error_message"),
                broker_error_type=fail_fields.get("broker_error_type"),
                broker_payload=fail_payload,
            )
            if self.engine_logger:
                self.engine_logger.log(
                    "order_failed",
                    (
                        f"ORDER_FAILED intent_id={intent.intent_id} "
                        f"reason={fail_fields['reason']} error={fail_fields['fail_detail']}"
                    ),
                    symbol=sym,
                    side=side,
                    qty=qty,
                    intent_id=getattr(intent, "intent_id", None),
                    strategy_id=intent_strategy_id,
                    broker_payload=fail_payload,
                    broker_error=fail_fields["broker_error"],
                    broker_error_code=fail_fields.get("broker_error_code"),
                    broker_error_message=fail_fields.get("broker_error_message"),
                    broker_error_type=fail_fields.get("broker_error_type"),
                )
            else:
                logger.warning(
                    "Broker place_order failed for %s %s qty=%s: %s",
                    sym,
                    side,
                    qty,
                    fail_fields["fail_detail"],
                )
            # Terminalize first: no_order_id must not linger as SENT/VALIDATED
            # (that caused perpetual order_state_mismatch + reconcile spam).
            self.intent_store.update(
                intent.intent_id,
                IntentStatus.REJECTED,
                order_state=OrderState.REJECTED,
            )
            self._set_order_state(
                intent.intent_id,
                OrderState.REJECTED,
                action="broker_no_order_id",
                message=fail_fields["fail_detail"],
            )
            if retryable and raise_on_retryable_failure:
                raise RuntimeError(
                    f"retryable_broker_error: {fail_fields['reason']}"
                )
            if (
                self._consecutive_failures >= self.circuit_breaker_threshold
                and self.risk
            ):
                self.risk.trigger_kill_switch("broker_failure")
                if self.engine_logger:
                    self.engine_logger.broker_circuit_breaker_triggered(
                        "broker_failure"
                    )
            return {
                "ok": False,
                "retryable": retryable,
                "reason": fail_fields["reason"],
            }

        self._consecutive_failures = 0
        self._log_oms_step(
            "place_order",
            intent,
            ok=True,
            intent_strategy_id=intent_strategy_id,
            exec_price=exec_price,
            order_id=order_id,
            reason="order_placed",
        )
        if stid_bracket and tag_bracket in BRACKET_TAGS:
            self.bracket_registry.register_structure(str(stid_bracket))
            self.bracket_registry.link_leg(
                str(stid_bracket),
                tag_bracket,
                intent_id=intent.intent_id,
                broker_order_id=str(order_id),
            )
        # Paper/sim broker may call process_fill inside place_order, so intent can already be FILLED.
        # Do not overwrite terminal status with SENT so has_pending_intent stays correct.
        rec = self.intent_store.get(intent.intent_id)
        already_terminal = rec and rec.get("status") in (
            IntentStatus.FILLED,
            IntentStatus.REJECTED,
            IntentStatus.CANCELLED,
            IntentStatus.EXPIRED,
        )
        if not already_terminal:
            self._set_order_state(
                intent.intent_id,
                OrderState.SENT,
                action="order_placed",
                message=f"order_id={order_id}",
            )
            if self.engine_logger:
                self.engine_logger.order_placed(
                    symbol=sym,
                    side=side,
                    qty=qty,
                    price=exec_price,
                    order_id=order_id,
                    intent_id=getattr(intent, "intent_id", None),
                    strategy_id=intent_strategy_id,
                )
            self.intent_store.update(
                intent.intent_id,
                "SENT",
                broker_order_id=order_id,
                order_state=OrderState.SENT,
            )
            if self._intent_is_hybrid_gtt(intent):
                self.gtt_fallback_book.register_from_intent(
                    intent, broker_order_id=order_id
                )
            if getattr(intent, "action", "") == "EXIT":
                sent_rec = self.intent_store.get(intent.intent_id)
                if sent_rec:
                    sent_rec["last_price_update_ts"] = time.time()
        else:
            # Paper/sim filled synchronously: keep status FILLED, still log order_placed for audit.
            if self.engine_logger:
                self.engine_logger.order_placed(
                    symbol=sym,
                    side=side,
                    qty=qty,
                    price=exec_price,
                    order_id=order_id,
                    intent_id=getattr(intent, "intent_id", None),
                    strategy_id=intent_strategy_id,
                )
            self.intent_store.update(
                intent.intent_id,
                rec["status"],
                broker_order_id=order_id,
            )
        broker_sent_ts = time.time()
        return {
            "ok": True,
            "retryable": False,
            "reason": "order_placed",
            "broker_sent_ts": broker_sent_ts,
        }

    def _broker_hedge_fill_gate_enabled(self) -> bool:
        return bool(getattr(self.broker, "supports_hedge_fill_gated_bundles", False))

    @staticmethod
    def _partition_hedge_gated_legs(
        resolved: List[Tuple[Any, float]],
    ) -> Tuple[List[Tuple[Any, float]], List[Tuple[Any, float]]]:
        hedge_legs: List[Tuple[Any, float]] = []
        follow_legs: List[Tuple[Any, float]] = []
        for intent, exec_price in resolved:
            tag_u = str(getattr(intent, "tag", "") or "").upper()
            if tag_u == "HEDGE":
                hedge_legs.append((intent, exec_price))
            else:
                follow_legs.append((intent, exec_price))
        return hedge_legs, follow_legs

    @staticmethod
    def _should_use_dhan_hedge_fill_gate(
        resolved: List[Tuple[Any, float]],
        actions: Set[str],
    ) -> bool:
        if len(resolved) < 2 or not actions <= {"ENTRY"}:
            return False
        tags = {str(getattr(i, "tag", "") or "").upper() for i, _ in resolved}
        return "HEDGE" in tags and bool(tags - {"HEDGE"})

    def _reject_bundle_legs(
        self,
        legs: List[Tuple[Any, float]],
        *,
        reason: str,
        message: str,
        bundle_item: Dict[str, Any],
    ) -> None:
        for intent, _ in legs:
            self.intent_store.update(
                intent.intent_id,
                IntentStatus.REJECTED,
                order_state=OrderState.REJECTED,
            )
            self._set_order_state(
                intent.intent_id,
                OrderState.REJECTED,
                action=reason,
                message=message,
            )
            if self.engine_logger:
                self.engine_logger.log(
                    "order_failed",
                    (
                        f"ORDER_FAILED intent_id={intent.intent_id} "
                        f"reason={reason} bundle=true | {message}"
                    ),
                    intent_id=intent.intent_id,
                    strategy_id=bundle_item.get("strategy_id"),
                    structure_id=bundle_item.get("structure_id"),
                )

    def _log_bundle_margin_check(
        self,
        *,
        bundle_item: Dict[str, Any],
        resolved: List[Tuple[Any, float]],
        bundle_margin: Optional[Dict[str, Any]],
        label: str,
    ) -> bool:
        if bundle_margin is None:
            return True
        margin_ok = bool(bundle_margin.get("ok", True))
        primary = resolved[0][0]
        self._log_oms_step(
            "margin_check",
            primary,
            ok=margin_ok,
            message=bundle_margin.get("message")
            or (f"{label} margin_ok" if margin_ok else "insufficient_funds"),
            intent_strategy_id=getattr(primary, "strategy_id", None)
            or bundle_item.get("strategy_id"),
            required_margin=bundle_margin.get("required_margin"),
            available=bundle_margin.get("available"),
            shortfall=bundle_margin.get("shortfall"),
            span_margin=bundle_margin.get("span_margin"),
            reason="insufficient_funds" if not margin_ok else None,
        )
        if self.engine_logger:
            self.engine_logger.log(
                "oms",
                (
                    f"Bundle margin_check {label} legs={len(resolved)} "
                    f"ok={margin_ok} required={bundle_margin.get('required_margin')} "
                    f"available={bundle_margin.get('available')} "
                    f"hedge_benefit={bundle_margin.get('hedge_benefit')}"
                ),
                strategy_id=bundle_item.get("strategy_id"),
                structure_id=bundle_item.get("structure_id"),
            )
        return margin_ok

    def _poll_and_sync_intent_terminal(
        self, intent_record: Dict[str, Any]
    ) -> Optional[OrderState]:
        """Poll broker for one intent; sync fill/reject into intent_store when terminal."""
        tag = intent_record.get("intent_id")
        if not tag:
            return None
        cached = self._order_state.get(tag)
        if cached in _TERMINAL_ORDER_STATES:
            return cached

        order = self._find_broker_order_for_intent(intent_record)
        if not order:
            return None
        order = self._normalize_broker_order_for_recon(order)
        status = (order.get("status") or "").lower()
        filled = float(order.get("filled_size") or 0)
        size = float(order.get("size") or 0)
        avg_px = float(
            order.get("average_fill_price")
            or order.get("averageTradedPrice")
            or order.get("average_traded_price")
            or intent_record.get("price")
            or 0
        )

        if status in ("cancelled", "rejected", "expired"):
            ost = (
                OrderState.CANCELLED
                if status == "cancelled"
                else OrderState.EXPIRED
                if status == "expired"
                else OrderState.REJECTED
            )
            intent_st = (
                IntentStatus.CANCELLED
                if status == "cancelled"
                else IntentStatus.EXPIRED
                if status == "expired"
                else IntentStatus.REJECTED
            )
            self._set_order_state(
                tag,
                ost,
                action=f"sync_{status}",
                message=f"Polling discovered {status}",
            )
            self.intent_store.update(
                tag,
                intent_st,
                broker_order_id=order.get("order_id"),
                order_state=ost,
            )
            return ost

        is_filled = status in ("filled", "traded", "complete", "completed") or (
            size > 0 and filled >= size
        )
        if is_filled:
            payload = intent_record.get("payload") or {}
            action_eff = intent_record.get("action") or payload.get("action")
            fill_qty = filled if filled > 0 else size
            if self.position_manager and fill_qty > 0:
                stid0 = intent_record.get("structure_id") or payload.get("structure_id")
                if not self._terminal_fill_reflected_in_pm(
                    intent_record.get("instrument"),
                    intent_record.get("side"),
                    int(fill_qty),
                    str(action_eff or ""),
                    tag,
                    structure_id=stid0,
                ):
                    self.process_fill(
                        instrument=intent_record.get("instrument"),
                        side=intent_record.get("side"),
                        qty=fill_qty,
                        price=avg_px,
                        order_id=order.get("order_id"),
                        intent_id=tag,
                        strategy=intent_record.get("strategy"),
                        structure_id=stid0,
                        tag=intent_record.get("tag"),
                        candle_ts=intent_record.get("candle_ts"),
                        action=action_eff,
                    )
            self._set_order_state(
                tag,
                OrderState.FILLED,
                action="sync_filled",
                message="Polling discovered fill",
            )
            self.intent_store.update(
                tag,
                IntentStatus.FILLED,
                broker_order_id=order.get("order_id"),
                order_state=OrderState.FILLED,
            )
            self._last_applied_filled_by_intent[tag] = float(fill_qty)
            return OrderState.FILLED

        if size > 0 and filled > 0 and filled < size:
            self._set_order_state(
                tag,
                OrderState.PARTIAL,
                action="sync_partial",
                message=f"Polling: partial fill filled={filled} size={size}",
            )
            self.intent_store.update(
                tag,
                IntentStatus.SENT,
                broker_order_id=order.get("order_id"),
                order_state=OrderState.PARTIAL,
            )
        return None

    def _await_intent_terminal(
        self,
        intent_id: str,
        *,
        timeout_sec: float,
        poll_interval: float,
    ) -> Dict[str, Any]:
        deadline = time.time() + timeout_sec
        while time.time() < deadline:
            rec = self.intent_store.get(intent_id)
            if not rec:
                return {
                    "ok": False,
                    "status": "missing",
                    "reason": "intent_not_found",
                    "retryable": False,
                }
            ost = self._order_state.get(intent_id)
            if ost == OrderState.FILLED:
                return {"ok": True, "status": "filled", "reason": "filled", "retryable": False}
            if ost in (
                OrderState.REJECTED,
                OrderState.CANCELLED,
                OrderState.EXPIRED,
            ):
                return {
                    "ok": False,
                    "status": str(ost.value).lower(),
                    "reason": str(ost.value).lower(),
                    "retryable": False,
                }
            synced = self._poll_and_sync_intent_terminal(rec)
            if synced == OrderState.FILLED:
                return {"ok": True, "status": "filled", "reason": "filled", "retryable": False}
            if synced in (
                OrderState.REJECTED,
                OrderState.CANCELLED,
                OrderState.EXPIRED,
            ):
                return {
                    "ok": False,
                    "status": str(synced.value).lower(),
                    "reason": str(synced.value).lower(),
                    "retryable": False,
                }
            time.sleep(max(0.05, float(poll_interval)))
        return {
            "ok": False,
            "status": "timeout",
            "reason": "hedge_fill_timeout",
            "retryable": False,
        }

    def _hedge_fill_retry_enabled(self, bundle_item: Dict[str, Any]) -> bool:
        if not self._broker_hedge_fill_gate_enabled():
            return False
        if not bool(getattr(self.broker, "hedge_fill_retry_enabled", True)):
            return False
        sid = str(bundle_item.get("strategy_id") or "").strip()
        allowed = getattr(self.broker, "hedge_fill_retry_strategy_ids", None)
        if allowed is None:
            return True
        if isinstance(allowed, (set, frozenset, list, tuple)):
            if not allowed:
                return True
            return sid in allowed
        return False

    def _mark_hedge_intent_cancelled(
        self,
        hedge_intent: Any,
        *,
        reason: str,
        message: str,
        bundle_item: Dict[str, Any],
    ) -> None:
        intent_id = str(getattr(hedge_intent, "intent_id", "") or "")
        if not intent_id:
            return
        self.intent_store.update(
            intent_id,
            IntentStatus.CANCELLED,
            order_state=OrderState.CANCELLED,
        )
        self._set_order_state(
            intent_id,
            OrderState.CANCELLED,
            action=reason,
            message=message,
        )
        if self.engine_logger:
            self.engine_logger.log(
                "order_failed",
                (
                    f"ORDER_CANCELLED intent_id={intent_id} "
                    f"reason={reason} bundle=true | {message}"
                ),
                intent_id=intent_id,
                strategy_id=bundle_item.get("strategy_id"),
                structure_id=bundle_item.get("structure_id"),
            )

    def _cancel_hedge_intent_and_verify(
        self,
        hedge_intent: Any,
        *,
        bundle_item: Dict[str, Any],
        timeout_sec: float,
        poll_interval: float,
    ) -> Dict[str, Any]:
        """
        Cancel a resting hedge limit after fill timeout; poll broker until terminal.

        Returns ``filled=True`` if the hedge filled during cancel (caller may continue MAIN).
        """
        intent_id = str(getattr(hedge_intent, "intent_id", "") or "")
        if not intent_id:
            return {"ok": True, "filled": False, "cancelled": False}

        ost = self._order_state.get(intent_id)
        if ost == OrderState.FILLED:
            return {"ok": True, "filled": True, "cancelled": False}

        rec = self.intent_store.get(intent_id) if self.intent_store else None
        broker_oid = (rec or {}).get("broker_order_id")
        cancel_fn = getattr(self.broker, "cancel_order_by_id", None)
        is_open_fn = getattr(self.broker, "order_is_open", None)

        if broker_oid and callable(is_open_fn) and is_open_fn(str(broker_oid)):
            if callable(cancel_fn):
                cancel_fn(
                    str(broker_oid),
                    intent_id=intent_id,
                    reason="hedge_fill_timeout",
                )
                if self.engine_logger:
                    self.engine_logger.log(
                        "oms",
                        (
                            f"Hedge cancel on bundle fail intent_id={intent_id} "
                            f"order_id={broker_oid}"
                        ),
                        intent_id=intent_id,
                        strategy_id=bundle_item.get("strategy_id"),
                        structure_id=bundle_item.get("structure_id"),
                    )
            deadline = time.time() + max(1.0, float(timeout_sec))
            while time.time() < deadline:
                rec = self.intent_store.get(intent_id) if self.intent_store else rec
                if rec:
                    synced = self._poll_and_sync_intent_terminal(rec)
                    if synced == OrderState.FILLED:
                        return {"ok": True, "filled": True, "cancelled": False}
                    if synced in (
                        OrderState.CANCELLED,
                        OrderState.REJECTED,
                        OrderState.EXPIRED,
                    ):
                        return {"ok": True, "filled": False, "cancelled": True}
                ost = self._order_state.get(intent_id)
                if ost == OrderState.FILLED:
                    return {"ok": True, "filled": True, "cancelled": False}
                if ost in (
                    OrderState.CANCELLED,
                    OrderState.REJECTED,
                    OrderState.EXPIRED,
                ):
                    return {"ok": True, "filled": False, "cancelled": True}
                if (
                    broker_oid
                    and callable(is_open_fn)
                    and not is_open_fn(str(broker_oid))
                ):
                    remaining = max(0.05, deadline - time.time())
                    wait = self._await_intent_terminal(
                        intent_id,
                        timeout_sec=remaining,
                        poll_interval=poll_interval,
                    )
                    if wait.get("ok"):
                        return {"ok": True, "filled": True, "cancelled": False}
                    return {"ok": True, "filled": False, "cancelled": True}
                time.sleep(max(0.05, float(poll_interval)))
            return {
                "ok": False,
                "filled": False,
                "cancelled": False,
                "reason": "cancel_verify_timeout",
            }

        if rec:
            synced = self._poll_and_sync_intent_terminal(rec)
            if synced == OrderState.FILLED:
                return {"ok": True, "filled": True, "cancelled": False}
        return {"ok": True, "filled": False, "cancelled": False}

    def _refresh_bundle_entry_prices(
        self,
        bundle_item: Dict[str, Any],
        intents: List[Any],
        price_map: Dict[str, float],
    ) -> bool:
        refresher = self.bundle_price_refresher
        if not callable(refresher):
            return False
        try:
            refresher(bundle_item, intents, price_map)
            return True
        except Exception as exc:
            logger.warning("bundle_price_refresher failed: %s", exc)
            return False

    def _reprice_resolved_list(
        self,
        resolved: List[Tuple[Any, float]],
        price_map: Dict[str, float],
    ) -> List[Tuple[Any, float]]:
        out: List[Tuple[Any, float]] = []
        for intent, _ in resolved:
            sym = (
                getattr(intent.instrument, "trading_symbol", None)
                if getattr(intent, "instrument", None)
                else ""
            )
            exec_price = self._lookup_price_map(price_map, intent, sym)
            if exec_price is None:
                exec_price = getattr(intent, "price", None)
            exec_price = self._coerce_positive_exec_price(exec_price)
            if exec_price is not None:
                exec_price = self.slippage_model(exec_price)
                if sym:
                    price_map[sym] = exec_price
                try:
                    intent.price = exec_price
                except Exception:
                    pass
            out.append((intent, exec_price))
        return out

    def _prepare_intent_reorder(self, intent_id: str) -> None:
        if self.intent_store and self.intent_store.prepare_reorder(intent_id):
            self._order_state[intent_id] = OrderState.NEW
            self._last_applied_filled_by_intent.pop(intent_id, None)

    def _submit_hedge_with_retry_price(
        self,
        intent: Any,
        exec_price: Optional[float],
        price_map: Dict[str, float],
        *,
        attempt: int,
        idempotency_key: Optional[str],
        raise_on_retryable_failure: bool,
        skip_margin_check: bool,
        bundle_item: Dict[str, Any],
    ) -> Dict[str, Any]:
        intent_id = str(getattr(intent, "intent_id", "") or "")
        rec = self.intent_store.get(intent_id) if self.intent_store else None
        broker_oid = (rec or {}).get("broker_order_id")
        ost = self._order_state.get(intent_id)

        if ost == OrderState.FILLED:
            return {"ok": True, "retryable": False, "reason": "already_filled"}

        modify_fn = getattr(self.broker, "modify_order_price", None)
        is_open_fn = getattr(self.broker, "order_is_open", None)
        cancel_fn = getattr(self.broker, "cancel_order_by_id", None)

        if attempt > 1:
            if broker_oid and callable(is_open_fn) and is_open_fn(str(broker_oid)):
                if (
                    exec_price is not None
                    and callable(modify_fn)
                    and modify_fn(intent, str(broker_oid), exec_price)
                ):
                    if self.engine_logger:
                        self.engine_logger.log(
                            "oms",
                            (
                                f"Hedge retry modify attempt={attempt} "
                                f"intent_id={intent_id} price={exec_price}"
                            ),
                            intent_id=intent_id,
                            strategy_id=bundle_item.get("strategy_id"),
                            structure_id=bundle_item.get("structure_id"),
                        )
                    return {"ok": True, "retryable": False, "reason": "hedge_modified"}
                if callable(cancel_fn):
                    cancel_fn(
                        str(broker_oid),
                        intent_id=intent_id,
                        reason="hedge_retry_requote",
                    )
                self._prepare_intent_reorder(intent_id)
            elif ost in (
                OrderState.REJECTED,
                OrderState.CANCELLED,
                OrderState.EXPIRED,
                OrderState.SENT,
                OrderState.PARTIAL,
                OrderState.OPEN,
            ):
                if broker_oid and callable(cancel_fn):
                    cancel_fn(
                        str(broker_oid),
                        intent_id=intent_id,
                        reason="hedge_retry_requote",
                    )
                self._prepare_intent_reorder(intent_id)

        if exec_price is None:
            return {"ok": False, "retryable": False, "reason": "no_price"}

        return self.process_intent(
            intent,
            price_map,
            idempotency_key=idempotency_key,
            raise_on_retryable_failure=raise_on_retryable_failure,
            skip_margin_check=skip_margin_check,
        )

    def _process_dhan_hedge_gated_bundle(
        self,
        bundle_item: Dict[str, Any],
        resolved: List[Tuple[Any, float]],
        *,
        raise_on_retryable_failure: bool = False,
    ) -> Dict[str, Any]:
        """
        Dhan: place HEDGE BUY, wait for fill, re-check margin with open positions,
        then place MAIN / follow legs so RMS sees the hedge in portfolio.
        """
        price_map = dict(bundle_item.get("price_map") or {})
        idempotency_key = bundle_item.get("idempotency_key")
        hedge_legs, follow_legs = self._partition_hedge_gated_legs(resolved)
        if not hedge_legs or not follow_legs:
            return {"ok": False, "retryable": False, "reason": "invalid_hedge_bundle"}

        retry_enabled = self._hedge_fill_retry_enabled(bundle_item)
        max_attempts = (
            int(getattr(self.broker, "hedge_fill_retry_max_attempts", 3) or 3)
            if retry_enabled
            else 1
        )
        per_attempt_sec = float(
            getattr(self.broker, "hedge_fill_retry_per_attempt_sec", 40.0) or 40.0
            if retry_enabled
            else getattr(self.broker, "hedge_fill_wait_timeout_sec", 120.0) or 120.0
        )
        poll_interval = float(
            getattr(self.broker, "hedge_fill_poll_interval_sec", 0.5) or 0.5
        )
        multi_check = getattr(self.broker, "check_funds_before_orders", None)

        if multi_check and hedge_legs:
            hedge_margin = multi_check(hedge_legs)
            if not self._log_bundle_margin_check(
                bundle_item=bundle_item,
                resolved=hedge_legs,
                bundle_margin=hedge_margin,
                label="hedge_pre",
            ):
                msg = (hedge_margin or {}).get("message") or "Insufficient funds for hedge"
                self._reject_bundle_legs(
                    hedge_legs + follow_legs,
                    reason="insufficient_funds",
                    message=msg,
                    bundle_item=bundle_item,
                )
                return {"ok": False, "retryable": False, "reason": "insufficient_funds"}

        broker_sent_ts = None
        all_intents = [i for i, _ in hedge_legs + follow_legs]
        for hedge_intent, _ in hedge_legs:
            hedge_filled = False
            last_wait: Dict[str, Any] = {"ok": False, "reason": "hedge_fill_failed"}
            for attempt in range(1, max_attempts + 1):
                if retry_enabled:
                    self._refresh_bundle_entry_prices(
                        bundle_item, all_intents, price_map
                    )
                    resolved = self._reprice_resolved_list(resolved, price_map)
                    hedge_legs, follow_legs = self._partition_hedge_gated_legs(resolved)
                    hedge_intent, hedge_price = hedge_legs[0]
                else:
                    hedge_price = hedge_legs[0][1]

                result = self._submit_hedge_with_retry_price(
                    hedge_intent,
                    hedge_price,
                    price_map,
                    attempt=attempt,
                    idempotency_key=idempotency_key,
                    raise_on_retryable_failure=raise_on_retryable_failure,
                    skip_margin_check=bool(multi_check),
                    bundle_item=bundle_item,
                )
                if not result.get("ok", True):
                    last_wait = {
                        "ok": False,
                        "status": "place_failed",
                        "reason": str(result.get("reason") or "hedge_place_failed"),
                    }
                    if attempt >= max_attempts:
                        self._reject_bundle_legs(
                            follow_legs,
                            reason=last_wait["reason"],
                            message="Hedge leg failed; follow legs not sent",
                            bundle_item=bundle_item,
                        )
                        return result
                    time.sleep(max(0.05, poll_interval))
                    continue

                broker_sent_ts = result.get("broker_sent_ts") or broker_sent_ts
                wait = self._await_intent_terminal(
                    hedge_intent.intent_id,
                    timeout_sec=per_attempt_sec,
                    poll_interval=poll_interval,
                )
                last_wait = wait
                if self.engine_logger:
                    self.engine_logger.log(
                        "oms",
                        (
                            f"Hedge fill_gate attempt={attempt}/{max_attempts} "
                            f"intent_id={hedge_intent.intent_id} ok={wait.get('ok')} "
                            f"status={wait.get('status')} reason={wait.get('reason')}"
                        ),
                        intent_id=hedge_intent.intent_id,
                        strategy_id=bundle_item.get("strategy_id"),
                        structure_id=bundle_item.get("structure_id"),
                    )
                if wait.get("ok"):
                    hedge_filled = True
                    break
                if attempt < max_attempts and retry_enabled:
                    continue

            if not hedge_filled:
                cancel_on_fail = bool(
                    getattr(self.broker, "hedge_fill_cancel_on_failure", True)
                )
                verify_sec = float(
                    getattr(self.broker, "hedge_fill_cancel_verify_sec", 15.0) or 15.0
                )
                if cancel_on_fail:
                    for hedge_intent, _ in hedge_legs:
                        cr = self._cancel_hedge_intent_and_verify(
                            hedge_intent,
                            bundle_item=bundle_item,
                            timeout_sec=verify_sec,
                            poll_interval=poll_interval,
                        )
                        if cr.get("filled"):
                            hedge_filled = True
                            if self.engine_logger:
                                self.engine_logger.log(
                                    "oms",
                                    (
                                        f"Hedge filled during cancel verify "
                                        f"intent_id={hedge_intent.intent_id}; "
                                        "continuing with MAIN"
                                    ),
                                    intent_id=hedge_intent.intent_id,
                                    strategy_id=bundle_item.get("strategy_id"),
                                    structure_id=bundle_item.get("structure_id"),
                                )
                            break
                        fail_reason = str(
                            last_wait.get("reason") or "hedge_fill_failed"
                        )
                        if cr.get("cancelled"):
                            self._mark_hedge_intent_cancelled(
                                hedge_intent,
                                reason=fail_reason,
                                message=(
                                    "Hedge order cancelled after fill timeout; "
                                    "follow legs not sent"
                                ),
                                bundle_item=bundle_item,
                            )
                        elif not cr.get("ok"):
                            logger.warning(
                                "Hedge cancel verify failed intent_id=%s reason=%s; "
                                "order may still be live at broker",
                                hedge_intent.intent_id,
                                cr.get("reason"),
                            )
                            if self.engine_logger:
                                self.engine_logger.log(
                                    "oms",
                                    (
                                        f"Hedge cancel verify failed "
                                        f"intent_id={hedge_intent.intent_id} "
                                        f"reason={cr.get('reason')}"
                                    ),
                                    intent_id=hedge_intent.intent_id,
                                    strategy_id=bundle_item.get("strategy_id"),
                                    structure_id=bundle_item.get("structure_id"),
                                )

            if not hedge_filled:
                msg = (
                    f"Hedge leg did not fill (status={last_wait.get('status')}); "
                    "follow legs not sent"
                )
                self._reject_bundle_legs(
                    follow_legs,
                    reason=str(last_wait.get("reason") or "hedge_fill_failed"),
                    message=msg,
                    bundle_item=bundle_item,
                )
                return {
                    "ok": False,
                    "retryable": False,
                    "reason": last_wait.get("reason") or "hedge_fill_failed",
                }

        settle_sec = float(
            getattr(self.broker, "hedge_fill_margin_settle_sec", 0.5) or 0.0
        )
        if settle_sec > 0:
            time.sleep(settle_sec)

        if retry_enabled:
            self._refresh_bundle_entry_prices(bundle_item, all_intents, price_map)
            resolved = self._reprice_resolved_list(resolved, price_map)
            hedge_legs, follow_legs = self._partition_hedge_gated_legs(resolved)

        follow_margin: Optional[Dict[str, Any]] = None
        if multi_check and follow_legs:
            # After hedge fill: MAIN-only check MUST include open positions so Dhan
            # applies hedge benefit (Final Margin), not standalone short margin.
            follow_margin = multi_check(
                follow_legs,
                include_position=True,
                include_orders=True,
            )
            if follow_margin is None:
                # Fallback: theoretical combined structure margin (matches strategy builder).
                follow_margin = multi_check(
                    hedge_legs + follow_legs,
                    include_position=False,
                    include_orders=False,
                )
            if not self._log_bundle_margin_check(
                bundle_item=bundle_item,
                resolved=follow_legs,
                bundle_margin=follow_margin,
                label="post_hedge",
            ):
                msg = (
                    (follow_margin or {}).get("message")
                    or "Insufficient funds for main leg after hedge fill"
                )
                self._reject_bundle_legs(
                    follow_legs,
                    reason="insufficient_funds",
                    message=msg,
                    bundle_item=bundle_item,
                )
                return {"ok": False, "retryable": False, "reason": "insufficient_funds"}
            if follow_margin is None:
                # Do not fall through to standalone MAIN margin (ignores hedge).
                self._reject_bundle_legs(
                    follow_legs,
                    reason="margin_check_unavailable",
                    message="Post-hedge margin check unavailable; MAIN not sent",
                    bundle_item=bundle_item,
                )
                return {
                    "ok": False,
                    "retryable": True,
                    "reason": "margin_check_unavailable",
                }

        last_result: Dict[str, Any] = {
            "ok": True,
            "retryable": False,
            "reason": "bundle_placed",
        }
        for intent, _ in follow_legs:
            result = self.process_intent(
                intent,
                price_map,
                idempotency_key=idempotency_key,
                raise_on_retryable_failure=raise_on_retryable_failure,
                skip_margin_check=bool(follow_margin),
                bundle_margin_result=follow_margin,
            )
            last_result = result
            if not result.get("ok", True):
                return result
            broker_sent_ts = result.get("broker_sent_ts") or broker_sent_ts

        if broker_sent_ts is not None:
            last_result["broker_sent_ts"] = broker_sent_ts
        return last_result

    def process_intent_bundle(
        self,
        bundle_item: Dict[str, Any],
        raise_on_retryable_failure: bool = False,
    ) -> Dict[str, Any]:
        """
        Process multiple ENTRY legs (e.g. hedge + main) with one multi-order margin check.
        Delta FORCE_EXIT bracket legs (MAIN_SL + MAIN_TARGET) use one combined bracket API call.
        """
        legs = bundle_item.get("intent_bundle") or []
        if not legs:
            return {"ok": False, "retryable": False, "reason": "empty_bundle"}

        if self._should_use_delta_combined_bracket(legs):
            return self._process_delta_bracket_bundle(
                bundle_item,
                raise_on_retryable_failure=raise_on_retryable_failure,
            )

        price_map = dict(bundle_item.get("price_map") or {})
        idempotency_key = bundle_item.get("idempotency_key")
        resolved: List[Tuple[Any, float]] = []

        for intent in legs:
            sym = (
                getattr(intent.instrument, "trading_symbol", None)
                if getattr(intent, "instrument", None)
                else ""
            )
            exec_price = self._lookup_price_map(price_map, intent, sym)
            if exec_price is None:
                exec_price = getattr(intent, "price", None)
            exec_price = self._coerce_positive_exec_price(exec_price)
            if exec_price is None:
                return {
                    "ok": False,
                    "retryable": False,
                    "reason": "no_price",
                }
            exec_price = self.slippage_model(exec_price)
            if sym:
                price_map[sym] = exec_price
            resolved.append((intent, exec_price))

        actions = {
            str(getattr(i, "action", "ENTRY") or "ENTRY").upper() for i, _ in resolved
        }
        if (
            self._broker_hedge_fill_gate_enabled()
            and self._should_use_dhan_hedge_fill_gate(resolved, actions)
        ):
            return self._process_dhan_hedge_gated_bundle(
                bundle_item,
                resolved,
                raise_on_retryable_failure=raise_on_retryable_failure,
            )

        bundle_margin: Optional[Dict[str, Any]] = None
        if actions <= {"ENTRY"} and len(resolved) > 1:
            multi_check = getattr(
                self.broker, "check_funds_before_orders", None
            )
            if multi_check:
                bundle_margin = multi_check(resolved)
                if bundle_margin is not None:
                    margin_ok = bool(bundle_margin.get("ok", True))
                    primary = resolved[0][0]
                    self._log_oms_step(
                        "margin_check",
                        primary,
                        ok=margin_ok,
                        message=bundle_margin.get("message")
                        or ("margin_ok" if margin_ok else "insufficient_funds"),
                        intent_strategy_id=getattr(primary, "strategy_id", None)
                        or bundle_item.get("strategy_id"),
                        required_margin=bundle_margin.get("required_margin"),
                        available=bundle_margin.get("available"),
                        shortfall=bundle_margin.get("shortfall"),
                        span_margin=bundle_margin.get("span_margin"),
                        reason="insufficient_funds" if not margin_ok else None,
                    )
                    if self.engine_logger:
                        self.engine_logger.log(
                            "oms",
                            (
                                f"Bundle margin_check legs={len(resolved)} "
                                f"ok={margin_ok} required={bundle_margin.get('required_margin')} "
                                f"available={bundle_margin.get('available')} "
                                f"hedge_benefit={bundle_margin.get('hedge_benefit')}"
                            ),
                            strategy_id=bundle_item.get("strategy_id"),
                            structure_id=bundle_item.get("structure_id"),
                        )
                    if not margin_ok:
                        msg = bundle_margin.get("message") or "Insufficient funds"
                        for intent, _ in resolved:
                            self.intent_store.update(
                                intent.intent_id,
                                IntentStatus.REJECTED,
                                order_state=OrderState.REJECTED,
                            )
                            self._set_order_state(
                                intent.intent_id,
                                OrderState.REJECTED,
                                action="insufficient_funds",
                                message=msg,
                            )
                            if self.engine_logger:
                                self.engine_logger.log(
                                    "order_failed",
                                    f"ORDER_FAILED intent_id={intent.intent_id} "
                                    f"reason=insufficient_funds bundle=true | {msg}",
                                    intent_id=intent.intent_id,
                                    strategy_id=bundle_item.get("strategy_id"),
                                    structure_id=bundle_item.get("structure_id"),
                                    required_margin=bundle_margin.get("required_margin"),
                                    available=bundle_margin.get("available"),
                                    shortfall=bundle_margin.get("shortfall"),
                                )
                        return {
                            "ok": False,
                            "retryable": False,
                            "reason": "insufficient_funds",
                        }

        last_result: Dict[str, Any] = {"ok": True, "retryable": False, "reason": "bundle_placed"}
        broker_sent_ts = None
        for intent, _ in resolved:
            result = self.process_intent(
                intent,
                price_map,
                idempotency_key=idempotency_key,
                raise_on_retryable_failure=raise_on_retryable_failure,
                skip_margin_check=bool(bundle_margin),
                bundle_margin_result=bundle_margin,
            )
            last_result = result
            if not result.get("ok", True):
                return result
            broker_sent_ts = result.get("broker_sent_ts") or broker_sent_ts

        if broker_sent_ts is not None:
            last_result["broker_sent_ts"] = broker_sent_ts
        return last_result

    @staticmethod
    def _should_use_delta_combined_bracket(legs: List[Any]) -> bool:
        if len(legs) != 2:
            return False
        tags = {str(getattr(i, "tag", "") or "").upper() for i in legs}
        actions = {str(getattr(i, "action", "") or "").upper() for i in legs}
        return tags == {"MAIN_SL", "MAIN_TARGET"} and actions == {"FORCE_EXIT"}

    def _process_delta_bracket_bundle(
        self,
        bundle_item: Dict[str, Any],
        *,
        raise_on_retryable_failure: bool = False,
    ) -> Dict[str, Any]:
        legs = list(bundle_item.get("intent_bundle") or [])
        price_map = dict(bundle_item.get("price_map") or {})
        idempotency_key = bundle_item.get("idempotency_key")
        sl_intent = next(
            i for i in legs if str(getattr(i, "tag", "")).upper() == "MAIN_SL"
        )
        tgt_intent = next(
            i for i in legs if str(getattr(i, "tag", "")).upper() == "MAIN_TARGET"
        )
        resolved: List[Tuple[Any, float]] = []
        for intent in (sl_intent, tgt_intent):
            sym = (
                getattr(intent.instrument, "trading_symbol", None)
                if getattr(intent, "instrument", None)
                else ""
            )
            exec_price = self._lookup_price_map(price_map, intent, sym)
            if exec_price is None:
                exec_price = getattr(intent, "price", None)
            exec_price = self._coerce_positive_exec_price(exec_price)
            if exec_price is None:
                return {"ok": False, "retryable": False, "reason": "no_price"}
            exec_price = self.slippage_model(exec_price)
            if sym:
                price_map[sym] = exec_price
            resolved.append((intent, exec_price))

        broker = self.broker
        place_fn = getattr(broker, "place_combined_bracket_orders", None)
        if not callable(place_fn):
            last_result: Dict[str, Any] = {
                "ok": True,
                "retryable": False,
                "reason": "bundle_placed",
            }
            broker_sent_ts = None
            for intent, exec_price in resolved:
                result = self.process_intent(
                    intent,
                    price_map,
                    idempotency_key=idempotency_key,
                    raise_on_retryable_failure=raise_on_retryable_failure,
                    skip_margin_check=True,
                )
                last_result = result
                if not result.get("ok", True):
                    return result
                broker_sent_ts = result.get("broker_sent_ts") or broker_sent_ts
            if broker_sent_ts is not None:
                last_result["broker_sent_ts"] = broker_sent_ts
            return last_result

        for intent, exec_price in resolved:
            prep = self.process_intent(
                intent,
                price_map,
                idempotency_key=idempotency_key,
                raise_on_retryable_failure=raise_on_retryable_failure,
                skip_margin_check=True,
                defer_broker_place=True,
            )
            if not prep.get("ok", True):
                return prep

        sl_intent, sl_price = resolved[0]
        tgt_intent, tgt_price = resolved[1]
        combo = place_fn(
            sl_intent,
            tgt_intent,
            sl_execution_price=sl_price,
            target_execution_price=tgt_price,
        )
        if not combo.get("ok"):
            fail_msg = str(
                combo.get("message") or combo.get("reason") or "combined bracket failed"
            )
            broker_fail = getattr(broker, "_last_place_order_failure", None) or {}
            if self._failure_is_no_open_position(combo, fail_msg) or self._failure_is_no_open_position(
                broker_fail, fail_msg
            ):
                return self._handle_broker_no_open_position(
                    [i for i, _ in resolved],
                    message=fail_msg,
                    bundle_item=bundle_item,
                )
            for intent, _ in resolved:
                self.intent_store.update(
                    intent.intent_id,
                    IntentStatus.REJECTED,
                    order_state=OrderState.REJECTED,
                )
                self._set_order_state(
                    intent.intent_id,
                    OrderState.REJECTED,
                    action="broker_no_order_id",
                    message=fail_msg,
                )
            return {
                "ok": False,
                "retryable": bool(combo.get("retryable")),
                "reason": combo.get("reason") or "no_order_id",
            }

        stid = getattr(sl_intent, "structure_id", None)
        broker_sent_ts = time.time()
        leg_orders = {
            "MAIN_SL": combo.get("sl_order_id"),
            "MAIN_TARGET": combo.get("tp_order_id"),
        }
        for intent, exec_price in resolved:
            tag_u = str(getattr(intent, "tag", "") or "").upper()
            order_id = leg_orders.get(tag_u)
            if not order_id:
                continue
            sym = (
                getattr(intent.instrument, "trading_symbol", None)
                if getattr(intent, "instrument", None)
                else ""
            )
            side = getattr(intent, "side", "")
            qty_lots = int(getattr(intent, "qty", 0) or 0)
            intent_strategy_id = (
                getattr(intent, "strategy_id", None)
                or getattr(intent, "strategy_name", None)
                or getattr(intent, "strategy", None)
                or self.strategy_id
            )
            self._log_oms_step(
                "place_order",
                intent,
                ok=True,
                intent_strategy_id=intent_strategy_id,
                exec_price=exec_price,
                order_id=order_id,
                reason=combo.get("reason") or "order_placed",
            )
            if stid and tag_u in BRACKET_TAGS:
                self.bracket_registry.register_structure(str(stid))
                self.bracket_registry.link_leg(
                    str(stid),
                    tag_u,
                    intent_id=intent.intent_id,
                    broker_order_id=str(order_id),
                )
            self._set_order_state(
                intent.intent_id,
                OrderState.SENT,
                action="order_placed",
                message=f"order_id={order_id}",
            )
            if self.engine_logger:
                self.engine_logger.order_placed(
                    symbol=sym,
                    side=side,
                    qty=qty_lots,
                    price=exec_price,
                    order_id=order_id,
                    intent_id=getattr(intent, "intent_id", None),
                    strategy_id=intent_strategy_id,
                )
            self.intent_store.update(
                intent.intent_id,
                IntentStatus.SENT,
                broker_order_id=order_id,
                order_state=OrderState.SENT,
            )

        return {
            "ok": True,
            "retryable": False,
            "reason": combo.get("reason") or "bundle_placed",
            "broker_sent_ts": broker_sent_ts,
        }

    def cancel_unfilled_strategy_orders(
        self,
        strategy_id: str,
        *,
        tags: Optional[Union[str, Iterable[str]]] = None,
        actions: Optional[Union[str, Iterable[str]]] = None,
        trade_date: Optional[Any] = None,
    ) -> int:
        """
        Cancel unfilled broker orders for in-flight intents (SENT/VALIDATED) owned by strategy_id.
        Optionally restrict to structure_id entry dates matching trade_date (date object or iso str).
        """
        if not self.intent_store:
            return 0
        tag_filter = IntentStore._upper_set(tags)
        action_filter = IntentStore._upper_set(actions)
        trade_d: Optional[Any] = None
        if trade_date is not None:
            try:
                if hasattr(trade_date, "isoformat"):
                    trade_d = trade_date
                else:
                    from datetime import date as _date

                    trade_d = _date.fromisoformat(str(trade_date)[:10])
            except (TypeError, ValueError):
                trade_d = None

        pending = list(self.intent_store.list_by_status(IntentStatus.SENT)) + list(
            self.intent_store.list_by_status(IntentStatus.VALIDATED)
        ) + list(self.intent_store.list_by_status(IntentStatus.ACKED))
        cancelled = 0
        for rec in pending:
            payload = rec.get("payload") or {}
            if payload.get("strategy_id") != strategy_id:
                continue
            rec_tag = str(payload.get("tag") or rec.get("tag") or "").upper()
            if tag_filter is not None and rec_tag not in tag_filter:
                continue
            rec_action = str(payload.get("action") or rec.get("action") or "").upper()
            if action_filter is not None and rec_action not in action_filter:
                continue
            structure_id = str(
                rec.get("structure_id") or payload.get("structure_id") or ""
            )
            if trade_d is not None and structure_id:
                parts = structure_id.split(":")
                if len(parts) >= 3:
                    try:
                        from datetime import date as _date

                        sid_dt = _date.fromisoformat(str(parts[2])[:10])
                        if sid_dt != trade_d:
                            continue
                    except (TypeError, ValueError):
                        pass
            intent_id = rec.get("intent_id")
            if not intent_id:
                continue
            broker_order_id = rec.get("broker_order_id")
            if broker_order_id and self.broker and hasattr(
                self.broker, "cancel_order_by_id"
            ):
                ok = self.broker.cancel_order_by_id(
                    str(broker_order_id),
                    intent_id=str(intent_id),
                    reason=f"{strategy_id}_cutoff_cancel",
                )
                if not ok:
                    continue
            self.intent_store.update(
                intent_id,
                IntentStatus.CANCELLED,
                order_state=OrderState.CANCELLED,
            )
            self._set_order_state(
                intent_id,
                OrderState.CANCELLED,
                action="cutoff_cancel",
                message=f"Cancelled unfilled {strategy_id} order at session cutoff",
            )
            if self.engine_logger:
                self.engine_logger.log(
                    "oms",
                    f"Cutoff cancel strategy={strategy_id} intent_id={intent_id} "
                    f"broker_order_id={broker_order_id or 'none'} structure_id={structure_id}",
                    strategy_id=strategy_id,
                    intent_id=intent_id,
                    structure_id=structure_id,
                )
            cancelled += 1
        return cancelled

    def cancel_gtt_fallback_watch(
        self, watch: GttFallbackWatch, *, reason: str = "fallback"
    ) -> bool:
        """Cancel the broker Forever order for a hybrid GTT watch (this leg only)."""
        store = self.intent_store
        if not store or not watch.gtt_intent_id:
            return False
        rec = store.get(watch.gtt_intent_id)
        if not rec:
            return False
        if rec.get("status") == IntentStatus.FILLED:
            return True
        broker_order_id = rec.get("broker_order_id") or watch.broker_order_id
        # Resolve Forever order id from broker if local id missing (avoids
        # marking CANCELLED locally while Forever stays live → duplicate LIMITs).
        if (
            not broker_order_id
            and self.broker
            and hasattr(self.broker, "find_forever_order_by_client_id")
        ):
            try:
                forever = self.broker.find_forever_order_by_client_id(watch.gtt_intent_id)
            except Exception:
                forever = None
            if isinstance(forever, dict):
                broker_order_id = forever.get("order_id") or forever.get("id")
                if broker_order_id:
                    watch.broker_order_id = str(broker_order_id)
        if not broker_order_id:
            logger.warning(
                "GTT cancel skipped — no broker_order_id intent=%s reason=%s",
                watch.gtt_intent_id,
                reason,
            )
            return False
        if self.broker and hasattr(self.broker, "cancel_order_by_id"):
            ok = self.broker.cancel_order_by_id(
                str(broker_order_id),
                intent_id=str(watch.gtt_intent_id),
                reason=reason,
            )
            if not ok:
                return False
        store.update(
            watch.gtt_intent_id,
            IntentStatus.CANCELLED,
            order_state=OrderState.CANCELLED,
        )
        self._set_order_state(
            watch.gtt_intent_id,
            OrderState.CANCELLED,
            action="gtt_fallback_cancel",
            message=reason,
        )
        return True

    def place_gtt_fallback_order(
        self, watch: GttFallbackWatch, *, price: Optional[float] = None
    ) -> Optional[str]:
        """Place resting LIMIT fallback after GTT trigger; returns new intent_id."""
        store = self.intent_store
        if store is None or watch.instrument is None:
            return None
        limit = float(price) if price is not None and float(price) > 0 else float(watch.limit_price)
        meta = dict(watch.metadata_extras or {})
        meta["execution_mode"] = "LIMIT"
        meta["gtt_fallback_parent"] = watch.gtt_intent_id
        fallback = OrderIntent(
            intent_id=uuid.uuid4().hex,
            instrument=watch.instrument,
            side=watch.side,
            qty=int(watch.qty or 1),
            price=limit,
            order_type="LIMIT",
            strategy=watch.strategy_id,
            structure_id=watch.structure_id,
            trade_type="MARGIN",
            tag="MAIN",
            symbol=watch.symbol,
            action="ENTRY",
            candle_ts=watch.candle_ts or datetime.datetime.utcnow(),
            parent_intent_id=watch.gtt_intent_id,
            metadata_extras=meta,
            trigger_price=None,
        )
        sym = watch.trading_symbol
        result = self.process_intent(fallback, {sym: limit})
        if not isinstance(result, dict) or not result.get("ok"):
            return None
        return fallback.intent_id

    # working
    def refresh_stale_exit_orders(
        self,
        get_bid_ask: Callable[[str], Tuple[float, float]],
        stale_seconds: float = 30,
    ) -> None:
        """Re-quote open EXIT / FORCE_EXIT limits at best bid (SELL) or ask (BUY)."""
        self._refresh_stale_limit_orders(
            get_bid_ask=get_bid_ask,
            stale_seconds=stale_seconds,
            action="EXIT",
            label="exit",
        )
        self._refresh_stale_limit_orders(
            get_bid_ask=get_bid_ask,
            stale_seconds=stale_seconds,
            action="FORCE_EXIT",
            label="force_exit",
        )

    def refresh_stale_entry_orders(
        self,
        get_bid_ask: Callable[[str], Tuple[float, float]],
        stale_seconds: float = 30,
    ) -> None:
        """Re-quote open ENTRY limits at best bid for SELL / best ask for BUY."""
        self._refresh_stale_limit_orders(
            get_bid_ask=get_bid_ask,
            stale_seconds=stale_seconds,
            action="ENTRY",
            label="entry",
        )

    def _refresh_stale_limit_orders(
        self,
        *,
        get_bid_ask: Callable[[str], Tuple[float, float]],
        stale_seconds: float,
        action: str,
        label: str,
    ) -> None:
        """Modify matching open limit orders in place; never cancel or duplicate them."""
        if not hasattr(self.broker, "update_order_price"):
            return
        now = time.time()
        action_u = str(action or "").upper()
        sent_orders = [
            i
            for i in self.intent_store.list_by_status(IntentStatus.SENT)
            if str((i.get("payload") or {}).get("action") or "").upper() == action_u
        ]
        for rec in sent_orders:
            intent_id = rec.get("intent_id")
            if not intent_id:
                continue
            payload = rec.get("payload") or {}

            # Use last_price_update_ts so only re-quote interval matters. Fallback to updated_at only when missing (not when 0).
            # Explicit 0 = "always stale" (adopted EXIT orphan from yesterday) so we must not fall back to updated_at.
            raw_ts = rec.get("last_price_update_ts")

            if raw_ts is None:
                last_price_ts = rec.get("updated_at") or 0
            else:
                last_price_ts = raw_ts
            try:
                last_price_ts = float(last_price_ts)
            except (TypeError, ValueError):
                last_price_ts = 0
            if last_price_ts <= 0:
                pass  # Treat as always stale (e.g. adopted orphan from yesterday)
            elif now - last_price_ts < stale_seconds:
                continue

            symbol = self._instrument_trading_symbol(rec.get("instrument")) or (
                (rec.get("payload") or {}).get("symbol") or ""
            )
            # FORCE_EXIT MAIN_SL payload.symbol is often the underlying; always prefer
            # the option trading symbol from the attached instrument.
            if action_u == "FORCE_EXIT":
                inst_sym = self._instrument_trading_symbol(rec.get("instrument"))
                if inst_sym:
                    symbol = inst_sym
            if not symbol:
                if self.engine_logger:
                    self.engine_logger.log(
                        "oms", f"Refresh {label} skip {intent_id}: no symbol"
                    )
                continue
            order_id = rec.get("broker_order_id")
            if not order_id:
                if self.engine_logger:
                    self.engine_logger.log(
                        "oms",
                        f"Refresh {label} skip {intent_id}: no broker_order_id",
                    )
                continue
            broker_order = None
            if hasattr(self.broker, "find_order_by_client_id"):
                broker_order = self.broker.find_order_by_client_id(intent_id)
            if not broker_order:
                if self.engine_logger:
                    self.engine_logger.log(
                        "oms",
                        f"Refresh {label} skip {intent_id}: order not found at broker",
                    )
                continue
            status = (broker_order.get("status") or "").lower()
            open_states = {
                "open",
                "pending",
                "placed",
                "trigger pending",
                "live",
                "untriggered",
            }
            if status not in open_states:
                if self.engine_logger:
                    self.engine_logger.log(
                        "oms",
                        f"Refresh {label} skip {intent_id}: "
                        f"broker status={status} (not open)",
                    )
                continue
            broker_order_id = broker_order.get("order_id")
            if not broker_order_id or str(broker_order_id) != str(order_id):
                if self.engine_logger:
                    self.engine_logger.log(
                        "oms",
                        f"Refresh {label} skip {intent_id}: broker order id mismatch",
                    )
                continue
            remaining_qty = broker_order.get("remaining_qty")
            if remaining_qty is not None:
                try:
                    if float(remaining_qty) <= 0:
                        continue
                except (TypeError, ValueError):
                    continue
            if action_u == "ENTRY":
                order_type = str(
                    payload.get("order_type") or rec.get("order_type") or ""
                ).upper()
                if order_type:
                    if order_type != "LIMIT":
                        continue
                else:
                    # Backward compatibility for intents created before order_type
                    # was persisted: require broker evidence of a plain limit.
                    try:
                        broker_limit = float(broker_order.get("price") or 0)
                    except (TypeError, ValueError):
                        broker_limit = 0
                    if broker_limit <= 0 or broker_order.get("stop_order_type"):
                        continue
            product_id = broker_order.get("product_id")
            if product_id is None:
                if self.engine_logger:
                    self.engine_logger.log(
                        "oms", f"Refresh {label} skip {intent_id}: no product_id"
                    )
                continue
            bid, ask = get_bid_ask(symbol)
            side = (rec.get("side") or rec.get("payload", {}).get("side") or "").upper()
            if side == "SELL":
                new_price = bid
            else:
                new_price = ask
            if new_price is None or new_price <= 0:
                if self.engine_logger:
                    self.engine_logger.log(
                        "oms",
                        f"Refresh {label} skip {intent_id}: no bid/ask for {symbol}",
                    )
                continue
            try:
                ok = self.broker.update_order_price(
                    product_id=int(product_id),
                    order_id=str(broker_order_id),
                    new_limit_price=float(new_price),
                )
                if ok and self.engine_logger:
                    self.engine_logger.log(
                        "oms",
                        f"Refreshed {label} order {intent_id} at {new_price} "
                        f"(best {'bid' if side == 'SELL' else 'ask'})",
                    )
                if ok:
                    self.intent_store.update(intent_id, IntentStatus.SENT)
                    rec = self.intent_store.get(intent_id)
                    if rec:
                        rec["last_price_update_ts"] = now
            except Exception as e:
                if self.engine_logger:
                    self.engine_logger.log(
                        "oms", f"Refresh {label} order failed: {e}"
                    )

    def verify_open_orders_with_broker(self) -> Tuple[bool, Dict]:
        """
        Compare broker open orders with local IntentStore (SENT/VALIDATED).
        Attempts to resolve mismatches by updating local records.
        Returns (ok: bool, details: dict).
        """
        if not hasattr(self.broker, "get_open_orders"):
            return True, {}
        try:
            broker_open_raw = self.broker.get_open_orders()
        except Exception as e:
            if self.engine_logger:
                self.engine_logger.log(
                    "oms",
                    f"Failed to fetch broker open orders: {e}",
                    severity="error",
                )
            else:
                logger.warning("Failed to fetch broker open orders: %s", e)
            return False, {"error": str(e)}

        # Trade-led: sync trades (fills) first so positions are up to date before we compare order state
        self.sync_trades_from_broker()

        # Consider both VALIDATED (in flight) and SENT
        local_pending = self.intent_store.list_by_status(
            IntentStatus.SENT
        ) + self.intent_store.list_by_status(IntentStatus.VALIDATED)
        # Drop intents already terminal in local order-state cache (e.g. place
        # failed / REJECTED but IntentStatus briefly lagged).
        local_pending = [
            i
            for i in local_pending
            if self._order_state.get(i.get("intent_id")) not in _TERMINAL_ORDER_STATES
        ]

        # GTT fills may not appear on regular open-order book; poll Forever + fills API.
        self._sync_gtt_pending_fills(local_pending)

        broker_open = [
            self._normalize_broker_order_for_recon(o)
            for o in (broker_open_raw or [])
            if isinstance(o, dict)
        ]
        broker_open = self._merge_forever_orders_for_recon(broker_open, local_pending)

        local_intent_ids = {
            i.get("intent_id") for i in local_pending if i.get("intent_id")
        }
        broker_tags = {o.get("tag") for o in broker_open if o.get("tag")}
        broker_order_ids = {
            str(o.get("order_id"))
            for o in broker_open
            if o.get("order_id") is not None
        }

        # 1. Orphans: On broker but not in local pending
        # We might have recorded them earlier, so check if they exist AT ALL in intent_store
        orphans = []
        resolved_orphans: Set[str] = set()
        resolved_missing: Set[str] = set()
        now_ts = time.time()
        for o in broker_open:
            tag = str(o.get("tag") or "").strip()
            # Dhan returns literal "NA" for manual / untagged open orders.
            if not tag or tag.upper() in {"NA", "NONE", "NULL", "N/A"}:
                continue
            matched_intent = tag if tag in local_intent_ids else None
            if not matched_intent:
                matched_intent = self._resolve_intent_id_from_broker_order(
                    o, local_pending
                )

            if not self.intent_store.exists(tag) and not (
                matched_intent and self.intent_store.exists(matched_intent)
            ):
                orphans.append(o)
                try:
                    b_sym = o.get("symbol") or o.get("product_symbol")
                    product_id = o.get("product_id")

                    engine_sym = b_sym
                    instr = None
                    if self.instrument_store and b_sym:
                        inst = None
                        if hasattr(self.instrument_store, "get_by_symbol"):
                            inst = self.instrument_store.get_by_symbol(b_sym)
                        if (
                            not inst
                            and product_id
                            and hasattr(self.instrument_store, "get_by_product_id")
                        ):
                            inst = self.instrument_store.get_by_product_id(product_id)
                        if not inst and hasattr(
                            self.instrument_store, "intent_creation_details"
                        ):
                            inst = self.instrument_store.intent_creation_details(
                                b_sym, None, None, None, None
                            )
                        if not inst and hasattr(
                            self.instrument_store, "futures_intent_creation_details"
                        ):
                            inst = self.instrument_store.futures_intent_creation_details(
                                b_sym, "DELTA", None
                            )
                        if inst:
                            engine_sym = inst.trading_symbol
                            instr = inst

                    is_reduce = o.get("reduce_only") in (True, "true", "yes", 1)
                    action = "EXIT" if is_reduce else "ENTRY"
                    stub_payload = {
                        "symbol": engine_sym,
                        "side": (o.get("side") or "").upper(),
                        "qty": int(o.get("qty") or 0),
                        "action": action,
                        "strategy": "recovery",
                        "structure_id": f"recovered:{engine_sym}",
                        "candle_ts": None,
                        "engine_id": self.engine_id,
                        "strategy_id": self.strategy_id,
                    }

                    self.intent_store.create(payload=stub_payload, intent_id=tag)
                    self.intent_store.update(tag, IntentStatus.VALIDATED)
                    self.intent_store.update(
                        tag,
                        IntentStatus.SENT,
                        broker_order_id=o.get("order_id"),
                        order_state=OrderState.OPEN,
                    )
                    self._set_order_state(
                        tag,
                        OrderState.OPEN,
                        action="adopt_orphan",
                        message="Order seen on broker open list; adopted as local intent",
                    )

                    intent_record = self.intent_store.get(tag)
                    if intent_record is None:
                        continue
                    intent_record["instrument"] = instr
                    intent_record["side"] = (o.get("side") or "").upper()
                    intent_record["qty"] = int(o.get("qty") or 0)
                    intent_record["action"] = stub_payload["action"]
                    if action == "EXIT":
                        intent_record["last_price_update_ts"] = 0

                    if self.engine_logger:
                        self.engine_logger.log(
                            "oms", f"Adopted orphan order {tag} for {engine_sym}"
                        )
                    resolved_orphans.add(str(tag))
                except Exception as exc:
                    logger.exception(
                        "Orphan adopt failed tag=%s order_id=%s: %s",
                        tag,
                        o.get("order_id"),
                        exc,
                    )
                    if self.engine_logger:
                        self.engine_logger.log(
                            "oms",
                            f"Orphan adopt failed tag={tag}: {exc}",
                            severity="error",
                        )
                    continue

            elif matched_intent and matched_intent in local_intent_ids:
                # Local thinks it's pending, broker confirms it's open. Sync order ID and persist OPEN.
                tag_key = matched_intent
                self._set_order_state(
                    tag_key,
                    OrderState.OPEN,
                    action="sync_open",
                    message="Broker confirms order is open",
                )
                intent = self.intent_store.get(tag_key)
                self.intent_store.update(
                    tag_key,
                    IntentStatus.SENT,
                    broker_order_id=intent.get("broker_order_id") or o.get("order_id"),
                    order_state=OrderState.OPEN,
                )
                resolved_missing.add(str(tag_key))

        # 2. Missing: In local pending but not on broker open list
        # Usually FILLED/REJECTED/CANCELLED. Only poll broker when cache doesn't have terminal state.
        missing = []
        for i in local_pending:
            intent_id = i.get("intent_id")
            if not intent_id:
                continue
            if self._intent_matched_on_broker_open(
                str(intent_id),
                i.get("broker_order_id"),
                broker_tags,
                broker_order_ids,
            ):
                resolved_missing.add(str(intent_id))
                continue
            payload = i.get("payload") or {}
            action = str(payload.get("action") or i.get("action") or "").upper()
            # FORCE_EXIT (broker-side SL/trigger) may be absent from open/fills APIs
            # until trigger/execution. Delta bracket legs use stop_order_type and may
            # not appear in the normalized open-order book.
            if action == "FORCE_EXIT":
                sym = payload.get("symbol") or i.get("symbol")
                tag = str(payload.get("tag") or i.get("tag") or "").upper()
                # Never got a broker order id → place never succeeded. Do not leave
                # these as perpetual "missing local" mismatches across strategies.
                if not i.get("broker_order_id"):
                    created_at = float(i.get("created_at") or 0.0)
                    grace = min(
                        60.0, float(getattr(self, "_force_exit_pending_max_wait_sec", 300) or 300)
                    )
                    if created_at <= 0 or (now_ts - created_at) >= grace:
                        self._set_order_state(
                            str(intent_id),
                            OrderState.REJECTED,
                            action="force_exit_no_broker_id",
                            message="FORCE_EXIT never received broker_order_id; marking REJECTED",
                        )
                        try:
                            self.intent_store.update(
                                str(intent_id),
                                IntentStatus.REJECTED,
                                order_state=OrderState.REJECTED,
                            )
                        except Exception:
                            pass
                        if self.engine_logger:
                            self.engine_logger.log(
                                "oms",
                                f"FORCE_EXIT {intent_id}: no broker_order_id after "
                                f"{grace:.0f}s; marked REJECTED",
                                strategy_id=self._intent_strategy_id(str(intent_id)),
                                intent_id=str(intent_id),
                            )
                    resolved_missing.add(str(intent_id))
                    continue
                if hasattr(self.broker, "find_order_by_client_id"):
                    try:
                        order = self.broker.find_order_by_client_id(str(intent_id))
                    except Exception:
                        order = None
                    if order:
                        resolved_missing.add(str(intent_id))
                        continue
                has_leg = getattr(self.broker, "has_bracket_leg_on_exchange", None)
                if sym and callable(has_leg) and has_leg(sym, tag):
                    resolved_missing.add(str(intent_id))
                    continue
                created_at = float(i.get("created_at") or 0.0)
                if created_at > 0 and (
                    now_ts - created_at
                ) < self._force_exit_pending_max_wait_sec:
                    resolved_missing.add(str(intent_id))
                    continue
            # GTT: still poll Forever/fills when missing from regular open book (not blind trust).
            if self._intent_is_gtt(i) and i.get("broker_order_id"):
                if self._try_sync_gtt_intent_fill(i):
                    resolved_missing.add(str(intent_id))
                    continue
            missing.append(i)
        missing_needing_poll = [
            i
            for i in missing
            if self._order_state.get(i.get("intent_id")) not in _TERMINAL_ORDER_STATES
        ]

        if missing_needing_poll and hasattr(self.broker, "find_order_by_client_id"):
            time.sleep(0.5)  # Let broker open list settle (recent fills may drop off)

        for i in missing:
            tag = i.get("intent_id")
            if self._order_state.get(tag) in _TERMINAL_ORDER_STATES:
                continue  # Already resolved locally; no broker call
            order = self._find_broker_order_for_intent(i)
            if order:
                try:
                    order = self._normalize_broker_order_for_recon(order)
                    status = (order.get("status") or "").lower()
                    filled = float(order.get("filled_size") or 0.0)
                    size = float(order.get("size") or 0.0)

                    # Partial fill: filled > 0 and unfilled > 0 (filled < size)
                    if size > 0 and filled > 0 and filled < size:
                        prev_cum = float(
                            self._last_applied_filled_by_intent.get(tag, 0.0)
                        )
                        delta = float(filled) - prev_cum
                        self._set_order_state(
                            tag,
                            OrderState.PARTIAL,
                            action="sync_partial",
                            message=f"Polling: filled={filled} delta={delta} size={size}",
                        )
                        self.intent_store.update(
                            tag,
                            IntentStatus.SENT,  # Still in flight
                            broker_order_id=order.get("order_id"),
                            order_state=OrderState.PARTIAL,
                        )
                        if delta > 0 and self.position_manager:
                            self.process_fill(
                                instrument=i.get("instrument"),
                                side=i.get("side"),
                                qty=delta,
                                price=float(
                                    order.get("average_fill_price")
                                    or i.get("price", 0)
                                ),
                                order_id=order.get("order_id"),
                                intent_id=tag,
                                strategy=i.get("strategy"),
                                structure_id=i.get("structure_id"),
                                tag=i.get("tag"),
                                candle_ts=i.get("candle_ts"),
                                action=i.get("action"),
                            )
                            self._last_applied_filled_by_intent[tag] = float(filled)
                        resolved_missing.add(str(tag))
                    elif status == "filled" or (size > 0 and filled >= size):
                        if self.engine_logger:
                            self.engine_logger.log(
                                "oms",
                                f"Syncing fill for {tag} discovered via polling",
                            )

                        if self.position_manager:
                            self.process_fill(
                                instrument=i.get("instrument"),
                                side=i.get("side"),
                                qty=filled,
                                price=float(
                                    order.get("average_fill_price")
                                    or i.get("price", 0)
                                ),
                                order_id=order.get("order_id"),
                                intent_id=tag,
                                strategy=i.get("strategy"),
                                structure_id=i.get("structure_id"),
                                tag=i.get("tag"),
                                candle_ts=i.get("candle_ts"),
                                action=i.get("action"),
                            )
                        self._set_order_state(
                            tag,
                            OrderState.FILLED,
                            action="sync_filled",
                            message="Syncing fill discovered via polling",
                        )
                        self.intent_store.update(
                            tag,
                            IntentStatus.FILLED,
                            broker_order_id=order.get("order_id"),
                            order_state=OrderState.FILLED,
                        )
                        self._last_applied_filled_by_intent[tag] = float(size or filled)
                        resolved_missing.add(str(tag))

                    elif status in ("cancelled", "rejected", "expired"):
                        ost = (
                            OrderState.CANCELLED
                            if status == "cancelled"
                            else (
                                OrderState.REJECTED
                                if status == "rejected"
                                else OrderState.EXPIRED
                            )
                        )
                        ist = (
                            IntentStatus.CANCELLED
                            if status == "cancelled"
                            else IntentStatus.REJECTED
                        )
                        self._set_order_state(
                            tag,
                            ost,
                            action="sync_terminal",
                            message=f"Broker status={status!r}",
                        )
                        self.intent_store.update(tag, ist, order_state=ost)
                        resolved_missing.add(str(tag))
                except Exception as e:
                    if self.engine_logger:
                        self.engine_logger.log(
                            "oms", f"Failed to sync status for {tag}: {e}"
                        )
            else:
                fill_info = None
                if hasattr(self.broker, "get_fill_for_client_order_id"):
                    try:
                        fill_info = self.broker.get_fill_for_client_order_id(tag)
                    except Exception:
                        pass
                if not fill_info and i.get("broker_order_id") and hasattr(
                    self.broker, "get_fill_by_order_id"
                ):
                    try:
                        fill_info = self.broker.get_fill_by_order_id(
                            str(i["broker_order_id"])
                        )
                    except Exception:
                        pass
                if fill_info and float(fill_info.get("price") or 0) > 0:
                    if self._order_state.get(tag) not in _TERMINAL_ORDER_STATES:
                        trade = {
                            "trade_id": f"fill_{tag}_{fill_info.get('order_id', '')}",
                            "order_id": fill_info.get("order_id"),
                            "intent_id": tag,
                            "client_order_id": tag,
                            "tag": tag,
                            "price": float(fill_info["price"]),
                            "size": float(fill_info.get("size") or 0),
                            "side": (fill_info.get("side") or i.get("side") or "").upper(),
                        }
                        if self.process_trade(trade):
                            if self.engine_logger:
                                self.engine_logger.log(
                                    "oms",
                                    f"Missing order {tag}: applied trade from /v2/fills (trade-led)",
                                )
                            resolved_missing.add(str(tag))
                    else:
                        self._set_order_state(
                            tag,
                            OrderState.FILLED,
                            action="assume_filled",
                            message="Fill from API; trade already applied by sync_trades",
                        )
                        self.intent_store.update(
                            tag, IntentStatus.FILLED, order_state=OrderState.FILLED
                        )
                        resolved_missing.add(str(tag))
                elif self._try_resolve_cancelled_bracket_sibling(i):
                    resolved_missing.add(str(tag))
                elif self.engine_logger:
                    self.engine_logger.log(
                        "oms",
                        f"Missing order {tag}: no fill in API; leaving state unchanged (trade-led OMS)",
                        strategy_id=self._intent_strategy_id(str(tag)),
                        intent_id=str(tag),
                    )

        unresolved_orphan_tags = [
            str(o.get("tag"))
            for o in orphans
            if str(o.get("tag")) not in resolved_orphans
        ]
        unresolved_missing_ids = [
            str(i.get("intent_id"))
            for i in missing
            if str(i.get("intent_id")) not in resolved_missing
        ]
        diff = {
            "unresolved_orphan_broker_orders": len(unresolved_orphan_tags),
            "unresolved_missing_local_records": len(unresolved_missing_ids),
        }

        if unresolved_orphan_tags or unresolved_missing_ids:
            if self.engine_logger:
                mismatch_sid = self.strategy_id
                if unresolved_missing_ids:
                    mismatch_sid = (
                        self._intent_strategy_id(unresolved_missing_ids[0])
                        or mismatch_sid
                    )
                elif unresolved_orphan_tags:
                    mismatch_sid = (
                        self._intent_strategy_id(unresolved_orphan_tags[0])
                        or mismatch_sid
                    )
                self.engine_logger.order_state_mismatch(
                    "Order state mismatch detected",
                    details=diff,
                    strategy_id=mismatch_sid,
                    intent_id=(
                        unresolved_missing_ids[0]
                        if unresolved_missing_ids
                        else (
                            unresolved_orphan_tags[0]
                            if unresolved_orphan_tags
                            else None
                        )
                    ),
                )
            return False, diff

        return True, {}

    @staticmethod
    def _normalize_broker_order_for_recon(order: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize broker order payload to stable fields for reconciliation logic."""
        if not isinstance(order, dict):
            return {}

        def _to_float(v: Any) -> float:
            try:
                return float(v)
            except (TypeError, ValueError):
                return 0.0

        order_id = order.get("order_id") or order.get("orderId")
        status = (order.get("status") or order.get("orderStatus") or "").lower()
        tag = order.get("tag") or order.get("intent_id")
        size = _to_float(order.get("size") or order.get("quantity") or order.get("qty"))
        filled = _to_float(
            order.get("filled_size")
            or order.get("filled")
            or order.get("filled_qty")
            or order.get("filledQty")
        )
        unfilled = _to_float(
            order.get("unfilled_size")
            or order.get("remaining_qty")
            or order.get("pending_qty")
        )
        if filled <= 0.0 and size > 0.0 and unfilled > 0.0:
            filled = max(0.0, size - unfilled)

        out = dict(order)
        out["order_id"] = order_id
        out["status"] = status
        out["tag"] = tag
        out["size"] = size
        out["filled_size"] = filled
        out["unfilled_size"] = unfilled
        return out

    @staticmethod
    def _instrument_trading_symbol(inst: Any) -> str:
        """Resolve PM/broker symbol from an Instrument instance or serialized dict."""
        if inst is None:
            return ""
        ts = getattr(inst, "trading_symbol", None)
        if ts:
            return str(ts).strip()
        if isinstance(inst, dict):
            d = inst
            return str(
                d.get("trading_symbol")
                or d.get("tradingsymbol")
                or d.get("tradingSymbol")
                or d.get("symbol")
                or ""
            ).strip()
        return ""

    def _terminal_fill_reflected_in_pm(
        self,
        instrument,
        side: str,
        qty: int,
        action: Optional[str],
        intent_id: Optional[str],
        structure_id: Optional[str] = None,
    ) -> bool:
        """
        True only if PositionManager already matches this terminal fill — safe to skip a duplicate
        broker callback. For ENTRY, prefers structure_id slice match (intent-centric), then legacy net match.
        """
        if not self.position_manager or instrument is None:
            return False
        sym = self._instrument_trading_symbol(instrument)
        if not sym:
            return False
        act = str(action or "").upper()
        q = int(qty)
        sd = str(side or "").upper()
        net = int(self.position_manager.get_qty(sym))
        pos = self.position_manager.positions.get(sym)

        if act == "ENTRY":
            signed_exp = -q if sd == "SELL" else q
            stid = str(structure_id).strip() if structure_id else ""
            if stid:
                slice_q = self.position_manager.get_structure_slice(sym, stid)
                if slice_q != 0 and slice_q == signed_exp:
                    if not intent_id:
                        return False
                    pid = getattr(pos, "intent_id", None) if pos else None
                    pm_mid = (
                        self.position_manager.position_metadata.get(sym) or {}
                    ).get("intent_id")
                    if pid and str(pid) != str(intent_id):
                        return False
                    if not pid and pm_mid and str(pm_mid) != str(intent_id):
                        return False
                    if not pid and not pm_mid:
                        return False
                    return True
            if net == 0:
                return False
            if sd == "SELL":
                ok = net == -q
            elif sd == "BUY":
                ok = net == q
            else:
                return False
            if not ok:
                return False
            if not intent_id:
                return False
            pid = getattr(pos, "intent_id", None) if pos else None
            pm_mid = (self.position_manager.position_metadata.get(sym) or {}).get(
                "intent_id"
            )
            if pid and str(pid) != str(intent_id):
                return False
            if not pid and pm_mid and str(pm_mid) != str(intent_id):
                return False
            if not pid and not pm_mid:
                return False
            return True

        if act in ("EXIT", "FORCE_EXIT"):
            return net == 0

        return False

    def _adopt_main_entry_shadow_fill(
        self,
        instrument,
        intent: Dict[str, Any],
        intent_id: str,
        side: str,
        qty: int,
        price: float,
        order_id: Any,
        trade_id: str,
    ) -> None:
        """
        Broker/reconcile already shows the correct net qty for a MAIN ENTRY, but PM lacked
        intent/metadata (e.g. FILLED was set before on_fill). Attach linkage and run the same
        on_main_entry_fill hook as a normal open — does not change net_qty.
        """
        sym = self._instrument_trading_symbol(instrument)
        if not sym or not self.position_manager:
            return
        payload = intent.get("payload") or {}
        strategy = intent.get("strategy") or payload.get("strategy_id")
        structure_id = intent.get("structure_id") or payload.get("structure_id")
        tag = intent.get("tag") or payload.get("tag") or "MAIN"
        meta_extras = payload.get("strategy_meta")
        iq = int(qty)
        signed = -iq if str(side).upper() == "SELL" else iq
        with self.position_manager._lock:
            self.position_manager._merge_position_metadata(
                sym,
                strategy=strategy,
                structure_id=structure_id,
                tag=tag,
                intent_id=intent_id,
                metadata_extras=meta_extras,
            )
            pos = self.position_manager.positions.get(sym)
            if pos:
                if strategy:
                    pos.strategy = strategy
                if structure_id:
                    pos.structure_id = structure_id
                if tag:
                    pos.tag = tag
                pos.intent_id = intent_id
            if structure_id and str(tag or "").upper() == "MAIN":
                d = self.position_manager._structure_slices.setdefault(sym, {})
                sid = str(structure_id)
                if d.get(sid) in (None, 0):
                    d[sid] = signed
        hook = getattr(self.position_manager, "on_main_entry_fill", None)
        if callable(hook) and str(tag or "").upper() == "MAIN":
            try:
                hook(
                    instrument=instrument,
                    side=side,
                    qty=qty,
                    price=price,
                    strategy=strategy,
                    structure_id=structure_id,
                    tag=tag,
                    action="ENTRY",
                    candle_ts=intent.get("candle_ts"),
                    intent_id=intent_id,
                    metadata_extras=meta_extras,
                )
            except Exception as e:
                logger.warning("on_main_entry_fill after shadow adopt failed: %s", e)
        self._set_order_state(
            intent_id,
            OrderState.FILLED,
            action="adopt_main_entry_shadow",
            message="Metadata + SL hook; qty already at broker",
        )
        self.intent_store.update(
            intent_id,
            IntentStatus.FILLED,
            broker_order_id=order_id,
            order_state=OrderState.FILLED,
        )
        self._processed_trade_ids.add(trade_id)
        if len(self._processed_trade_ids) > getattr(
            self, "_processed_trade_ids_max", 10000
        ):
            self._processed_trade_ids = set(
                list(self._processed_trade_ids)[
                    -self._processed_trade_ids_max // 2 :
                ]
            )
        self.position_manager.note_trade_led_fill(sym)
        self.report_fill(
            sym,
            side,
            int(qty),
            None,
            price,
            order_id=order_id,
            intent_id=intent_id,
            strategy_id=strategy,
        )

    def process_fill(
        self,
        instrument,
        side,
        qty,
        price,
        expected_price=None,
        order_id=None,
        intent_id=None,
        strategy=None,
        structure_id=None,
        tag=None,
        candle_ts=None,
        action=None,
        exit_reason=None,
        execution_source=None,
    ):
        """
        Single entry point for fill processing. Call from broker fill callback or LiveEngine.
        Updates position via PositionManager.on_fill(); if position closed, records realized PnL
        with RiskManager for daily_max_loss enforcement. Then logs and runs slippage check.
        """
        if not self.position_manager:
            self.report_fill(
                self._instrument_trading_symbol(instrument),
                side,
                qty,
                expected_price,
                price,
                order_id=order_id,
                intent_id=intent_id,
                strategy_id=strategy,
            )
            return
        # Skip duplicate callback only when PM already reflects this fill — not merely when
        # intent_store says FILLED (polling used to set FILLED before process_fill, skipping on_fill).
        if intent_id and self.intent_store:
            rec = self.intent_store.get(intent_id)
            if rec:
                st = rec.get("status")
                stv = getattr(st, "value", st)
                ord_state = self._order_state.get(intent_id)
                rec_order_id = rec.get("broker_order_id")
                same_order = (
                    order_id is not None
                    and rec_order_id is not None
                    and str(order_id) == str(rec_order_id)
                )
                action_eff = action or rec.get("action") or (rec.get("payload") or {}).get(
                    "action"
                )
                if str(stv) == "FILLED" and (
                    ord_state == OrderState.FILLED or ord_state == "FILLED"
                ):
                    if same_order or order_id is None:
                        pay0 = rec.get("payload") or {}
                        stid0 = rec.get("structure_id") or pay0.get("structure_id")
                        if self._terminal_fill_reflected_in_pm(
                            instrument,
                            side,
                            int(qty),
                            str(action_eff or ""),
                            intent_id,
                            structure_id=stid0,
                        ):
                            if self.engine_logger:
                                self.engine_logger.log(
                                    "oms",
                                    f"Skipping duplicate fill callback for already-filled intent {intent_id}",
                                )
                            return
                        if self.engine_logger:
                            self.engine_logger.log(
                                "oms",
                                f"CRITICAL: intent {intent_id} terminal but PM not updated — applying fill anyway",
                            )
        metadata_extras = None
        _ir = self.intent_store.get(intent_id) if intent_id and self.intent_store else None
        if _ir:
            metadata_extras = (_ir.get("payload") or {}).get("strategy_meta")
        if self.position_manager and intent_id and _ir:
            pay_pf = _ir.get("payload") or {}
            act_pf = str(
                action or _ir.get("action") or pay_pf.get("action") or ""
            ).upper()
            tag_pf = str(tag or _ir.get("tag") or pay_pf.get("tag") or "MAIN").upper()
            stid_pf = structure_id or _ir.get("structure_id") or pay_pf.get("structure_id")
            sym_pf = self._instrument_trading_symbol(instrument)
            if (
                act_pf == "ENTRY"
                and sym_pf
                and stid_pf
                and tag_pf == "MAIN"
                and self.position_manager.has_structure_slice_open(sym_pf, str(stid_pf))
                and not self._terminal_fill_reflected_in_pm(
                    instrument,
                    side,
                    int(qty),
                    act_pf,
                    intent_id,
                    structure_id=str(stid_pf),
                )
            ):
                if self.engine_logger:
                    self.engine_logger.log(
                        "oms",
                        f"Skipping duplicate MAIN ENTRY fill structure_id={stid_pf}",
                    )
                return

        # REST fill paths often omit candle_ts; stamp wall clock so trades.csv / trade_log get times.
        if candle_ts is None:
            candle_ts = datetime.datetime.now(tz=datetime.timezone.utc)

        position_closed, realized_pnl = self.position_manager.on_fill(
            instrument=instrument,
            side=side,
            qty=qty,
            price=price,
            intent_id=intent_id,
            order_id=order_id,
            strategy=strategy,
            structure_id=structure_id,
            tag=tag,
            candle_ts=candle_ts,
            action=action,
            metadata_extras=metadata_extras,
            exit_reason=exit_reason,
            execution_source=execution_source or "INTENT",
        )
        if position_closed and realized_pnl is not None:
            self.risk.record_realized_pnl(realized_pnl)
        tag_fill = str(tag or "").upper()
        stid_fill = structure_id
        if not stid_fill and intent_id and self.intent_store:
            _rec_fill = self.intent_store.get(intent_id) or {}
            stid_fill = _rec_fill.get("structure_id") or (_rec_fill.get("payload") or {}).get(
                "structure_id"
            )
        self._maybe_cancel_bracket_sibling_after_exit(
            bool(position_closed), tag_fill, stid_fill
        )
        sym = self._instrument_trading_symbol(instrument)
        self.report_fill(
            sym,
            side,
            qty,
            expected_price,
            price,
            order_id=order_id,
            intent_id=intent_id,
            strategy_id=strategy,
        )
        if intent_id and self.intent_store:
            self._set_order_state(
                intent_id,
                OrderState.FILLED,
                action="process_fill",
                message="Fill processed from callback or engine",
            )
            self.intent_store.update(
                intent_id,
                IntentStatus.FILLED,
                broker_order_id=order_id,
                order_state=OrderState.FILLED,
            )
        if self.position_manager and sym:
            self.position_manager.note_trade_led_fill(sym)
        self._emit_bus_fill_events(
            intent_id=intent_id,
            strategy=strategy,
            instrument=instrument,
            side=side,
            qty=qty,
            price=price,
            position_closed=bool(position_closed),
            realized_pnl=realized_pnl,
            structure_id=structure_id,
            tag=tag,
            action=action,
            metadata_extras=metadata_extras,
        )

    def _emit_bus_fill_events(
        self,
        *,
        intent_id: Any,
        strategy: Any,
        instrument: Any,
        side: Any,
        qty: Any,
        price: Any,
        position_closed: bool,
        realized_pnl: Any,
        structure_id: Any,
        tag: Any,
        action: Any = None,
        metadata_extras: Any = None,
    ) -> None:
        bus = getattr(self, "event_bus", None)
        if bus is None:
            return
        from core.events.types import EventType, make_event

        sym = self._instrument_trading_symbol(instrument)
        engine_id = str(getattr(self, "engine_id", None) or "live")
        bus.publish(
            make_event(
                EventType.INTENT_FILLED,
                {
                    "intent_id": intent_id,
                    "strategy": strategy,
                    "symbol": sym,
                    "side": side,
                    "qty": qty,
                    "price": price,
                    "structure_id": structure_id,
                    "tag": tag,
                    "action": action,
                    "instrument": instrument,
                    "metadata_extras": metadata_extras,
                },
                engine_id=engine_id,
            )
        )
        if position_closed:
            bus.publish(
                make_event(
                    EventType.POSITION_CLOSED,
                    {
                        "strategy": strategy,
                        "symbol": sym,
                        "realized_pnl": realized_pnl,
                        "structure_id": structure_id,
                    },
                    engine_id=engine_id,
                )
            )

    def process_trade(self, trade: Dict[str, Any]) -> bool:
        """
        Trade-led OMS: update position from a trade event (fill). Orders are metadata;
        positions are driven only by trades. Idempotent by trade_id.
        Returns True if trade was applied, False if skipped (e.g. already processed).
        """
        trade_id = str(
            trade.get("trade_id")
            or trade.get("id")
            or f"{trade.get('order_id', '')}_{trade.get('created_at', '')}"
        )
        if not trade_id or trade_id in getattr(self, "_processed_trade_ids", set()):
            return False
        intent_id = trade.get("intent_id") or trade.get("client_order_id") or trade.get("tag")
        if intent_id and self.intent_store and hasattr(self.intent_store, "resolve_intent_id"):
            resolved = self.intent_store.resolve_intent_id(intent_id)
            if resolved:
                intent_id = resolved
        if not intent_id:
            if self.engine_logger:
                self.engine_logger.log(
                    "intent_not_found_for_trade",
                    "Trade missing intent_id/client_order_id/tag; cannot apply fill",
                    order_id=trade.get("order_id"),
                    trade_id=trade_id,
                    strategy_id=trade.get("strategy_id"),
                )
            return False
        price = float(trade.get("price") or 0)
        size = float(trade.get("size") or 0)
        if price <= 0 or size <= 0:
            return False
        side = (trade.get("side") or "").upper()
        order_id = trade.get("order_id")
        # Resolve instrument and metadata from intent_store
        intent = self.intent_store.get(intent_id) if self.intent_store else None
        if not intent:
            if self.engine_logger:
                self.engine_logger.log(
                    "intent_not_found_for_trade",
                    "Intent not found for trade; fill not applied",
                    intent_id=intent_id,
                    order_id=order_id,
                    trade_id=trade_id,
                    strategy_id=trade.get("strategy_id"),
                )
            return False
        instrument = trade.get("instrument") or intent.get("instrument")
        if not instrument:
            return False
        if self.position_manager:
            payload = intent.get("payload") or {}
            action_to_apply = intent.get("action") or payload.get("action") or trade.get("action")
            action_upper = str(action_to_apply or "").upper()
            sym = self._instrument_trading_symbol(instrument)

            tag_u = str(intent.get("tag") or payload.get("tag") or "MAIN").upper()
            stid = (
                intent.get("structure_id")
                or payload.get("structure_id")
                or trade.get("structure_id")
            )
            if action_upper == "ENTRY" and sym and tag_u == "MAIN":
                prev_q = int(self.position_manager.get_qty(sym))
                if prev_q != 0:
                    iq = int(size)
                    exp = -iq if side == "SELL" else iq
                    if prev_q == exp and not self._terminal_fill_reflected_in_pm(
                        instrument,
                        side,
                        iq,
                        action_upper,
                        intent_id,
                        structure_id=stid,
                    ):
                        if self.engine_logger:
                            self.engine_logger.log(
                                "oms",
                                f"Adopting MAIN ENTRY linkage for {sym} intent_id={intent_id} "
                                f"(qty already at broker; attaching metadata + SL)",
                            )
                        self._adopt_main_entry_shadow_fill(
                            instrument=instrument,
                            intent=intent,
                            intent_id=intent_id,
                            side=side,
                            qty=iq,
                            price=price,
                            order_id=order_id,
                            trade_id=trade_id,
                        )
                        return True

            # Skip ENTRY from fills API only when this intent's ENTRY is already reflected in PM
            # (true duplicate). Do not skip merely because the symbol is open — that can hide
            # a never-applied ENTRY after reconcile vs. fill races.
            if action_upper == "ENTRY" and self._terminal_fill_reflected_in_pm(
                instrument,
                side,
                int(size),
                action_upper,
                intent_id,
                structure_id=stid,
            ):
                if self.engine_logger:
                    self.engine_logger.log(
                        "oms",
                        f"Skipping duplicate ENTRY trade for {sym} (intent_id={intent_id}) — PM already matches",
                    )
                self._processed_trade_ids.add(trade_id)
                self._set_order_state(
                    intent_id,
                    OrderState.FILLED,
                    action="skip_duplicate_entry_trade",
                    message="ENTRY trade already in PM",
                )
                self.intent_store.update(
                    intent_id,
                    IntentStatus.FILLED,
                    broker_order_id=order_id,
                    order_state=OrderState.FILLED,
                )
                self.position_manager.note_trade_led_fill(sym)
                return True

            if (
                action_upper == "ENTRY"
                and sym
                and stid
                and tag_u == "MAIN"
                and self.position_manager.has_structure_slice_open(sym, str(stid))
                and not self._terminal_fill_reflected_in_pm(
                    instrument,
                    side,
                    int(size),
                    action_upper,
                    intent_id,
                    structure_id=str(stid),
                )
            ):
                if self.engine_logger:
                    self.engine_logger.log(
                        "oms",
                        f"Skipping duplicate MAIN ENTRY for structure_id={stid} on {sym} "
                        f"(intent_id={intent_id})",
                    )
                self._processed_trade_ids.add(trade_id)
                self._set_order_state(
                    intent_id,
                    OrderState.FILLED,
                    action="skip_duplicate_structure_entry",
                    message="MAIN ENTRY already open for this structure_id",
                )
                self.intent_store.update(
                    intent_id,
                    IntentStatus.FILLED,
                    broker_order_id=order_id,
                    order_state=OrderState.FILLED,
                )
                self.position_manager.note_trade_led_fill(sym)
                return True

            execution_source = trade.get("execution_source") or "INTENT"
            position_closed = False
            realized_pnl = None
            position_closed, realized_pnl = self.position_manager.on_fill(
                instrument=instrument,
                side=side,
                qty=int(size),
                price=price,
                intent_id=intent_id,
                order_id=order_id,
                strategy=(
                    intent.get("strategy")
                    or payload.get("strategy_id")
                    or trade.get("strategy")
                ),
                structure_id=(
                    intent.get("structure_id")
                    or payload.get("structure_id")
                    or trade.get("structure_id")
                ),
                tag=intent.get("tag") or trade.get("tag"),
                candle_ts=intent.get("candle_ts") or trade.get("candle_ts"),
                action=intent.get("action") or payload.get("action") or trade.get("action"),
                metadata_extras=payload.get("strategy_meta"),
                execution_source=execution_source,
            )
            if position_closed and realized_pnl is not None:
                self.risk.record_realized_pnl(realized_pnl)
            tag_fill = str(
                intent.get("tag") or payload.get("tag") or trade.get("tag") or ""
            ).upper()
            stid_fill = (
                intent.get("structure_id")
                or payload.get("structure_id")
                or trade.get("structure_id")
            )
            self._maybe_cancel_bracket_sibling_after_exit(
                bool(position_closed), tag_fill, stid_fill
            )
        sym = self._instrument_trading_symbol(instrument)
        self.report_fill(
            sym, side, int(size), trade.get("expected_price"), price,
            order_id=order_id, intent_id=intent_id,
            strategy_id=intent.get("strategy") or payload.get("strategy_id") or trade.get("strategy"),
        )
        self._set_order_state(
            intent_id,
            OrderState.FILLED,
            action="process_trade",
            message=f"Position updated from trade ({trade.get('execution_source') or 'INTENT'})",
        )
        self.intent_store.update(
            intent_id,
            IntentStatus.FILLED,
            broker_order_id=order_id,
            order_state=OrderState.FILLED,
        )
        payload_done = intent.get("payload") or {}
        act_done = str(
            intent.get("action") or payload_done.get("action") or trade.get("action") or ""
        ).upper()
        tag_done = str(
            intent.get("tag") or payload_done.get("tag") or trade.get("tag") or ""
        ).upper()
        if act_done == "ENTRY" and tag_done == "MAIN":
            book = getattr(self, "gtt_fallback_book", None)
            if book is not None:
                book.on_fill(intent_id)
        self._processed_trade_ids.add(trade_id)
        if len(self._processed_trade_ids) > getattr(self, "_processed_trade_ids_max", 10000):
            self._processed_trade_ids = set(list(self._processed_trade_ids)[-self._processed_trade_ids_max // 2 :])
        if self.position_manager and sym:
            self.position_manager.note_trade_led_fill(sym)
        return True

    @staticmethod
    def _string_indicates_exchange_liquidation(s: str) -> bool:
        """
        True only for explicit liquidation semantics — not bare 'liquid' (matches 'illiquid', etc.).
        """
        if not isinstance(s, str) or not s.strip():
            return False
        sl = s.lower()
        if "liquidation" in sl or "liquidated" in sl:
            return True
        if "force_liquid" in sl:
            return True
        return False

    @staticmethod
    def _is_delta_liquidation_fill(f: Dict[str, Any]) -> bool:
        """True if broker fill is an exchange-driven liquidation (no client_order_id / intent)."""
        if not isinstance(f, dict):
            return False
        if f.get("liquidation") is True or f.get("is_liquidation") is True:
            return True
        ft = f.get("fill_type") or f.get("type") or ""
        if isinstance(ft, str) and OrderRouter._string_indicates_exchange_liquidation(ft):
            return True
        meta = f.get("meta")
        if isinstance(meta, str):
            try:
                meta = json.loads(meta)
            except (json.JSONDecodeError, TypeError):
                meta = None
        if isinstance(meta, dict):
            for key in ("fill_type", "type", "order_type", "liquidation_type"):
                v = meta.get(key)
                if isinstance(v, str) and OrderRouter._string_indicates_exchange_liquidation(v):
                    return True
        return False

    @staticmethod
    def _is_adl_fill(f: Dict[str, Any]) -> bool:
        """Auto-deleverage close (future-proof; Delta/metadata may expose flags later)."""
        if not isinstance(f, dict):
            return False
        if f.get("adl") is True or f.get("is_adl") is True:
            return True
        ft = f.get("fill_type") or f.get("type") or ""
        if isinstance(ft, str) and (
            "adl" in ft.lower() or "delever" in ft.lower()
        ):
            return True
        meta = f.get("meta")
        if isinstance(meta, str):
            try:
                meta = json.loads(meta)
            except (json.JSONDecodeError, TypeError):
                meta = None
        if isinstance(meta, dict):
            for key in ("fill_type", "type", "order_type", "liquidation_type"):
                v = meta.get(key)
                if isinstance(v, str) and (
                    "adl" in v.lower() or "delever" in v.lower()
                ):
                    return True
        return False

    def _known_broker_order_ids(self) -> Set[str]:
        """All broker order IDs we have recorded on intents (own orders)."""
        out: Set[str] = set()
        if not self.intent_store or not hasattr(self.intent_store, "intents"):
            return out
        try:
            for rec in self.intent_store.intents.values():
                bid = rec.get("broker_order_id")
                if bid is not None and str(bid).strip():
                    out.add(str(bid).strip())
        except Exception:
            pass
        return out

    def resolve_intent_id_by_broker_order_id(self, broker_order_id: str) -> Optional[str]:
        """Map Dhan OrderNo / broker order id to intent_id when CorrelationId is empty."""
        bid = str(broker_order_id or "").strip()
        if not bid or not self.intent_store:
            return None
        try:
            for rec in self.intent_store.intents.values():
                if str(rec.get("broker_order_id") or "").strip() == bid:
                    iid = rec.get("intent_id")
                    return str(iid) if iid else None
        except Exception:
            pass
        return None

    def _external_close_confidence_score(
        self, f: Dict[str, Any], known_order_ids: Set[str]
    ) -> Tuple[int, Optional[Any]]:
        """
        Confidence for treating a fill as EXTERNAL_CLOSE (not boolean) — reduces false positives
        when the broker drops client_order_id on our own exit orders.

        +2 no client_order_id / tag
        +2 broker order_id not in known_order_ids
        +1 reduce_only is True
        +2 fill direction matches an open leg that would reduce exposure
        """
        if not isinstance(f, dict):
            return 0, None
        oid = str(f.get("order_id") or f.get("id") or "").strip()
        cid = str(f.get("client_order_id") or f.get("tag") or "").strip()
        if cid:
            return 0, None
        if not oid or oid in known_order_ids:
            return 0, None
        ro = f.get("reduce_only")
        if ro is False:
            return 0, None
        sym = OrderRouter._fill_product_symbol(f)
        side = (f.get("side") or "").upper()
        if not sym or side not in ("BUY", "SELL"):
            return 0, None
        score = 4
        if ro is True:
            score += 1
        pos = None
        if self.position_manager:
            pos = self._find_position_for_external_close(
                sym, side, float(f.get("size") or 0)
            )
        if pos is not None:
            score += 2
        return score, pos

    @staticmethod
    def _fill_product_symbol(f: Dict[str, Any]) -> str:
        sym = (
            f.get("product_symbol")
            or (f.get("product") or {}).get("symbol")
            or f.get("symbol")
            or ""
        )
        return str(sym).strip()

    #checked
    @staticmethod
    def _fill_timestamp_unix(f: Dict[str, Any]) -> Optional[float]:
        """Parse broker fill time to UTC unix seconds (float). None if missing or unparseable."""
        raw = f.get("created_at")
        if raw is None:
            raw = f.get("filled_at") or f.get("timestamp") or f.get("time")
        if raw is None:
            return None
        if isinstance(raw, (int, float)):
            ts = float(raw)
            if ts > 1e12:
                ts /= 1000.0
            return ts
        if isinstance(raw, str):
            s = raw.strip()
            if not s:
                return None
            try:
                uf = float(s)
                if uf > 1e12:
                    uf /= 1000.0
                return uf
            except ValueError:
                pass
            try:
                iso = s.replace("Z", "+00:00")
                dt = datetime.datetime.fromisoformat(iso)
                return dt.timestamp()
            except (ValueError, TypeError, OSError):
                return None
        return None

    def _orphan_fill_fails_time_gates(self, t_fill: Optional[float], order_id: Any) -> bool:
        """True => do not run orphan EXTERNAL_CLOSE / LIQUIDATION / ADL for this fill."""
        if t_fill is None:
            logger.debug(
                "Orphan fill skipped: no parseable fill time (order_id=%s)",
                order_id,
            )
            return True
        if self.reject_orphan_fills_before_oms_session:
            if t_fill + 0.5 < self._oms_session_start_unix:
                logger.debug(
                    "Orphan fill skipped: before OMS session start (order_id=%s)",
                    order_id,
                )
                return True
        if (
            self.max_orphan_fill_age_seconds is not None
            and self.max_orphan_fill_age_seconds > 0
        ):
            if time.time() - t_fill > self.max_orphan_fill_age_seconds:
                logger.debug(
                    "Orphan fill skipped: exceeds max_orphan_fill_age_seconds (order_id=%s)",
                    order_id,
                )
                return True
        return False

    @staticmethod
    def _symbol_keys_close_enough(a: str, b: str) -> bool:
        """Case-insensitive match for option contract symbols (e.g. C-BTC-65000-030426)."""
        return (a or "").strip().upper() == (b or "").strip().upper()

    def _close_qty_from_fill(self, pos: Any, raw_size: float) -> float:
        """
        Contracts to apply for this fill: supports partial liquidation when size is in contracts
        or in base currency (e.g. BTC) via instrument.contract_multiplier.
        If reported size is missing (<=0), assume full local leg.
        """
        net = abs(float(pos.net_qty))
        if net <= 0:
            return 0.0
        if raw_size <= 0:
            return net
        inst = pos.instrument
        mult = float(getattr(inst, "contract_multiplier", 0) or 0)
        # Integer contract count from API
        if raw_size >= 1.0 - 1e-9:
            q = float(int(round(raw_size)))
            return min(net, q) if q > 0 else net
        # Fractional: often base currency (notional) per contract on Delta
        if mult > 0 and raw_size < net * mult * 4 + 1e-9:
            contracts = raw_size / mult
            if contracts > 0:
                return min(net, float(contracts))
        # Unparseable small fraction: treat as partial in contract space
        if 0 < raw_size < 1:
            return min(net, float(raw_size))
        return min(net, float(raw_size))

    def _find_position_for_external_close(
        self,
        product_symbol: str,
        fill_side: str,
        fill_size_raw: float,
    ) -> Optional[Any]:
        """
        Match external close to an open leg. Priority when multiple: exact size, closest size,
        most recently updated, then highest exposure (|qty|*avg_price*lot_size).
        """
        if not self.position_manager or not product_symbol:
            return None
        fs = fill_side.upper()
        if fs not in ("BUY", "SELL"):
            return None

        candidates = []
        for sym_key, pos in self.position_manager.positions.items():
            if pos.net_qty == 0:
                continue
            inst_ts = (
                getattr(pos.instrument, "trading_symbol", "") or ""
                if pos.instrument
                else ""
            )
            if (
                not self._symbol_keys_close_enough(sym_key, product_symbol)
                and not self._symbol_keys_close_enough(inst_ts, product_symbol)
            ):
                continue
            if fs == "BUY" and pos.net_qty >= 0:
                continue
            if fs == "SELL" and pos.net_qty <= 0:
                continue
            candidates.append(pos)

        if not candidates:
            return None
        if len(candidates) == 1:
            return candidates[0]

        def _rank_tuple(pos: Any) -> Tuple[int, float, float, float]:
            net = abs(float(pos.net_qty))
            guessed = self._close_qty_from_fill(pos, fill_size_raw)
            exact_miss = 0 if abs(net - guessed) < 1e-8 else 1
            dist = abs(net - guessed)
            last = float(getattr(pos, "last_updated", 0) or 0)
            exposure = abs(float(pos.net_qty)) * float(pos.avg_price or 0) * float(
                getattr(pos.instrument, "lot_size", 1) or 1
            )
            return (exact_miss, dist, -last, -exposure)

        return sorted(candidates, key=_rank_tuple)[0]

    def _process_external_close_fill(self, f: Dict[str, Any], execution_source: str) -> bool:
        """
        Liquidation / ADL / orphan reduce-only fills without intent linkage.
        execution_source: LIQUIDATION | EXTERNAL_CLOSE | ADL
        """
        if not self.position_manager:
            return False
        if execution_source not in ("LIQUIDATION", "EXTERNAL_CLOSE", "ADL"):
            return False

        trade_id = str(
            f.get("trade_id")
            or f.get("id")
            or f"{f.get('order_id', '')}_{f.get('created_at', '')}"
        )
        if not trade_id or trade_id in getattr(self, "_processed_trade_ids", set()):
            return False

        fill_ts = self._fill_timestamp_unix(f)
        if fill_ts is None:
            logger.debug(
                "Orphan close skipped: missing fill timestamp (trade_id=%s)",
                trade_id,
            )
            return False

        price = float(f.get("price") or f.get("average_fill_price") or 0)
        raw_size = float(f.get("size") or f.get("qty") or 0)
        if price <= 0:
            return False

        sym = self._fill_product_symbol(f)
        side = (f.get("side") or "").upper()

        with self.position_manager._lock:
            pos = self._find_position_for_external_close(sym, side, raw_size)
            if not pos or pos.net_qty == 0:
                if pos is None:
                    # Expected when: stale fills in get_recent_fills, manual close already flat,
                    # or another account/session — not actionable for local OMS.
                    logger.debug(
                        "Orphan fill skipped (no reducing leg in local book): source=%s symbol=%s side=%s size=%s",
                        execution_source,
                        sym,
                        side,
                        raw_size,
                    )
                return False
            if self.reject_orphan_fill_if_predates_position_open:
                et = getattr(pos, "entry_time", None)
                if et is not None and fill_ts < float(et) - 1.0:
                    logger.debug(
                        "Orphan fill skipped: fill before local position open (symbol=%s fill_ts=%s entry_time=%s)",
                        getattr(pos.instrument, "trading_symbol", sym),
                        fill_ts,
                        et,
                    )
                    return False
            inst = pos.instrument
            sym_ts = getattr(inst, "trading_symbol", sym)
            close_qty = min(
                self._close_qty_from_fill(pos, raw_size),
                abs(float(pos.net_qty)),
            )
            prev_signed = int(pos.net_qty)
            pm_meta = self.position_manager.position_metadata.get(sym_ts) or {}
            strat = pos.strategy or pm_meta.get("strategy")
            struct_id = pos.structure_id or pm_meta.get("structure_id")
            tag = pos.tag or pm_meta.get("tag")
            intent_id = pos.intent_id or pm_meta.get("intent_id")
            meta_extras = pm_meta.get("strategy_meta")

        if close_qty <= 0:
            return False

        exit_reason = {
            "LIQUIDATION": "LIQUIDATION",
            "EXTERNAL_CLOSE": "EXTERNAL_CLOSE",
            "ADL": "ADL",
        }.get(execution_source, execution_source)
        order_id = str(f.get("order_id") or f.get("id") or "")

        qty_arg = (
            int(round(close_qty))
            if abs(close_qty - round(close_qty)) < 1e-9
            else close_qty
        )
        position_closed, realized_pnl = self.position_manager.on_fill(
            instrument=inst,
            side=side,
            qty=qty_arg,
            price=price,
            intent_id=intent_id,
            order_id=order_id or None,
            strategy=strat,
            structure_id=struct_id,
            tag=tag,
            candle_ts=None,
            action="EXIT",
            metadata_extras=meta_extras,
            exit_reason=exit_reason,
            execution_source=execution_source,
        )
        np = self.position_manager.positions.get(sym_ts)
        new_qty = int(np.net_qty) if np else 0

        fn = getattr(self.position_manager, "on_forced_exit", None)
        debounce_key = struct_id or sym_ts
        if callable(fn) and self.position_manager.should_emit_forced_exit(
            debounce_key, position_closed
        ):
            try:
                fn(
                    instrument=inst,
                    symbol=sym_ts,
                    strategy=strat,
                    structure_id=struct_id,
                    tag=tag,
                    intent_id=intent_id,
                    prev_qty=prev_signed,
                    new_qty=new_qty,
                    qty_closed=close_qty,
                    price=price,
                    execution_source=execution_source,
                    exit_reason=exit_reason,
                    position_closed=position_closed,
                    order_id=order_id or None,
                )
            except Exception as e:
                logger.warning("on_forced_exit callback failed: %s", e, exc_info=True)

        rec_es = getattr(self.risk, "record_execution_source", None)
        if callable(rec_es):
            try:
                rec_es(
                    execution_source,
                    strat,
                    symbol=sym_ts,
                    position_closed=position_closed,
                )
            except Exception as e:
                logger.debug("record_execution_source failed: %s", e)

        if position_closed and realized_pnl is not None:
            self.risk.record_realized_pnl(realized_pnl)

        self.report_fill(
            sym_ts,
            side,
            qty_arg,
            None,
            price,
            order_id=order_id or None,
            intent_id=intent_id,
            strategy_id=strat,
        )
        if intent_id and self.intent_store:
            self._set_order_state(
                intent_id,
                OrderState.FILLED,
                action="external_close_fill",
                message=f"{execution_source} broker_order_id={order_id}",
            )
            self.intent_store.update(
                intent_id,
                IntentStatus.FILLED,
                broker_order_id=order_id or None,
                order_state=OrderState.FILLED,
            )
        self._processed_trade_ids.add(trade_id)
        if len(self._processed_trade_ids) > getattr(self, "_processed_trade_ids_max", 10000):
            self._processed_trade_ids = set(
                list(self._processed_trade_ids)[-self._processed_trade_ids_max // 2 :]
            )
        self.position_manager.note_trade_led_fill(sym_ts)
        if self.engine_logger:
            self.engine_logger.log(
                "oms",
                f"Applied {execution_source} fill to {sym_ts} qty={close_qty} intent_id={intent_id or 'none'}",
            )
        return True

    def sync_trades_from_broker(self) -> None:
        """
        Trade-led OMS: pull recent fills from broker and apply any new trades.
        Call before order-state verification so positions are up to date from trades.
        """
        if not getattr(self.broker, "get_recent_fills", None):
            return
        try:
            fills = self.broker.get_recent_fills(page_size=50)
        except Exception:
            return
        # Match by broker order_id when fill has no client_order_id (e.g. Delta often returns only order_id).
        # Include FILLED/CANCELLED intents so delayed API rows still map to process_trade (idempotent by trade_id).
        broker_order_id_to_intent: Dict[str, str] = {}
        known_order_ids = self._known_broker_order_ids()
        try:
            for rec in self.intent_store.intents.values():
                bid = rec.get("broker_order_id")
                iid = rec.get("intent_id")
                if bid is not None and iid:
                    k = str(bid).strip()
                    if k:
                        broker_order_id_to_intent.setdefault(k, iid)
        except Exception:
            pass
        for f in fills or []:
            intent_id = (
                f.get("client_order_id")
                or f.get("tag")
                or broker_order_id_to_intent.get(str(f.get("order_id") or f.get("id") or ""))
            )
            if intent_id and self.intent_store and self.intent_store.get(intent_id):
                oid = str(f.get("order_id") or f.get("id") or "")
                sz = float(f.get("size") or 0)
                pr = float(f.get("price") or 0)
                is_dhan = type(self.broker).__name__ == "DhanBroker"
                # Canonical REST reconciliation id for Dhan (distinct from DHAN_WS:* incremental keys).
                if is_dhan:
                    trade_id = f"DHAN_REST:{oid}:{int(sz)}:{pr}"
                else:
                    tid = f.get("id") or f.get("trade_id")
                    trade_id = str(tid) if tid else f"{oid}_{int(sz)}_{pr}"
                trade: Dict[str, Any] = {
                    "trade_id": trade_id,
                    "id": trade_id,
                    "order_id": oid or str(f.get("id", "")),
                    "intent_id": intent_id,
                    "client_order_id": intent_id,
                    "tag": intent_id,
                    "price": pr,
                    "size": sz,
                    "side": (f.get("side") or "").upper(),
                    "created_at": f.get("created_at"),
                    "execution_source": "REST_FILLS",
                }
                if is_dhan:
                    trade["fill_confidence"] = "CONFIRMED"
                self.process_trade(trade)
                continue

            t_fill = self._fill_timestamp_unix(f)
            if self._orphan_fill_fails_time_gates(t_fill, f.get("order_id")):
                continue

            # Manual / untagged fills: prefer EXTERNAL_CLOSE when a reducing leg exists locally,
            # before LIQUIDATION — avoids false 'liquid' substring matches stealing the path.
            exec_src = None
            score, pos_hint = self._external_close_confidence_score(
                f, known_order_ids
            )
            th = getattr(self, "_orphan_close_score_threshold", 6)
            sus = getattr(self, "_orphan_close_suspect_floor", 5)

            if self._is_adl_fill(f):
                exec_src = "ADL"
            elif score >= th and pos_hint is not None:
                exec_src = "EXTERNAL_CLOSE"
            elif self._is_delta_liquidation_fill(f):
                exec_src = "LIQUIDATION"
            else:
                if score >= th and pos_hint is None:
                    logger.info(
                        "Orphan-style fill score=%s but no reducing leg; not applying EXTERNAL_CLOSE (order_id=%s symbol=%s)",
                        score,
                        f.get("order_id"),
                        OrderRouter._fill_product_symbol(f),
                    )
                elif sus <= score < th:
                    logger.info(
                        "Suspect orphan-style fill below EXTERNAL_CLOSE threshold: score=%s (need %s) order_id=%s symbol=%s",
                        score,
                        th,
                        f.get("order_id"),
                        OrderRouter._fill_product_symbol(f),
                    )

            if exec_src and self._process_external_close_fill(f, exec_src):
                continue
        return

    def report_fill(
        self,
        symbol,
        side,
        qty,
        expected_price,
        fill_price,
        order_id=None,
        intent_id=None,
        strategy_id=None,
    ):
        """Logs order_filled and high_slippage_warning if above threshold. Called by process_fill or legacy paths."""
        if self.engine_logger:
            self.engine_logger.order_filled(
                symbol=symbol,
                side=side,
                qty=qty,
                price=fill_price,
                order_id=order_id,
                intent_id=intent_id,
                strategy_id=strategy_id,
            )
        if (
            self.slippage_threshold_pct is not None
            and expected_price
            and expected_price > 0
            and fill_price is not None
        ):
            pct = abs(fill_price - expected_price) / expected_price
            if pct > self.slippage_threshold_pct:
                if self.engine_logger:
                    self.engine_logger.high_slippage_warning(
                        symbol=symbol,
                        expected_price=expected_price,
                        fill_price=fill_price,
                        slippage_pct=pct * 100,
                    )
