# Order Execution

**Purpose:** Route intents from strategies through risk checks to the broker; positions update from **trade events** (fills), not order acks alone.

## Flow

```
Strategy.on_candle(candle, ctx)
    → OrderIntent(s)
        → LiveEngine intent queue
            → OrderRouter.process_intent(intent, price_map)
                → RiskManager.allow_intent(...)
                → Broker.place_order(intent, execution_price)
                → IntentStore (CREATED → VALIDATED → SENT → FILLED | REJECTED)
                → (on fill) PositionManager.on_fill → strategy hooks (on_main_entry_filled, …)
```

## Files

| File | Role |
|------|------|
| `order_router.py` | Risk, placement, trade-led sync, bundles, GTT sync |
| `gtt_fallback_book.py` | **HYBRID_GTT**: Forever order + engine ask watch + LIMIT fallback |
| `reentry_at_cost_book.py` | **reentry_at_cost**: after MAIN_SL, poll premium ≤ cost and re-enter same contract |
| `bracket_orders.py` | MAIN_SL / MAIN_TARGET sibling registry (OCO-style cancel) |
| `risk_manager.py` | `allow_intent`, kill switch, daily loss |
| `intent_store.py` | Intent lifecycle, idempotency, pending queries |
| `position_manager.py` | Positions, structure slices, hedge lookup, reconcile |
| `account_router.py` | Intent → account id mapping |
| `slippage.py` | Execution price adjustment |

## Execution modes (`metadata_extras.execution_mode`)

| Mode | Behavior |
|------|----------|
| *(default)* | Regular Dhan LIMIT / SL-M via `place_order` |
| `GTT` | Dhan Forever order; fill polled via `_sync_gtt_pending_fills` |
| `HYBRID_GTT` | GTT + `GttFallbackBook` watches bid/ask; cancels GTT and places resting LIMIT when trigger fires |

## Re-entry at cost (`reentry_at_cost`)

Strategies opt in via class attr and/or MAIN ENTRY `metadata_extras`:

```python
reentry_at_cost = {
    "enabled": True,
    "max_reentries": 1,
    "poll_interval_sec": 300,
    "min_premium": 0.1,
    "until_expiry": True,
}
```

OMS flow (Delta / LiveEngine):
1. `MAIN_SL` fill → `ReentryAtCostBook.maybe_arm_from_main_sl` (cost = entry premium)
2. Engine tick polls book; when premium ≤ cost, places same-contract MAIN ENTRY (`:R{n}`)
3. Stops when MAIN opens on that contract, max reentries hit, or expiry day ends
4. Persists under `logs/oms/reentry_at_cost.json`

Opt-in fallback spec (`gtt_fallback` in strategy_meta):
```python
{
    "trigger_field": "ask",      # ask | bid | ltp
    "trigger_op": "<=",          # <= | >=
    "active_until": "15:20",     # IST HH:MM cutoff
}
```

## Live pricing

Engine resolves **price_map** from websocket depth (`get_best_bid` / `get_best_ask`) before `process_intent`. Router prefers `price_map` over static intent.price.

## Risk manager

- **ENTRY**: funds/margin check when broker supports it; SPAN check for option shorts (`check_short_option_margin`).
- **EXIT / FORCE_EXIT**: never blocked by funds check (positions can always be closed).

## Intent lifecycle

`CREATED` → `VALIDATED` → `SENT` → `FILLED` | `REJECTED` | `CANCELLED` | `EXPIRED`

Order state cache in `OrderRouter._order_state` (persisted under `logs/`).

## Multi-leg bundles

- **HEDGE + MAIN ENTRY** (Dhan LEAPS): fill-gated — hedge BUY, wait fill, margin re-check, MAIN SELL.
- **Delta brackets**: MAIN_SL + MAIN_TARGET via `place_combined_bracket_orders`.

## Future / design notes (not implemented)

**Order slicing** (large qty into passive LIMIT slices at refreshed best bid/ask per account) belongs in OrderRouter but is **not implemented**. Current `structure_slice` in position_manager is **position accounting**, not execution slicing. See archived design notes in git history if needed.

## Dependencies

- `OrderIntent` — `core.models.order_intent`
- `StrategyContext` — `core.models.strategy_context`
- Brokers — `core.broker.internal.dhan`, `delta`, `simulated`
