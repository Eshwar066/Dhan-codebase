# .create_live_engine

> 27 nodes

## Key Concepts

- **.create_live_engine()** (53 connections) — `core/engine/factory.py`
- **EngineFactory** (46 connections) — `core/engine/factory.py`
- **.create_backtest_engine()** (20 connections) — `core/engine/factory.py`
- **main()** (12 connections) — `core/strategies/IBBM/Leaps/emergency/retry_leaps_main.py`
- **.create_engine()** (10 connections) — `core/engine/factory.py`
- **._universe_service()** (7 connections) — `core/engine/factory.py`
- **get_strategy_config()** (7 connections) — `core/strategies/registry.py`
- **._attach_engine_context()** (6 connections) — `core/engine/factory.py`
- **._instrument_store()** (6 connections) — `core/engine/factory.py`
- **._resolve_ipo_symbols()** (5 connections) — `core/engine/factory.py`
- **Implementations** (5 connections) — `core/data/feeds/README.md`
- **._strategy_feed_timeframe()** (4 connections) — `core/engine/factory.py`
- **send_telegram_alert()** (4 connections) — `core/utils/telegram_alert.py`
- **telegram_alert()** (3 connections) — `core/engine/factory.py`
- **exit_price()** (1 connections) — `core/strategies/IBBM/Leaps/emergency/retry_leaps_main.py`
- **place()** (1 connections) — `core/strategies/IBBM/Leaps/emergency/retry_leaps_main.py`
- **Any** (1 connections)
- **Finest (smallest) strategy timeframe for Delta WS candle channel.** (1 connections) — `core/engine/factory.py`
- **Build engine from config. Backtest vs Live is determined by config.run_mode.** (1 connections) — `core/engine/factory.py`
- **Build BacktestEngine with isolated stack for config.broker_name.** (1 connections) — `core/engine/factory.py`
- **Build LiveEngine with isolated stack for config.broker_name. PAPER:…** (1 connections) — `core/engine/factory.py`
- **Build venue-specific InstrumentStore (same class, different paths).** (1 connections) — `core/engine/factory.py`
- **For IPOBreakout with symbols None/empty: get IPO equities, filter, cap, set…** (1 connections) — `core/engine/factory.py`
- **Build EquityUniverseService for DHAN equity strategies only. Never raises: on…** (1 connections) — `core/engine/factory.py`
- **Creates BacktestEngine or LiveEngine with a fully isolated OMS stack. No shared…** (1 connections) — `core/engine/factory.py`
- *... and 2 more nodes in this community*

## Relationships

- [EngineConfig](EngineConfig.md) (9 shared connections)
- [factory.py](factory.py.md) (8 shared connections)
- [RunMode](RunMode.md) (5 shared connections)
- [dummy_live.py](dummy_live.py.md) (4 shared connections)
- [main.py](main.py.md) (4 shared connections)
- [PositionManager](PositionManager.md) (4 shared connections)
- [force_leaps_cycle.py](force_leaps_cycle.py.md) (3 shared connections)
- [roll_leaps_hedge.py](roll_leaps_hedge.py.md) (3 shared connections)
- [BacktestEngine](BacktestEngine.md) (3 shared connections)
- [LiveEngine](LiveEngine.md) (3 shared connections)
- [DeltaSource](DeltaSource.md) (3 shared connections)
- [DhanSource](DhanSource.md) (3 shared connections)

## Source Files

- `core/data/feeds/README.md`
- `core/engine/factory.py`
- `core/strategies/IBBM/Leaps/emergency/retry_leaps_main.py`
- `core/strategies/registry.py`
- `core/utils/telegram_alert.py`

## Audit Trail

- EXTRACTED: 123 (77%)
- INFERRED: 37 (23%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*