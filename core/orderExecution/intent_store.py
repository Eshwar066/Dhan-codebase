import threading
import time
import uuid
from enum import Enum
from typing import Iterable, List, Optional, Union

#  idempotency_key = hash(strategy + symbol + candle_time + signal)

#  Strategy Creates intent:
#  intent_store.create(
#      payload=position_dict,
#      idempotency_key=signal_hash
#  )

#  Risk Manager
#  Reads: intent_store.list_by_status(IntentStatus.CREATED)
#  updates: intent_store.update(intent_id, IntentStatus.VALIDATED)

#  Execution Engine
#  intent_store.update(intent_id, IntentStatus.SENT, broker_id)
#  on fill: intent_store.update(intent_id, IntentStatus.FILLED)


# -------------------------
# STATUS ENUM
# -------------------------
class IntentStatus(str, Enum):
    CREATED = "CREATED"
    VALIDATED = "VALIDATED"
    SENT = "SENT"
    ACKED = "ACKED"
    FILLED = "FILLED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


# -------------------------
# STORE
# -------------------------
class IntentStore:
    def __init__(self):
        self._lock = threading.Lock()

        # intent_id → intent_data
        self.intents = {}

        # idempotency_key → intent_id
        self.idempotency_index = {}

    # -------------------------
    # CREATE
    # -------------------------
    def create(self, payload, intent_id=None, idempotency_key=None):
        with self._lock:
            # Idempotency protection
            if idempotency_key and idempotency_key in self.idempotency_index:
                existing_id = self.idempotency_index[idempotency_key]
                return self.intents[existing_id]

            intent_id = intent_id or str(uuid.uuid4())

            intent = {
                "intent_id": intent_id,
                "payload": payload,
                "status": IntentStatus.CREATED,
                "created_at": time.time(),
                "updated_at": time.time(),
                "broker_order_id": None,
                "idempotency_key": idempotency_key,
            }

            self.intents[intent_id] = intent

            if idempotency_key:
                self.idempotency_index[idempotency_key] = intent_id

            return intent

    # -------------------------
    # EXISTS
    # -------------------------
    def exists(self, intent_id):
        return intent_id in self.intents

    # -------------------------
    # GET
    # -------------------------
    def get(self, intent_id):
        return self.intents.get(intent_id)

    # -------------------------
    # UPDATE STATUS
    # -------------------------
    def update(
        self,
        intent_id,
        status: IntentStatus,
        broker_order_id=None,
        order_state=None,
    ):
        """
        Update intent status and optionally broker_order_id and order_state.
        order_state is persisted so OrderRouter can rebuild _order_state cache on restart.
        """
        with self._lock:
            if intent_id not in self.intents:
                return None

            intent = self.intents[intent_id]

            intent["status"] = status
            intent["updated_at"] = time.time()

            if broker_order_id:
                intent["broker_order_id"] = broker_order_id

            if order_state is not None:
                # Store string value so OrderRouter can rebuild _order_state cache on restart
                intent["order_state"] = getattr(order_state, "value", order_state)

            return intent

    # -------------------------
    # LIST BY STATUS
    # -------------------------
    def list_by_status(self, status: IntentStatus):
        return [i for i in self.intents.values() if i["status"] == status]

    # -------------------------
    # PENDING INTENT CHECK (for strategy duplicate-signal guard)
    # -------------------------
    @staticmethod
    def _upper_set(
        vals: Optional[Union[str, Iterable[str]]],
    ) -> Optional[List[str]]:
        """Normalize tag/action filter to a list of upper-case strings; None => no filter."""
        if vals is None:
            return None
        if isinstance(vals, str):
            return [vals.strip().upper()]
        out: List[str] = []
        for v in vals:
            if v is None:
                continue
            s = str(v).strip().upper()
            if s:
                out.append(s)
        return out or None

    def has_pending_intent(
        self,
        strategy: str,
        structure_id: str,
        tags: Optional[Union[str, Iterable[str]]] = None,
        actions: Optional[Union[str, Iterable[str]]] = None,
    ) -> bool:
        """True if any in-flight intent matches strategy + structure (and optional tag/action).

        Lifecycle vs risk: same ``structure_id`` is shared by MAIN and MAIN_SL on Delta, so
        callers that guard duplicate MAIN_EXIT should pass
        ``tags=[\"MAIN_EXIT\"], actions=[\"EXIT\"]`` instead of matching all pendings.
        """
        pending = list(self.list_by_status(IntentStatus.SENT)) + list(
            self.list_by_status(IntentStatus.VALIDATED)
        )
        tag_filter = self._upper_set(tags)
        action_filter = self._upper_set(actions)
        # Parse symbol from structure_id "StrategyName:SYMBOL:FLAT"
        parts = (structure_id or "").split(":")
        sym = parts[1] if len(parts) >= 2 else None
        for i in pending:
            p = i.get("payload") or {}
            if p.get("strategy_id") != strategy:
                continue
            struct_match = p.get("structure_id") == structure_id
            sym_match = sym is not None and p.get("symbol") == sym
            if not struct_match and not sym_match:
                continue

            if tag_filter is not None:
                rec_tag = str(p.get("tag") or "").strip().upper()
                if rec_tag not in tag_filter:
                    continue
            if action_filter is not None:
                rec_action = str(p.get("action") or "").strip().upper()
                if rec_action not in action_filter:
                    continue
            return True
        return False

    # -------------------------
    # ORDER STATE (for OrderRouter cache rebuild)
    # -------------------------
    def get_all_order_states(self):
        """Return [(intent_id, order_state_str), ...] for intents that have order_state set."""
        return [
            (iid, rec["order_state"])
            for iid, rec in self.intents.items()
            if rec.get("order_state")
        ]

    # below two are not used
    # -------------------------
    # EXPIRE STALE
    # -------------------------
    def expire_stale(self, ttl_seconds=30):
        now = time.time()

        with self._lock:
            for intent in self.intents.values():
                if intent["status"] in (
                    IntentStatus.CREATED,
                    IntentStatus.VALIDATED,
                ):
                    age = now - intent["created_at"]
                    if age > ttl_seconds:
                        intent["status"] = IntentStatus.EXPIRED
                        intent["updated_at"] = now

    # -------------------------
    # CLEANUP FINISHED
    # -------------------------
    def cleanup_finalized(self):
        with self._lock:
            to_delete = [
                iid
                for iid, i in self.intents.items()
                if i["status"]
                in (
                    IntentStatus.FILLED,
                    IntentStatus.CANCELLED,
                    IntentStatus.REJECTED,
                    IntentStatus.EXPIRED,
                )
            ]

            for iid in to_delete:
                self.intents.pop(iid, None)
