# Order Execution

**Purpose:** Route intents from strategies through risk checks to the broker and update positions. Uses **OrderIntent** (dataclass) and **StrategyContext** (typed context from engine).

## Flow

```
Strategy.on_candle(candle, ctx: StrategyContext)
    → returns OrderIntent(s)
        → OrderRouter.process_intent(intent, price_map)
            → RiskManager.allow_intent(intent, price_map)
            → Broker.place_order(intent, execution_price)
            → IntentStore.update(...)
            → (on fill) PositionManager.on_fill(...)
```

## Files

| File | Role |
|------|------|
| `order_router.py` | `process_intent(intent, price_map)` – risk check, slippage, broker.place_order, intent_store update |
| `risk_manager.py` | `allow_intent(intent, price_map, candle_ts)` – position limits, exposure, duplicate prevention |
| `intent_store.py` | Intent lifecycle: CREATED → SENT → FILLED / REJECTED; idempotency |
| `position_manager.py` | Positions, `on_fill()`, `get_open_positions()`, `get_hedge_for()`, `has_open_structure()`, reconcile_with_broker |
| `order_state.py` | Order state tracking (if used) |
| `slippage.py` | Slippage model for execution price |

## Intent lifecycle

- **CREATED** – strategy produced intent
- **VALIDATED** – risk manager allowed (conceptually; router may not persist this)
- **SENT** – passed to broker
- **FILLED** / **REJECTED** – after broker response / fill

## Dependencies

- **OrderIntent** from `core.models.order_intent`
- **Broker** (BaseBroker impl) from `core.broker`
- **StrategyContext** built in `core.engine.base_engine.build_context()`

## Risk Manager

Answers: *“Is this intent safe to execute given current positions and limits?”*

Can include: portfolio exposure, per-symbol limits, max position size, no double-direction entries, strategy-level limits, cooldown. Extend in `risk_manager.py`.
