import threading
import time
import uuid
from enum import Enum

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
    ):
        with self._lock:
            if intent_id not in self.intents:
                return None

            intent = self.intents[intent_id]

            intent["status"] = status
            intent["updated_at"] = time.time()

            if broker_order_id:
                intent["broker_order_id"] = broker_order_id

            return intent

    # -------------------------
    # LIST BY STATUS
    # -------------------------
    def list_by_status(self, status: IntentStatus):
        return [i for i in self.intents.values() if i["status"] == status]

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
