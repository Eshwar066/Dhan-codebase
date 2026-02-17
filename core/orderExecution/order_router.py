from core.orderExecution.intent_store import IntentStatus


class OrderRouter:
    def __init__(
        self,
        risk_manager,
        broker,
        intent_store,
        position_manager=None,
        slippage_model=None,
        engine_logger=None,
        circuit_breaker_threshold: int = 5,
        slippage_threshold_pct: float = None,
    ):
        self.risk = risk_manager
        self.broker = broker
        self.intent_store = intent_store
        self.position_manager = position_manager
        self.slippage_model = slippage_model or (lambda price: price)
        self.engine_logger = engine_logger
        self.circuit_breaker_threshold = circuit_breaker_threshold
        self.slippage_threshold_pct = slippage_threshold_pct
        self._consecutive_failures = 0

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
        try:
            order_id = self.broker.place_order(intent, execution_price=exec_price)
        except Exception as e:
            self._consecutive_failures += 1
            if self.engine_logger:
                self.engine_logger.log("risk_block", f"Broker place_order failed: {e}")
            if self._consecutive_failures >= self.circuit_breaker_threshold and self.risk:
                self.risk.trigger_kill_switch("broker_failure")
                if self.engine_logger:
                    self.engine_logger.broker_circuit_breaker_triggered("broker_failure")
            self.intent_store.update(intent.intent_id, "REJECTED")
            return

        if order_id is None:
            self._consecutive_failures += 1
            if self.engine_logger:
                self.engine_logger.log("risk_block", "Broker place_order returned None")
            if self._consecutive_failures >= self.circuit_breaker_threshold and self.risk:
                self.risk.trigger_kill_switch("broker_failure")
                if self.engine_logger:
                    self.engine_logger.broker_circuit_breaker_triggered("broker_failure")
            self.intent_store.update(intent.intent_id, "REJECTED")
            return

        self._consecutive_failures = 0
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

    def verify_open_orders_with_broker(self, position_manager):
        """
        Compare broker.get_open_orders() with local IntentStore (SENT) and PositionManager.
        Returns (ok: bool, details: dict). If not ok: caller should call reconcile_positions_on_start and optionally pause.
        """
        if not hasattr(self.broker, "get_open_orders"):
            return True, {}
        try:
            broker_open = self.broker.get_open_orders()
        except Exception as e:
            if self.engine_logger:
                self.engine_logger.order_state_mismatch(f"Failed to fetch broker open orders: {e}")
            return False, {"error": str(e)}
        local_sent = self.intent_store.list_by_status(IntentStatus.SENT)
        local_intent_ids = {i.get("intent_id") for i in local_sent if i.get("intent_id")}
        broker_tags = {o.get("tag") for o in broker_open if o.get("tag")}
        broker_order_ids = {o.get("order_id") for o in broker_open}
        orphans = [o for o in broker_open if o.get("tag") and o.get("tag") not in local_intent_ids]
        missing = [i for i in local_sent if i.get("broker_order_id") and i.get("broker_order_id") not in broker_order_ids]
        filled_not_reflected = [
            i for i in local_sent
            if i.get("broker_order_id") not in broker_order_ids
        ]
        diff = {
            "orphan_broker_orders": len(orphans),
            "missing_local_records": len(missing),
            "filled_not_reflected": len(filled_not_reflected),
        }
        if orphans or missing or filled_not_reflected:
            if self.engine_logger:
                self.engine_logger.order_state_mismatch("Order state mismatch; reconcile required", details=diff)
            return False, diff
        return True, {}

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
    ):
        """
        Single entry point for fill processing. Call from broker fill callback or LiveEngine.
        Updates position via PositionManager.on_fill(); if position closed, records realized PnL
        with RiskManager for daily_max_loss enforcement. Then logs and runs slippage check.
        """
        if not self.position_manager:
            self.report_fill(
                getattr(instrument, "trading_symbol", ""),
                side,
                qty,
                expected_price,
                price,
                order_id=order_id,
                intent_id=intent_id,
            )
            return
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
        )
        if position_closed and realized_pnl is not None:
            self.risk.record_realized_pnl(realized_pnl)
        sym = getattr(instrument, "trading_symbol", "")
        self.report_fill(sym, side, qty, expected_price, price, order_id=order_id, intent_id=intent_id)
        if intent_id and self.intent_store:
            self.intent_store.update(intent_id, IntentStatus.FILLED, broker_order_id=order_id)

    def report_fill(self, symbol, side, qty, expected_price, fill_price, order_id=None, intent_id=None):
        """Logs order_filled and high_slippage_warning if above threshold. Called by process_fill or legacy paths."""
        if self.engine_logger:
            self.engine_logger.order_filled(symbol=symbol, side=side, qty=qty, price=fill_price, order_id=order_id)
        if self.slippage_threshold_pct is not None and expected_price and expected_price > 0 and fill_price is not None:
            pct = abs(fill_price - expected_price) / expected_price
            if pct > self.slippage_threshold_pct:
                if self.engine_logger:
                    self.engine_logger.high_slippage_warning(
                        symbol=symbol,
                        expected_price=expected_price,
                        fill_price=fill_price,
                        slippage_pct=pct * 100,
                    )
