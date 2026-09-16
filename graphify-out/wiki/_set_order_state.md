# ._set_order_state

> 25 nodes

## Key Concepts

- **._set_order_state()** (22 connections) — `core/orderExecution/order_router.py`
- **.process_trade()** (16 connections) — `core/orderExecution/order_router.py`
- **.process_fill()** (15 connections) — `core/orderExecution/order_router.py`
- **._instrument_trading_symbol()** (11 connections) — `core/orderExecution/order_router.py`
- **._poll_and_sync_intent_terminal()** (11 connections) — `core/orderExecution/order_router.py`
- **._apply_gtt_fill_from_intent()** (10 connections) — `core/orderExecution/order_router.py`
- **._adopt_main_entry_shadow_fill()** (8 connections) — `core/orderExecution/order_router.py`
- **._terminal_fill_reflected_in_pm()** (8 connections) — `core/orderExecution/order_router.py`
- **._emit_bus_fill_events()** (6 connections) — `core/orderExecution/order_router.py`
- **.report_fill()** (6 connections) — `core/orderExecution/order_router.py`
- **TestProcessTradeEmitsBusFill** (4 connections) — `core/orderExecution/test_process_trade_reentry_bus.py`
- **._find_broker_order_for_intent()** (4 connections) — `core/orderExecution/order_router.py`
- **normalize_fill_side()** (3 connections) — `core/orderExecution/order_router.py`
- **._maybe_cancel_bracket_sibling_after_exit()** (3 connections) — `core/orderExecution/order_router.py`
- **resolve_fill_candle_ts()** (2 connections) — `core/orderExecution/order_router.py`
- **.test_process_trade_emits_intent_filled_for_main_sl()** (2 connections) — `core/orderExecution/test_process_trade_reentry_bus.py`
- **Update in-memory cache, append detailed log entry, and persist to JSON.** (1 connections) — `core/orderExecution/order_router.py`
- **Poll broker for one intent; sync fill/reject into intent_store when terminal.** (1 connections) — `core/orderExecution/order_router.py`
- **Apply a discovered GTT fill and run MAIN entry hooks (SL placement).** (1 connections) — `core/orderExecution/order_router.py`
- **Resolve PM/broker symbol from an Instrument instance or serialized dict.** (1 connections) — `core/orderExecution/order_router.py`
- **True only if PositionManager already matches this terminal fill — safe to skip…** (1 connections) — `core/orderExecution/order_router.py`
- **Broker/reconcile already shows the correct net qty for a MAIN ENTRY, but PM…** (1 connections) — `core/orderExecution/order_router.py`
- **Single entry point for fill processing. Call from broker fill callback or…** (1 connections) — `core/orderExecution/order_router.py`
- **Trade-led OMS: update position from a trade event (fill). Orders are metadata;…** (1 connections) — `core/orderExecution/order_router.py`
- **Logs order_filled and high_slippage_warning if above threshold. Called by…** (1 connections) — `core/orderExecution/order_router.py`

## Relationships

- [OrderRouter](OrderRouter.md) (21 shared connections)
- [Any](Any.md) (18 shared connections)
- [RunMode](RunMode.md) (5 shared connections)
- [Order Execution](Order_Execution.md) (3 shared connections)
- [._broker_position_row_for_intent](_broker_position_row_for_intent.md) (3 shared connections)
- [.sync_trades_from_broker](sync_trades_from_broker.md) (3 shared connections)
- [TradeLogger](TradeLogger.md) (2 shared connections)
- [EventType](EventType.md) (1 shared connections)
- [make_event](make_event.md) (1 shared connections)
- [._refresh_stale_limit_orders](_refresh_stale_limit_orders.md) (1 shared connections)
- [._maybe_tick_reentry_at_cost](_maybe_tick_reentry_at_cost.md) (1 shared connections)
- [.seed_filled_intents_from_open_positions_csv](seed_filled_intents_from_open_positions_csv.md) (1 shared connections)

## Source Files

- `core/orderExecution/order_router.py`
- `core/orderExecution/test_process_trade_reentry_bus.py`

## Audit Trail

- EXTRACTED: 93 (93%)
- INFERRED: 7 (7%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*