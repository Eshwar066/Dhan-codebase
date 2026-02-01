# import time
# import uuid

# from intent_store import IntentStore
# from order_state import OrderStatus
# from slippage import allowed_slippage


# class OrderExecutionEngine:
#     def __init__(self, broker, risk_mgr, pos_mgr):
#         self.broker = broker
#         self.risk_mgr = risk_mgr
#         self.pos_mgr = pos_mgr
#         self.intent_store = IntentStore()

#     # =================================
#     # MAIN ENTRY (Strategy Signal)
#     # =================================
#     def on_signal(self, signal):
#         """
#         signal = {
#             strategy_id,
#             symbol,
#             side,
#             price,
#             stop_loss,
#             risk_pct,
#             capital,
#             segment,
#             timestamp
#         }
#         """

#         intent_id = self._build_intent_id(signal)

#         # 1️⃣ Idempotency check
#         if self.intent_store.exists(intent_id):
#             return

#         # 2️⃣ Position sanity checks
#         if not self._position_checks(signal):
#             return

#         # 3️⃣ Slippage guard
#         if not self._slippage_check(signal):
#             return

#         # 4️⃣ Quantity calculation
#         qty = self._calc_qty(signal)
#         if qty <= 0:
#             return

#         # 5️⃣ Build intent
#         intent = self._build_intent(intent_id, signal, qty)
#         self.intent_store.create(intent_id, intent)

#         # 6️⃣ Risk approval (FINAL GATE)
#         if not self.risk_mgr.allow_intent(intent):
#             self.intent_store.update(intent_id, OrderStatus.REJECTED)
#             return

#         # 7️⃣ Execute
#         self._execute_intent(intent)

#     # =================================
#     # BUILDERS
#     # =================================
#     def _build_intent_id(self, signal):
#         base = f"{signal['strategy_id']}_{signal['symbol']}_{signal['side']}"
#         return f"{base}_{int(time.time())}"

#     def _build_intent(self, intent_id, signal, qty):
#         return {
#             "intent_id": intent_id,
#             "strategy": signal["strategy_id"],
#             "symbol": signal["symbol"],
#             "side": signal["side"],
#             "qty": qty,
#             "segment": signal.get("segment", "EQ"),
#             "order_type": "MARKET",
#             "product": "MIS",
#             "price": signal["price"],
#             "timestamp": time.time(),
#         }

#     # =================================
#     # CHECKS
#     # =================================
#     def _position_checks(self, signal):
#         sym = signal["symbol"]
#         side = signal["side"]

#         if side == "BUY" and self.pos_mgr.is_long(sym):
#             return False

#         if side == "SELL" and self.pos_mgr.is_short(sym):
#             return False

#         return True

#     def _slippage_check(self, signal):
#         ltp = self.broker.api.get_ltp(signal["symbol"])
#         return allowed_slippage(signal["price"], ltp)

#     def _calc_qty(self, signal):
#         return self.risk_mgr.calc_qty(
#             capital=signal["capital"],
#             risk_pct=signal["risk_pct"],
#             stop_loss_pts=signal["stop_loss"],
#         )

#     # =================================
#     # EXECUTION
#     # =================================
#     def _execute_intent(self, intent):

#         intent_id = intent["intent_id"]

#         try:
#             order_id = self.broker.place_order(intent, retries=2)

#             if not order_id:
#                 raise Exception("No order_id returned")

#             self.intent_store.update(
#                 intent_id,
#                 OrderStatus.SENT,
#             )

#         except Exception as e:
#             self.intent_store.update(
#                 intent_id,
#                 OrderStatus.REJECTED,
#             )
#             print("Execution error:", e)

#     # =================================
#     # FILL HANDLER (Broker Callback)
#     # =================================
#     def on_fill(self, fill):
#         """
#         fill = {
#             intent_id,
#             symbol,
#             side,
#             qty,
#             price
#         }
#         """

#         intent_id = fill["intent_id"]

#         # Update position manager
#         self.pos_mgr.on_fill(
#             instrument=fill["instrument"],
#             side=fill["side"],
#             qty=fill["qty"],
#             price=fill["price"],
#             strategy=fill.get("strategy"),
#         )

#         # Update intent state
#         self.intent_store.update(intent_id, OrderStatus.FILLED)
