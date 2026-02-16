class OrderRouter:
    def __init__(self, risk_manager, broker, intent_store, slippage_model=None, engine_logger=None):
        self.risk = risk_manager
        self.broker = broker
        self.intent_store = intent_store
        self.slippage_model = slippage_model or (lambda price: price)
        self.engine_logger = engine_logger

    def process_intent(self, intent, price_map):
        if not self.risk.allow_intent(intent, price_map, candle_ts=getattr(intent, "candle_ts", None)):
            self.intent_store.update(intent.intent_id, "REJECTED")
            return

        if intent.price is None:
            raise ValueError(f"No price available for intent {intent.intent_id}")

        exec_price = self.slippage_model(intent.price)
        sym = intent.instrument.trading_symbol if hasattr(intent, "instrument") else ""
        side = getattr(intent, "side", "")
        qty = getattr(intent, "qty", 0)
        order_id = self.broker.place_order(intent, execution_price=exec_price)

        if self.engine_logger:
            self.engine_logger.order_placed(
                symbol=sym,
                side=side,
                qty=qty,
                price=exec_price,
                order_id=order_id,
                intent_id=getattr(intent, "intent_id", None),
            )

        self.intent_store.update(
            intent.intent_id,
            "SENT",
            broker_order_id=order_id,
        )
