# .option_identity_key

> 23 nodes

## Key Concepts

- **.option_identity_key()** (14 connections) — `core/utils/expiry_resolver.py`
- **.reconcile_positions_on_start()** (13 connections) — `core/engine/live_engine.py`
- **._ensure_bracket_legs_after_reconcile()** (12 connections) — `core/engine/live_engine.py`
- **._apply_manual_flat_closes_after_reconcile()** (11 connections) — `core/engine/live_engine.py`
- **._configure_gtt_fallback_book()** (8 connections) — `core/engine/live_engine.py`
- **._bracket_leg_satisfied()** (7 connections) — `core/engine/live_engine.py`
- **._resolve_position_ownership_from_intent_store()** (6 connections) — `core/engine/live_engine.py`
- **.parse_dhan_space_option_symbol()** (6 connections) — `core/utils/expiry_resolver.py`
- **._broker_open_qty_map()** (5 connections) — `core/engine/live_engine.py`
- **._adopt_exchange_bracket_leg()** (4 connections) — `core/engine/live_engine.py`
- **._restore_strategies_after_reconcile()** (4 connections) — `core/engine/live_engine.py`
- **_broker_confirms_open()** (3 connections) — `core/engine/live_engine.py`
- **._nse_session_open_for_manual_flat()** (3 connections) — `core/engine/live_engine.py`
- **Attach strategy/structure_id/intent_id from intent_store when reconcile lacked…** (1 connections) — `core/engine/live_engine.py`
- **Link a manually placed or recovered exchange bracket leg into OMS.** (1 connections) — `core/engine/live_engine.py`
- **If MAIN is open but bracket legs missing (restart), re-arm per strategy.** (1 connections) — `core/engine/live_engine.py`
- **NSE cash session 09:15–15:30 IST — only then treat empty book as real flat.** (1 connections) — `core/engine/live_engine.py`
- **Map engine/identity keys → abs qty for flat detection.** (1 connections) — `core/engine/live_engine.py`
- **Manual square-off sync (Dhan) after broker reconcile. Contract: - Market hours…** (1 connections) — `core/engine/live_engine.py`
- **Fetch broker positions, sync PositionManager to broker truth, log any mismatch.…** (1 connections) — `core/engine/live_engine.py`
- **Call each strategy's restore_state_on_startup (not only self.strategy).** (1 connections) — `core/engine/live_engine.py`
- **Parse Dhan place-order / SEM_CUSTOM_SYMBOL form. ``BANKNIFTY 28 JUL 56300 PUT``…** (1 connections) — `core/utils/expiry_resolver.py`
- **Stable identity across compact vs space Dhan symbols (ignores expiry day/year).…** (1 connections) — `core/utils/expiry_resolver.py`

## Relationships

- [LiveEngine](LiveEngine.md) (11 shared connections)
- [Any](Any.md) (6 shared connections)
- [._on_pm_main_entry_fill_impl](_on_pm_main_entry_fill_impl.md) (5 shared connections)
- [._broker_position_row_for_intent](_broker_position_row_for_intent.md) (4 shared connections)
- [BankNiftyBTST](BankNiftyBTST.md) (3 shared connections)
- [.reconcile_with_broker](reconcile_with_broker.md) (3 shared connections)
- [DeltaBroker](DeltaBroker.md) (2 shared connections)
- [BidAskLtp](BidAskLtp.md) (2 shared connections)
- [.start](start.md) (2 shared connections)
- [Order Execution](Order_Execution.md) (2 shared connections)
- [GttFallbackBook](GttFallbackBook.md) (2 shared connections)
- [typing](typing.md) (2 shared connections)

## Source Files

- `core/engine/live_engine.py`
- `core/utils/expiry_resolver.py`

## Audit Trail

- EXTRACTED: 65 (81%)
- INFERRED: 15 (19%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*