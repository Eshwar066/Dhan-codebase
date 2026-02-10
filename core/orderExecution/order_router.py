import pdb


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
        if not self.risk.allow_intent(intent, price_map, candle_ts=intent.candle_ts):
            self.intent_store.update(intent.intent_id, "REJECTED")
            return

        # ---------- Safety ----------
        if intent.price is None:
            raise ValueError(f"No price available for intent {intent.intent_id}")

        # ---------- 2️⃣ Apply slippage ----------
        exec_price = self.slippage_model(intent.price)

        # ---------- 3️⃣ Send to broker ----------
        order_id = self.broker.place_order(
            intent=intent,
            execution_price=exec_price,  # 🔥 pass explicitly
        )

        # ---------- 4️⃣ Update IntentStore ----------
        self.intent_store.update(
            intent.intent_id,
            "SENT",
            broker_order_id=order_id,
        )
