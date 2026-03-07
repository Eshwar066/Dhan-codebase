# Project optimization audit

Deep-dive against README and codebase. Recommendations are ordered by impact and effort.

---

## 1. High impact / production safety

### 1.1 Bounded tick queue (recommended)

**Issue:** `queue.Queue()` has no `maxsize`. At sustained 1000+ ticks/sec, if the loop is slow (e.g. strategy or I/O), the queue can grow unbounded and increase memory.

**Fix:** Use a bounded queue in the factory, e.g. `queue.Queue(maxsize=50000)`. When full, feed’s `put_nowait` will raise; catch and drop or log occasionally so the producer thread doesn’t block.

**Where:** `core/engine/factory.py` (both Delta and Dhan tick_queue creation).

---

### 1.2 Hook `record_realized_pnl` when a position closes — **IMPLEMENTED**

**Issue:** README (checklist #20) says: “Hook RiskManager.record_realized_pnl(amount) when a position is closed … so daily_max_loss is accurate.” PositionManager computed `realized_pnl` in `Position.update_fill()` when `net_qty` went to 0, but nothing called `risk_manager.record_realized_pnl(pnl)`.

**Implemented:** OrderRouter is the single fill-processing boundary. `OrderRouter.process_fill(instrument, side, qty, price, ...)` calls `PositionManager.on_fill()` (which now returns `(position_closed, realized_pnl)`); when `position_closed`, calls `risk_manager.record_realized_pnl(realized_pnl)`. SimulatedBroker and factory wire broker → `order_router.process_fill()`. BaseBroker has `set_order_router()` so live brokers (Dhan/Delta) can call `order_router.process_fill()` when they add fill callbacks. No RiskManager in PositionManager; domain layers stay clean.

---

### 1.3 Reset pause flags when conditions improve

**Issue:** `_entries_paused_memory` and `_entries_paused_feed_stale` are set when memory is high or feed is stale but are never cleared when memory drops or feed recovers. Entries stay paused until restart.

**Fix:** In the same loop where you set them:
- If memory is below threshold, set `_entries_paused_memory = False`.
- If feed is connected and all symbols have recent data, set `_entries_paused_feed_stale = False`.

**Where:** `core/engine/live_engine.py` (`_check_memory`, `check_feed_health`).

---

## 2. Performance / scalability

### 2.1 Shorter sleep when using CandleAggregator

**Issue:** Main loop always does `time.sleep(1)`. With aggregator + high tick rate, draining 10k ticks then sleeping 1s can allow queue buildup (e.g. 15k ticks/sec → 5k growth per second).

**Fix:** When `tick_queue` and `candle_aggregator` are set, use a shorter sleep (e.g. `time.sleep(0.1)` or `0.05`) so the loop runs more often and keeps the queue under control. Keep 1s when not using aggregator.

**Where:** `core/engine/live_engine.py` (end of `while not self._shutdown_requested`).

---

### 2.2 Avoid heavy datetime in hot path

**Issue:** `_is_closed_candle()` uses `dt.datetime.utcnow()`, epoch, `total_seconds()`, and timezone handling per candle per symbol every cycle. With many symbols this adds up.

**Fix:** Compute `now = dt.datetime.utcnow()` once per loop iteration and pass it into `_is_closed_candle(candle, tf, now=now)`. Small change, same semantics.

**Where:** `core/engine/live_engine.py`.

---

### 2.3 CandleService / pandas in live path

**Issue:** README and spec say “No pandas in live path”. `CandleService.get_latest_closed()` is used as fallback when aggregator has no candle (or when not using aggregator); it uses `get_intraday()` (DataFrame), `.iloc`, `SessionManager`, RSI with talib, etc.

**Fix (options):**  
- Prefer not calling CandleService when aggregator is active (only use aggregator’s closed candles; wait for first closed bar).  
- Or add a lightweight “last closed candle only” REST path that returns one candle (no DataFrame) for that fallback.  
- Or document that CandleService fallback is the exception where pandas is allowed (and throttle/cache it heavily).

---

### 2.4 BacktestEngine: avoid `iterrows()`

**Issue:** `for _, row in df.iterrows()` is slow for large DataFrames.

**Fix:** Use `for idx in range(len(df)): row = df.iloc[idx]` or convert to list of dicts once and iterate, or use `itertuples()` for numeric-heavy rows. Removes one performance bottleneck in backtest.

**Where:** `core/engine/backtest_engine.py`.

---

## 3. Code quality / maintainability

### 3.1 README checklist stale

**Issue:** Checklist #18: “Add **DhanWebSocketFeed** … when Dhan exposes a WebSocket API” — DhanWebSocketFeed is already implemented and wired.

**Fix:** Update to something like: “DhanWebSocketFeed is implemented; use **DhanDepthFeed** when strategies need full market depth.”

**Where:** `README.md`.

---

### 3.2 BacktestEngine debug code

**Issue:** `import pdb` and commented `# pdb.set_trace()` and other commented debug blocks.

**Fix:** Remove `pdb` import and commented debug code for production cleanliness.

**Where:** `core/engine/backtest_engine.py`, and any similar in `position_manager.py` if desired.

---

### 3.3 Feed health: log throttle

**Issue:** `check_feed_health()` can log one warning per stale symbol every loop (e.g. 100 symbols → 100 log lines per second).

**Fix:** Log once per cycle (e.g. “Feed stale for N symbols: …”) or throttle per symbol (e.g. log each symbol at most once every 60s).

**Where:** `core/engine/live_engine.py` (`check_feed_health`).

---

## 4. Optional / future

- **Candle aggregator timeframe helper:** `_tf_to_minutes` exists in LiveEngine and CandleService; aggregator has `_resolution_to_seconds`. Could centralize in one small util (e.g. `core/utils/timeframe.py`) to avoid drift.
- **EngineConfig from run/config:** Strategy timeframe is taken from `config.backtest.get("timeframe", "60")` for Delta feed; strategy’s own `timeframe` is used for aggregator. Ensure job’s backtest/live timeframe and strategy’s `timeframe` stay aligned in config.
- **Supervisor + aggregator:** If Supervisor runs multiple live engines with aggregator, each engine already has its own queue and aggregator; no extra change needed for isolation.

---

## Summary table

| # | Item                         | Area           | Effort | Impact        |
|---|------------------------------|----------------|--------|---------------|
| 1.1 | Bounded tick queue          | Factory        | Low    | High (memory) |
| 1.2 | record_realized_pnl hook    | OMS / Risk     | Medium | High (risk)   |
| 1.3 | Reset pause flags           | LiveEngine     | Low    | Medium        |
| 2.1 | Shorter sleep w/ aggregator | LiveEngine     | Low    | Medium        |
| 2.2 | Cache `now` in loop         | LiveEngine     | Low    | Low–Medium    |
| 2.3 | CandleService / pandas      | Data           | Medium | Medium        |
| 2.4 | Backtest iterrows           | BacktestEngine | Low    | Low (backtest)|
| 3.1 | README checklist            | Docs           | Low    | Clarity       |
| 3.2 | Remove pdb / debug          | BacktestEngine | Low    | Clarity       |
| 3.3 | Feed health log throttle    | LiveEngine     | Low    | Log volume    |

Implementing 1.1 (bounded queue), 1.3 (reset pause flags), 3.1 (README), and 2.1 (shorter sleep with aggregator) gives the best balance of safety and behavior with minimal risk.




<!-- Double check this -->

If multiple fills complete the close:

Example:

Long 100
Sell 40
Sell 30
Sell 30

On final 30:

prev_qty = 30

new_qty = 0

position_closed = True

You must ensure:

pos.realized_pnl contains the full accumulated realized PnL,
not just last leg PnL.

If that is true → system is correct.

If you only store per-fill realized PnL → you must accumulate before reporting.

Double-check that.


