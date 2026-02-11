# Core models

Shared dataclasses and value objects used across engine, strategies, and order execution.

## Files

| File | Role |
|------|------|
| **order_intent.py** | **OrderIntent** – immutable intent: intent_id, instrument, side, qty, price, order_type, strategy, structure_id, tag, symbol, action, candle_ts, parent_intent_id. Created by strategies; consumed by OrderRouter and brokers. |
| **strategy_context.py** | **StrategyContext** – typed context passed to strategies: symbol, exchange, timestamp, spot_price, instrument_store, position_store, option_chain_service; mutable fields expiry_list, selected_expiry, otm_strikes, instrument. Built in `base_engine.build_context(candle)`. |

Use **StrategyContext** (not a dict) so the IDE can autocomplete and refactoring stays safe. Use **OrderIntent** for all order-like intents (entry, exit, hedge).
