# BacktestEngine

> 27 nodes

## Key Concepts

- **BacktestEngine** (25 connections) — `core/engine/backtest_engine.py`
- **.run()** (11 connections) — `core/engine/backtest_engine.py`
- **._load_backtest_ohlc()** (7 connections) — `core/engine/backtest_engine.py`
- **DataFrame** (7 connections)
- **._run_risk_and_rollover()** (6 connections) — `core/engine/backtest_engine.py`
- **.build_context()** (5 connections) — `core/engine/backtest_engine.py`
- **._merge_backtest_ohlc()** (5 connections) — `core/engine/backtest_engine.py`
- **._backtest_price_map()** (4 connections) — `core/engine/backtest_engine.py`
- **._drop_delta_ist_wall_clock_as_utc_api_bars()** (4 connections) — `core/engine/backtest_engine.py`
- **._overlay_stored_indicators()** (4 connections) — `core/engine/backtest_engine.py`
- **._run_entry()** (4 connections) — `core/engine/backtest_engine.py`
- **_position_allows_strategy_exit()** (4 connections) — `core/engine/backtest_engine.py`
- **Any** (4 connections)
- **._filter_df_calendar_range()** (3 connections) — `core/engine/backtest_engine.py`
- **._hist_covers_calendar_range()** (3 connections) — `core/engine/backtest_engine.py`
- **.__init__()** (3 connections) — `core/engine/backtest_engine.py`
- **._on_pm_main_exit_fill()** (3 connections) — `core/engine/backtest_engine.py`
- **._persisted_indicator_keys()** (3 connections) — `core/engine/backtest_engine.py`
- **._rows_to_ohlc_df()** (3 connections) — `core/engine/backtest_engine.py`
- **._on_pm_main_entry_fill()** (2 connections) — `core/engine/backtest_engine.py`
- **.update_risk_metrics()** (2 connections) — `core/engine/backtest_engine.py`
- **Prefer indicator_history.jsonl values over recomputed columns.** (1 connections) — `core/engine/backtest_engine.py`
- **Drop API rows whose UTC label is IST wall-clock when history has the real UTC…** (1 connections) — `core/engine/backtest_engine.py`
- **Merge OHLC; when ``prefer_hist``, indicator history wins on duplicate buckets.** (1 connections) — `core/engine/backtest_engine.py`
- **Prefer shared indicator history (live bootstrap file), then API.** (1 connections) — `core/engine/backtest_engine.py`
- *... and 2 more nodes in this community*

## Relationships

- [factory.py](factory.py.md) (7 shared connections)
- [.create_live_engine](create_live_engine.md) (3 shared connections)
- [Component Details](Component_Details.md) (2 shared connections)
- [Algo - Multi-Venue Trading System](Algo_-_Multi-Venue_Trading_System.md) (1 shared connections)
- [Live Engine](Live_Engine.md) (1 shared connections)

## Source Files

- `core/engine/backtest_engine.py`

## Audit Trail

- EXTRACTED: 60 (91%)
- INFERRED: 6 (9%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*