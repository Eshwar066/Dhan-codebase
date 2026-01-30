# run in engine: router.process_intent(intent, price_map)
class OrderRouter:
    def __init__(self, risk_manager, broker, intent_store, slippage_model=None):
        self.risk = risk_manager
        self.broker = broker
        self.intent_store = intent_store
        self.slippage_model = slippage_model or (
            lambda price: price
        )  # default: no slippage

    def process_intent(self, intent, price_map):

        # ---------- 1️⃣ Risk check ----------
        if not self.risk.allow_intent(intent, price_map):
            self.intent_store.update(intent["intent_id"], "REJECTED")
            return

        # ---------- 2️⃣ Apply slippage ----------
        intent["price"] = self.slippage_model(intent["price"])

        # ---------- 3️⃣ Send to broker ----------
        order_id = self.broker.place_order(intent)

        # ---------- 4️⃣ Update IntentStore ----------
        self.intent_store.update(intent["intent_id"], "SENT", broker_order_id=order_id)
