Final Model:
    Strategy
      ↓
    IntentStore (CREATED)
      ↓
    RiskManager (VALIDATED)
      ↓
    ExecutionEngine
      ↓
    Slippage Model
      ↓
    DhanBroker.place_order()
      ↓
    ACKNOWLEDGED
      ↓
    Broker Fill
      ↓
    PositionManager Update
      ↓
    IntentStore → FILLED

======================================

execution/
│
├── execution_engine.py
├── order_state.py
├── dhan_broker.py
├── risk_manager.py
├── position_manager.py
├── intent_store.py
├── slippage.py
└── logger.py



**Intent:**
    Strategy → Intent Store → Risk Manager → Execution Engine → Broker

    Risk manager reads intents from store:
        position limits
        daily loss limits
        exposure caps
        margin checks
        duplicate order prevention

        Only approved intents move forward


    State tracking & lifecycle
        CREATED
        → VALIDATED
    strategy.py
      → generate_signal()
      → create_intent()

    intent_store.py
      → save_intent()
      → mark_status()

    risk_manager.py
      → validate_intent()

    execution.py
      → place_order()
        → ACKNOWLEDGED
        → FILLED / REJECTED

    🔹 Pro-level features (optional but powerful)

    Advanced intent stores include:

    🔹 Priority queue

    Urgent exits first.

    🔹 Idempotency keys

    Avoid duplicate orders.

    🔹 Intent throttling

    Control order burst.

    🔹 Intent expiration

    Cancel stale signals.

**PositionManager**
    Strategy
        ↓
      Create Intent
        ↓
      Intent Store
        ↓
      Risk Manager checks vs PositionManager
        ↓
      Execution Engine places order
        ↓
      Broker Fill
        ↓
      PositionManager updates
        ↓
      Intent status updated to FILLED

**Risk Manager**
    A RiskManager sits between:
    IntentStore → RiskManager → Execution
                 ↑
          PositionManager

    It answers one question:

    ✅ “Is this intent safe to execute given current positions and limits?”

    Below is a practical, production-style risk_manager.py that plugs directly into your PositionManager.

    It includes:

    ✅ Portfolio exposure limits
    ✅ Per-symbol limits
    ✅ Max position size
    ✅ No double-direction entries
    ✅ Strategy-level limits
    ✅ Simple cooldown protection
    ✅ Easy to extend

    Strategy → Intent
    intent = {
    "symbol": "NIFTY24FEB22000CE",
    "side": "BUY",
    "qty": 50,
    "price": 120,
    "instrument": instrument,
    "strategy": "RSI"
    }


<!-- Next -->
Dhan SLM order