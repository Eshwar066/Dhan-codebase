# Order Logging Pipeline

This document describes how orders flow through the system and get logged to `/root/Dhan-codebase/logs` in **LIVE**, **PAPER**, and **BACKTEST** modes.

---

## Overview

The system uses a unified OMS (Order Management System) stack that works across all three modes:

```
┌─────────────────────────────────────────────────────────────────────┐
│                        STRATEGY LAYER                               │
│  SuperTrendStockRider, LEAPS_RSI, NiftyDOS, etc.                   │
│  → on_candle() → returns OrderIntent(s)                             │
└──────────────────────────┬──────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      ENGINE LAYER                                   │
│  BacktestEngine (BACKTEST) | LiveEngine (LIVE/PAPER)              │
│  → _run_entry() / _run_risk_and_rollover()                         │
│  → calls order_router.process_intent()                              │
└──────────────────────────┬──────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    ORDER ROUTER (core/orderExecution/order_router) │
│  process_intent()                                                   │
│  1. Risk checks                                                     │
│  2. Intent store persistence                                        │
│  3. Broker.place_order()                                            │
│  4. Broker calls process_fill() → PositionManager.on_fill()         │
│  5. PositionManager logs to TradeLogger                             │
└──────────────────────────┬──────────────────────────────────────────┘
                           │
               ┌───────────┴───────────┐
               ▼                       ▼
    ┌─────────────────────┐   ┌─────────────────────┐
    │   TRADES CSV        │   │   TRADE_LOG CSV     │
    │   (per-fill events) │   │   (round-trips)     │
    │   {strategy}_trades.csv    │   {strategy}_trade_log.csv    │
    │                     │   │   trade_log.csv     │
    └─────────────────────┘   └─────────────────────┘
```

---

## Component Details

### 1. Strategy Layer

Strategies return `OrderIntent` objects from:
- `on_candle()` - Entry signals
- `on_position_exit()` - Exit signals
- `should_exit()` - Risk-based exits
- `on_candle_rollover()` - Hedge rollovers

**Key method**: `map_instrument_to_intent()` / `create_order_intent()` (from `IndiaMktMixins`)

```python
# Example from SuperTrendStockRider
intent = self.map_instrument_to_intent(
    inst=instrument,
    strike_row=None,
    strategy=self.name,
    side="BUY",
    structure_id=f"{symbol}_{self.name}_ENTRY",
    candle_ts=pd.Timestamp(candle.get("timestamp")),
    tag="ST_GREEN",
    symbol=symbol,
    action="ENTRY",
    order_type="MARKET",
    metadata_extras={...}
)
```

---

### 2. Engine Layer

#### BacktestEngine (`core/engine/backtest_engine.py`)
- **Mode**: `RunMode.BACKTEST`
- **Broker**: `SimulatedBroker`
- **Flow**:
  1. `_run_entry()` - Called when `strategy.should_evaluate(candle)` is True
  2. `_run_risk_and_rollover()` - Always runs for exits/rollover
  3. Calls `order_router.process_intent(intent, price_map)`

#### LiveEngine (`core/engine/live_engine.py`)
- **Mode**: `RunMode.LIVE` or `RunMode.PAPER`
- **Broker**: `DhanBroker` / `DeltaBroker` / `KotakBroker` (LIVE) or `SimulatedBroker` (PAPER)
- **Flow**:
  1. Realtime feed → `on_candle()` → `build_context()` → strategy `on_candle()`
  2. Entry intents → `order_router.process_intent()`
  3. Exit monitoring via `evaluate_sim_broker_stops()` and position reconciliation

---

### 3. Order Router (`core/orderExecution/order_router.py`)

**Main entry point**: `process_intent()`

```python
def process_intent(
    self,
    intent,
    price_map,
    idempotency_key=None,
    raise_on_retryable_failure=False,
    skip_margin_check=False,
    bundle_margin_result=None,
    defer_broker_place=False,
):
```

**Flow**:
1. **Risk check** - `self.risk.allow_intent()`
2. **Intent store** - Create/update intent record
3. **Execution validation** (Delta only) - `_validate_intent_execution()`
4. **Place order** - `self.broker.place_order(intent, execution_price=exec_price)`
5. **Broker fills** - Calls back to `order_router.process_fill()`
6. **Process fill** - Updates PositionManager, logs trades

---

### 4. Broker Layer

#### SimulatedBroker (`core/broker/internal/simulated/broker.py`)
Used for **BACKTEST** and **PAPER** modes.

```python
def place_order(self, intent, execution_price=None, retries=0):
    # 1. Generate order_id
    order_id = f"SIM-{uuid.uuid4().hex[:10]}"
    
    # 2. Update intent store
    if self.intent_store:
        self.intent_store.update(intent.intent_id, "SENT")
    
    # 3. Handle special tags (MAIN_EXIT, MAIN_SL, MAIN_TARGET)
    # 4. For regular orders → instant fill via process_fill()
    if self.order_router:
        self.order_router.process_fill(
            instrument=instrument,
            side=intent.side,
            qty=fill_units,
            price=float(execution_price),
            ...
        )
    else:
        # Fallback direct to PositionManager
        self.position_manager.on_fill(...)
```

#### Live Brokers (DhanBroker, DeltaBroker, KotakBroker)
Used for **LIVE** mode only.
- Place real orders via exchange API
- Handle order updates via WebSocket (DhanOrderUpdateFeed, etc.)
- Reconcile positions periodically

---

### 5. Position Manager (`core/orderExecution/position_manager.py`)

**Central component** - tracks all positions and logs fills.

```python
def on_fill(
    self,
    instrument,
    side,
    qty,
    price,
    intent_id=None,
    order_id=None,
    strategy=None,
    structure_id=None,
    tag=None,
    candle_ts=None,
    action=None,
    metadata_extras=None,
    exit_reason=None,
    execution_source=None,
):
```

**Responsibilities**:
1. Update position state (qty, avg_price, realized_pnl, etc.)
2. **Log per-fill events** → `self.logger.log(strategy, row)` → writes `{strategy}_trades.csv`
3. **Log completed round-trips** → `self.logger.log_trade(trade_row)` → writes `{strategy}_trade_log.csv` AND `trade_log.csv`
4. Maintain `position_metadata` for strategy context
5. Trigger hooks: `on_main_entry_fill`, `on_main_exit_fill`

---

### 6. Trade Logger (`utils/logger/trade_logger.py`)

Two separate log files with different schemas:

#### TRADES_COLUMNS (per-fill events)
```python
TRADES_COLUMNS = [
    "candle_timestamp",
    "tag",
    "symbol",
    "trade_type",      # ENTRY, EXIT, SCALE_IN, FORCE_EXIT
    "side",            # BUY, SELL
    "qty",
    "price",
    "pnl",             # Only on EXIT/FORCE_EXIT
    "cumulative_pnl",  # Only on EXIT/FORCE_EXIT
    "net_qty_after",
    "execution_source",
    "mae",             # Only on EXIT
    "mfe",             # Only on EXIT
    "exit_reason",     # Only on EXIT
]
```
**File**: `logs/{strategy}_trades.csv`

#### TRADE_LOG_COLUMNS (completed round-trips)
```python
TRADE_LOG_COLUMNS = [
    "trade_id",
    "entry_time",
    "exit_time",
    "side",            # BUY (long) or SELL (short) - entry side
    "entry_price",
    "exit_price",
    "qty",
    "pnl",
    "collected_points",
    "symbol",
    "strategy",
    "exit_reason",
    "execution_source",
    # Optional strategy context (LiquiditySweep etc.)
    "swept_level", "zone_side", "zone_source", "zone_bar_key", "sweep_bar_key",
]
```
**Files**: 
- `logs/{strategy}_trade_log.csv` (per-strategy)
- `logs/trade_log.csv` (aggregate)

---

## Mode-Specific Differences

| Aspect | BACKTEST | PAPER | LIVE |
|--------|----------|-------|------|
| **Broker** | SimulatedBroker | SimulatedBroker | DhanBroker / DeltaBroker / KotakBroker |
| **Fill** | Instant (in-process) | Instant (in-process) | Async via WebSocket |
| **Price Source** | Historical data / indicator_history | Simulated (same as backtest) | Real market data |
| **Position Reconciliation** | N/A | N/A | Periodic via `reconcile_with_broker()` |
| **Order State** | Always FILLED | Always FILLED | PENDING → VALIDATED → SENT → FILLED |
| **Latency** | Configurable `latency_ms` (default 20ms) | Configurable `latency_ms` | Real network latency |

---

## Log File Structure

```
/root/Dhan-codebase/logs/
├── {strategy}_trades.csv          # Per-fill events (TRADES_COLUMNS)
├── {strategy}_trade_log.csv       # Round-trips (TRADE_LOG_COLUMNS)
├── trade_log.csv                  # Aggregate round-trips
├── {strategy}_sl_orders.csv       # SL/TARGET events (SimulatedBroker)
├── {strategy}/                    # Strategy-specific directory (if log_subdir set)
│   ├── {strategy}_trades.csv
│   ├── {strategy}_trade_log.csv
│   └── {engine_id}_open_positions.csv  # Live/PAPER only
├── calendars/                     # Economic event calendar
├── candles/                       # Candle cache
├── indicators/                    # Indicator history
├── option_chain_snapshots/        # Option chain snapshots
└── dhan_intent_pipeline.jsonl     # Intent pipeline debug
```

---

## Strategy-Specific Log Directory

Strategies can define `log_subdir` to isolate their logs:

```python
class SuperTrendStockRider(IndiaMktMixins, BaseStrategy):
    name = "SuperTrendStockRider"
    log_subdir = "SuperTrendStockRider"  # Creates logs/SuperTrendStockRider/
```

**Factory** (`core/engine/factory.py`) reads this:

```python
log_subdir = getattr(strategy, "log_subdir", None)
trade_logger_base_dir = os.path.join("logs", log_subdir) if log_subdir else "logs"
trade_logger = TradeLogger(base_dir=trade_logger_base_dir)
```

---

## Key Code Paths

### Entry Flow (All Modes)
```
Strategy.on_candle() 
  → returns OrderIntent
  → Engine._run_entry() 
  → OrderRouter.process_intent()
  → Broker.place_order()
  → OrderRouter.process_fill() (SimulatedBroker calls directly)
  → PositionManager.on_fill()
  → TradeLogger.log() + TradeLogger.log_trade()
```

### Exit Flow (All Modes)
```
Engine._run_risk_and_rollover()
  → Strategy.should_exit() / Strategy.on_position_exit()
  → OrderRouter.process_intent()
  → Broker.place_order()
  → OrderRouter.process_fill()
  → PositionManager.on_fill()
  → TradeLogger.log() + TradeLogger.log_trade()
```

### LIVE-Specific: Order Updates
```
DhanOrderUpdateFeed / KotakOrderUpdateFeed / DeltaWebSocketFeed
  → on_order_update()
  → OrderRouter.sync_orders()
  → OrderRouter.process_fill() (when fill detected)
  → PositionManager.on_fill()
  → TradeLogger.log()
```

---

## Debugging Tips

1. **Enable DEBUG prints** in:
   - `PositionManager.on_fill()` - Line 495
   - `OrderRouter.process_intent()` - Line 1782 (added temporarily)
   - `SimulatedBroker.place_order()` - Line 53 (added temporarily)

2. **Check log files**:
   ```bash
   tail -f logs/SuperTrendStockRider/SuperTrendStockRider_trades.csv
   tail -f logs/SuperTrendStockRider/SuperTrendStockRider_trade_log.csv
   ```

3. **Verify PositionManager logger**:
   ```python
   from core.orderExecution.position_manager import PositionManager
   from utils.logger.trade_logger import TradeLogger
   
   tl = TradeLogger(base_dir='logs/SuperTrendStockRider')
   pm = PositionManager(logger=tl)
   print(pm.logger.base_dir)  # Should show 'logs/SuperTrendStockRider'
   ```

---

## Common Issues

| Issue | Cause | Fix |
|-------|-------|-----|
| No trade logs in BACKTEST | `PositionManager.__init__` was creating new `TradeLogger()` instead of using passed logger | Fixed: use `self.logger = logger` |
| Logs in wrong directory | Strategy missing `log_subdir` or factory not reading it | Add `log_subdir = "StrategyName"` to strategy class |
| Duplicate fills logged | `process_fill` called multiple times (polling + WebSocket) | `_terminal_fill_reflected_in_pm()` deduplication in OrderRouter |
| Missing strategy name in logs | Intent not carrying strategy_id | Ensure `intent.strategy` is set (done in `map_instrument_to_intent`) |

---

## Related Files

- `core/strategies/base.py` - BaseStrategy interface
- `core/strategies/IndiaMktMixins.py` - Order intent creation helpers
- `core/engine/backtest_engine.py` - BACKTEST engine
- `core/engine/live_engine.py` - LIVE/PAPER engine
- `core/engine/factory.py` - EngineFactory (creates OMS stack)
- `core/orderExecution/order_router.py` - OrderRouter (central OMS)
- `core/orderExecution/position_manager.py` - PositionManager (position tracking + logging)
- `core/broker/internal/simulated/broker.py` - SimulatedBroker (BACKTEST/PAPER)
- `core/broker/internal/dhan/broker.py` - DhanBroker (LIVE)
- `utils/logger/trade_logger.py` - TradeLogger (CSV logging)
- `utils/logger/open_positions_logger.py` - OpenPositionsLogger (LIVE/PAPER)