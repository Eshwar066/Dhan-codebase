# Production Upgrades Summary

## 1. Broker position reconciliation (critical)

- **LiveEngine.reconcile_positions_on_start()**  
  Fetches open positions from broker (`broker.get_positions_for_recon()`), compares with `PositionManager.snapshot()`, syncs PM to broker truth via `position_manager.reconcile_with_broker(broker_positions)`, and logs any mismatch (structured log event `reconciliation`).
- **When**  
  Called at the start of `LiveEngine.start()`, before the main loop.
- **Broker**  
  `BaseBroker.get_positions_for_recon()` returns `{}`; **DhanBroker** and **DeltaBroker** implement it (same format as used in `sync_positions`).
- **PositionManager.reconcile_with_broker(broker_positions, drift_threshold=0)**  
  Uses correct `Instrument(...)` constructor; optional `drift_threshold`; no undefined `threshold`.

## 2. Risk kill switch (engine-level)

- **RiskManager**
  - **Config:** `daily_max_loss`, `max_open_positions`, `max_symbol_exposure`, `max_portfolio_exposure` (and `max_total_exposure` alias), `capital`, `risk_per_trade_percent` → `max_risk_amount = capital * risk_per_trade_percent / 100`.
  - **is_engine_blocked()** → `True` when kill switch is on.
  - **trigger_kill_switch(reason)** → Sets block and logs (engine_logger.kill_switch or print fallback).
  - **record_realized_pnl(amount)** / **reset_daily()** for daily PnL and daily_max_loss.
- **allow_intent**  
  Exit/force-exit always allowed; entry blocked if kill switch or any limit breached. All rejections logged via `engine_logger.risk_block` when present.
- **LiveEngine**  
  Checks `risk_manager.is_engine_blocked()` at the start of each loop iteration and skips entry processing when blocked.

## 3. Closed-candle validation

- **LiveEngine._is_closed_candle(candle, timeframe, now)**  
  Ensures candle timestamp is not in the future and is aligned to the timeframe boundary (e.g. 60 → hourly).
- **Flow**  
  Before `should_evaluate` / `build_context`, if `not _is_closed_candle(candle, tf)` we skip evaluation and log `closed_candle_skip` (debug).
- **get_last_candle()**  
  Still provided by feed/candle_service; engine only evaluates when `_is_closed_candle` passes.

## 4. Structured JSON logging

- **logs/engine_logger.py**  
  **EngineLogger(engine_id, venue, strategy, log_dir)** writes one JSON object per line to `logs/{engine_id}.log`.
- **Events:** `order_placed`, `order_filled`, `exit_triggered`, `risk_block`, `reconciliation`, `websocket_disconnect`, `kill_switch`, `latency`, `feed_health_warning`, `closed_candle_skip`, `eod_export`, `engine_start`.
- **No print()** in LiveEngine or RiskManager when engine_logger is set; OrderRouter logs order_placed when engine_logger is set.

## 5. WebSocket feed health

- **LiveEngine**
  - **last_tick_timestamp / last_candle_timestamp** per symbol (updated when data is received).
  - **check_feed_health()**  
    If no data for a symbol for `feed_stale_seconds` (default 60), logs `feed_health_warning` and sets `_entries_paused_feed_stale` so entries can be skipped (optional).
  - Called periodically inside the main loop.

## 6. End-of-day export

- **LiveEngine._export_eod(date_str)**  
  Writes `reports/{engine_id}_{YYYYMMDD}.csv` with columns: symbol, qty, avg_price, realized_pnl, unrealized_pnl (open positions only).
- **When**  
  Once per day (date change) in the main loop (every 60 iterations we check and export previous day if date changed).

## 7. Capital bucket per engine

- **EngineConfig**  
  **capital**, **risk_per_trade_percent** (and optional **daily_max_loss**).
- **RiskManager**  
  **max_risk_amount = capital * (risk_per_trade_percent / 100)**; entry blocked if trade exposure > max_risk_amount. Exposure and position limits use engine-level config only; no shared capital.

## 8. Latency metrics

- **LiveEngine**  
  Measures strategy evaluation time and time to send order; logs structured **latency** event: `strategy_time_ms`, `broker_latency_ms`, `total_latency_ms`.

---

## Example EngineConfig with capital

```python
from run.engine_config import EngineConfig
from run.config import RunMode

config = EngineConfig(
    broker_name="DELTA",
    run_mode=RunMode.LIVE,
    strategy_name="FuturesEMAHighLow",
    symbols=["BTCUSD"],
    engine_id="delta_futures_ema",
    capital=200_000.0,
    risk_per_trade_percent=1.0,
    daily_max_loss=5_000.0,  # optional
    backtest={...},
    live={...},
)
```

See **run/engine_config.py** for `example_dhan_live_config()` and `example_delta_live_config()` with capital.

---

## BacktestEngine

- **Unchanged.** No reconciliation, kill switch, feed health, or EOD export. No engine_logger or capital in factory for backtest.

## Modularity

- All new behaviour is per-engine (one broker, one OMS). No global mutable state. No Redis/DB; file-based logs and reports.
