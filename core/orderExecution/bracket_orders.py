"""
OCO-style bracket legs (MAIN_SL + MAIN_TARGET) per structure_id.

After MAIN entry fill, strategies arm two resting exits; when one fills,
the sibling leg is cancelled (sim pending book or live broker cancel_order).
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

BRACKET_TAGS = frozenset({"MAIN_SL", "MAIN_TARGET"})


class BracketLegRegistry:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        # structure_id -> {MAIN_SL: {intent_id, order_id}, MAIN_TARGET: {...}}
        self._legs: Dict[str, Dict[str, Dict[str, str]]] = {}

    def register_structure(self, structure_id: str) -> None:
        if not structure_id:
            return
        with self._lock:
            self._legs.setdefault(str(structure_id), {})

    def link_leg(
        self,
        structure_id: str,
        tag: str,
        *,
        intent_id: Optional[str] = None,
        broker_order_id: Optional[str] = None,
    ) -> None:
        if not structure_id:
            return
        tag_u = str(tag or "").upper()
        if tag_u not in BRACKET_TAGS:
            return
        with self._lock:
            bucket = self._legs.setdefault(str(structure_id), {})
            leg = bucket.setdefault(tag_u, {})
            if intent_id:
                leg["intent_id"] = str(intent_id)
            if broker_order_id:
                leg["order_id"] = str(broker_order_id)

    def get_sibling(
        self, structure_id: str, filled_tag: str
    ) -> Optional[Dict[str, str]]:
        tag_u = str(filled_tag or "").upper()
        other = "MAIN_TARGET" if tag_u == "MAIN_SL" else "MAIN_SL"
        with self._lock:
            bucket = self._legs.get(str(structure_id)) or {}
            sib = bucket.get(other)
            return dict(sib) if sib else None

    def clear_structure(self, structure_id: str) -> None:
        with self._lock:
            self._legs.pop(str(structure_id), None)

    def cancel_sibling(
        self,
        structure_id: str,
        filled_tag: str,
        *,
        broker: Any,
        order_router: Any,
        reason: str = "sibling_fill",
    ) -> None:
        if not structure_id:
            return
        sibling = self.get_sibling(structure_id, filled_tag)
        if not sibling:
            return
        self._cancel_leg(
            structure_id,
            sibling,
            broker=broker,
            order_router=order_router,
            detail=reason,
        )

    def cancel_all_for_structure(
        self,
        structure_id: str,
        *,
        broker: Any,
        order_router: Any = None,
        reason: str = "MAIN_EXIT",
    ) -> None:
        if not structure_id:
            return
        sid = str(structure_id)
        with self._lock:
            bucket = dict(self._legs.get(sid) or {})
        if broker is not None and hasattr(broker, "cancel_pending_bracket"):
            broker.cancel_pending_bracket(sid, reason=reason)
        else:
            for tag, leg in bucket.items():
                self._cancel_leg(
                    sid,
                    leg,
                    broker=broker,
                    order_router=order_router,
                    detail=reason,
                    tag_hint=str(tag),
                )
        for tag, leg in bucket.items():
            if broker is not None and hasattr(broker, "cancel_order_by_id"):
                self._cancel_live_order(leg, broker=broker, detail=reason, tag_hint=str(tag))
        self.clear_structure(sid)

    def _cancel_leg(
        self,
        structure_id: str,
        leg: Dict[str, str],
        *,
        broker: Any,
        order_router: Any,
        detail: str,
        tag_hint: str = "",
    ) -> None:
        sid = str(structure_id)
        intent_id = leg.get("intent_id")
        order_id = leg.get("order_id")

        if broker is not None and tag_hint == "MAIN_SL" and hasattr(
            broker, "cancel_pending_sl"
        ):
            broker.cancel_pending_sl(sid, detail=detail)
        elif broker is not None and tag_hint == "MAIN_TARGET" and hasattr(
            broker, "cancel_pending_target"
        ):
            broker.cancel_pending_target(sid, detail=detail)

        if broker is not None and hasattr(broker, "cancel_order_by_id"):
            self._cancel_live_order(leg, broker=broker, detail=detail, tag_hint=tag_hint)

        if order_router and intent_id and getattr(order_router, "intent_store", None):
            try:
                from core.orderExecution.intent_store import IntentStatus

                order_router.intent_store.update(
                    intent_id,
                    IntentStatus.CANCELLED,
                    order_state="CANCELLED",
                )
            except Exception:
                pass

    @staticmethod
    def _cancel_live_order(
        leg: Dict[str, str],
        *,
        broker: Any,
        detail: str,
        tag_hint: str,
    ) -> None:
        order_id = leg.get("order_id")
        intent_id = leg.get("intent_id")
        if not order_id:
            return
        cancel_fn = getattr(broker, "cancel_order_by_id", None)
        if not callable(cancel_fn):
            return
        try:
            cancel_fn(order_id, intent_id=intent_id, reason=detail)
        except Exception as exc:
            logger.warning(
                "bracket cancel live order failed tag=%s order_id=%s: %s",
                tag_hint,
                order_id,
                exc,
            )
