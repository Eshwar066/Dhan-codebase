# Live Engine

Implementation: `core/engine/live_engine.py` (+ `live_engine_common.py`, `execution_engine.py`)

## Responsibilities

- WebSocket feed → tick queue → `CandleAggregator` (closed bars only)
- **Scheduled eval** (`scheduled_times` on strategy, e.g. BankNiftyBTST)
- **Feed eval** (`should_evaluate` + `on_candle` per strategy timeframe)
- Per-strategy worker threads → intent queue → account router → OMS workers
- Startup broker reconciliation, feed health, kill switch integration
- `GttFallbackBook.tick()` each main loop (~1s) when HYBRID_GTT watches active

## Live vs backtest

| Concern | BacktestEngine | LiveEngine |
|---------|----------------|------------|
| Data | Historical candles | WS feed + aggregator or scheduled spot |
| Broker | SimulatedBroker | Dhan / Delta / Simulated (PAPER) |
| Eval | Every bar in loop | Closed bar or wall-clock slot |
| Exits + rollover | Every bar (`_run_risk_and_rollover`) | Every closed 60m bar (`_run_exits_and_rollover`) + strategy eval |
| Entries | Gated on `should_evaluate` | Same |
| GTT / HYBRID_GTT | Not used (BTST uses LIMIT) | Dhan Forever + GttFallbackBook |
| Pricing | Chain LTP / candle | Depth → `price_map` |

## Strategy eval modes (`strategy_eval_modes` / `runtime_spec`)

| Mode | When |
|------|------|
| `live_feed` | Candle aggregator + strategy `timeframe` |
| `scheduled` | `strategy.scheduled_times` IST wall clock (no TF candles) |

## Risk blocks (`risk_manager.is_engine_blocked()`)

Engine skips **entries** when:

- Daily max loss / capital bucket breached
- Kill switch (broker failures, manual)
- Feed stale / memory / latency guards (entries paused)
- Order state mismatch (configurable)

Exits and hedge rollover still run where implemented.

## Institutional upgrades (roadmap)

- Slippage / execution quality metrics per fill
- Spread-based entry block (partially in `live_engine_common._is_spread_acceptable`)
- Scheduled RiskManager daily reset
- Latency histograms
- Periodic position reconcile timer

## Related docs

- Root `README.md` — full live pipeline
- `docs/runtime_flow.md`, `docs/oms_flow.md`
- `docs/EVENT_DRIVEN_STRATEGY_GUIDE.md` — adding strategies
