# SimulatedBroker

> 29 nodes

## Key Concepts

- **SimulatedBroker** (34 connections) — `core/broker/internal/simulated/broker.py`
- **Any** (9 connections)
- **._append_sl_order_event()** (6 connections) — `core/broker/internal/simulated/broker.py`
- **.cancel_pending_sl()** (6 connections) — `core/broker/internal/simulated/broker.py`
- **.evaluate_pending_stops()** (6 connections) — `core/broker/internal/simulated/broker.py`
- **._cancel_bracket_record()** (5 connections) — `core/broker/internal/simulated/broker.py`
- **.cancel_pending_bracket()** (5 connections) — `core/broker/internal/simulated/broker.py`
- **.cancel_pending_target()** (5 connections) — `core/broker/internal/simulated/broker.py`
- **.place_order()** (5 connections) — `core/broker/internal/simulated/broker.py`
- **._evaluate_pending_book()** (4 connections) — `core/broker/internal/simulated/broker.py`
- **.exit_position()** (3 connections) — `core/broker/internal/simulated/broker.py`
- **.find_order_by_client_id()** (3 connections) — `core/broker/internal/simulated/broker.py`
- **.get_fill_by_order_id()** (3 connections) — `core/broker/internal/simulated/broker.py`
- **.get_fill_for_client_order_id()** (3 connections) — `core/broker/internal/simulated/broker.py`
- **.get_open_orders()** (3 connections) — `core/broker/internal/simulated/broker.py`
- **.get_recent_fills()** (3 connections) — `core/broker/internal/simulated/broker.py`
- **.__init__()** (3 connections) — `core/broker/internal/simulated/broker.py`
- **.get_positions_for_recon()** (2 connections) — `core/broker/internal/simulated/broker.py`
- **._sl_orders_log_path()** (2 connections) — `core/broker/internal/simulated/broker.py`
- **Used for both PAPER and BACKTEST: instant fill, no real exchange. Same contract…** (1 connections) — `core/broker/internal/simulated/broker.py`
- **Remove resting MAIN_SL (OCO sibling fill or MAIN_EXIT).** (1 connections) — `core/broker/internal/simulated/broker.py`
- **Remove resting MAIN_TARGET (OCO sibling fill or MAIN_EXIT).** (1 connections) — `core/broker/internal/simulated/broker.py`
- **Resting MAIN_SL / MAIN_TARGET: SL lte/gte per side; target profit gte for long…** (1 connections) — `core/broker/internal/simulated/broker.py`
- **Return PositionManager state in same format as live brokers so reconcile is a…** (1 connections) — `core/broker/internal/simulated/broker.py`
- **Paper: no open orders (instant fill). Same interface as live so order-state…** (1 connections) — `core/broker/internal/simulated/broker.py`
- *... and 4 more nodes in this community*

## Relationships

- [RunMode](RunMode.md) (4 shared connections)
- [.create_live_engine](create_live_engine.md) (2 shared connections)
- [BaseBroker](BaseBroker.md) (2 shared connections)
- [KotakBroker](KotakBroker.md) (2 shared connections)
- [.update_pending_sl_trigger](update_pending_sl_trigger.md) (2 shared connections)
- [Component Details](Component_Details.md) (2 shared connections)
- [._maybe_switch_premium_sl_to_index](_maybe_switch_premium_sl_to_index.md) (2 shared connections)
- [factory.py](factory.py.md) (1 shared connections)
- [Kotak Neo dual-broker smoke checklist](Kotak_Neo_dual-broker_smoke_checklist.md) (1 shared connections)
- [Algo - Multi-Venue Trading System](Algo_-_Multi-Venue_Trading_System.md) (1 shared connections)
- [normalize_fill_side](normalize_fill_side.md) (1 shared connections)

## Source Files

- `core/broker/internal/simulated/broker.py`

## Audit Trail

- EXTRACTED: 61 (87%)
- INFERRED: 9 (13%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*