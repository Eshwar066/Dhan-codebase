Strategy
  ↓
Intent
  ↓
RiskManager
  ↓
OrderRouter
  ↓
DhanBroker.place_order()
  ↓
Broker
  ↓
Fill
  ↓
PositionManager.on_fill()

LiveEngine
 └── Strategy.on_candle()
      └── generate intent
           └── OrderRouter.process_intent()
                └── RiskManager.allow_intent()
                     └── Broker.place_order()

