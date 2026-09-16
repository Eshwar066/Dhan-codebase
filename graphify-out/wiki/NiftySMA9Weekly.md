# NiftySMA9Weekly

> 75 nodes

## Key Concepts

- **NiftySMA9Weekly** (40 connections) — `core/strategies/IBBM/SMA9Weekly/NiftySMA9Weekly.py`
- **SessionManager** (36 connections) — `core/utils/session/session_manager.py`
- **CandleService** (13 connections) — `core/data/candle_service.py`
- **.hedge_rollover_target_date()** (10 connections) — `core/utils/session/session_manager.py`
- **._resolve_main_expiry()** (9 connections) — `core/strategies/IBBM/SMA9Weekly/NiftySMA9Weekly.py`
- **.is_holiday()** (9 connections) — `core/utils/session/session_manager.py`
- **._build_entry_intents()** (8 connections) — `core/strategies/IBBM/SMA9Weekly/NiftySMA9Weekly.py`
- **.is_market_open()** (8 connections) — `core/utils/session/session_manager.py`
- **.normalize_exchange()** (8 connections) — `core/utils/session/session_manager.py`
- **test_hedge_rollover_calendar.py** (8 connections) — `tests/test_hedge_rollover_calendar.py`
- **.get_latest_closed()** (7 connections) — `core/data/candle_service.py`
- **_is_exchange_open()** (7 connections) — `core/library/dhan_ws_common.py`
- **.is_trading_day()** (7 connections) — `core/utils/session/session_manager.py`
- **date** (7 connections)
- **.fetch_hedge_option_chain()** (6 connections) — `core/strategies/IBBM/SMA9Weekly/NiftySMA9Weekly.py`
- **.should_evaluate()** (6 connections) — `core/strategies/IBBM/SMA9Weekly/NiftySMA9Weekly.py`
- **._trade_date()** (6 connections) — `core/strategies/IBBM/SMA9Weekly/NiftySMA9Weekly.py`
- **._now()** (6 connections) — `core/utils/session/session_manager.py`
- **.session_end_unix_for_bar()** (6 connections) — `core/utils/session/session_manager.py`
- **_dhan_market_stall_should_close()** (5 connections) — `core/library/dhan_websocket.py`
- **_is_dhan_holiday()** (5 connections) — `core/library/dhan_ws_common.py`
- **_is_dhan_trading_day()** (5 connections) — `core/library/dhan_ws_common.py`
- **._accept_otm_premium_strike()** (5 connections) — `core/strategies/IBBM/SMA9Weekly/NiftySMA9Weekly.py`
- **._is_event_no_trade_day()** (5 connections) — `core/strategies/IBBM/SMA9Weekly/NiftySMA9Weekly.py`
- **._is_weekly_expiry_day()** (5 connections) — `core/strategies/IBBM/SMA9Weekly/NiftySMA9Weekly.py`
- *... and 50 more nodes in this community*

## Relationships

- [typing](typing.md) (15 shared connections)
- [logging.py](logging.py.md) (11 shared connections)
- [main](main.md) (6 shared connections)
- [indicator_history.py](indicator_history.py.md) (4 shared connections)
- [IndiaMktMixins](IndiaMktMixins.md) (3 shared connections)
- [.create_live_engine](create_live_engine.md) (2 shared connections)
- [factory.py](factory.py.md) (2 shared connections)
- [NiftyDOS](NiftyDOS.md) (2 shared connections)
- [.as_calendar_date](as_calendar_date.md) (2 shared connections)
- [._run_watches](_run_watches.md) (1 shared connections)
- [EngineConfig](EngineConfig.md) (1 shared connections)
- [DeltaDataProvider](DeltaDataProvider.md) (1 shared connections)

## Source Files

- `core/data/candle_service.py`
- `core/library/dhan_websocket.py`
- `core/library/dhan_ws_common.py`
- `core/strategies/IBBM/SMA9Weekly/NiftySMA9Weekly.py`
- `core/strategies/IBBM/SMA9Weekly/__init__.py`
- `core/utils/session/session_manager.py`
- `tests/test_hedge_rollover_calendar.py`

## Audit Trail

- EXTRACTED: 183 (89%)
- INFERRED: 23 (11%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*