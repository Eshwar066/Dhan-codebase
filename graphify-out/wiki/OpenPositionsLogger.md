# OpenPositionsLogger

> 22 nodes

## Key Concepts

- **OpenPositionsLogger** (17 connections) — `utils/logger/open_positions_logger.py`
- **.record_broker_reconcile_snapshot()** (10 connections) — `utils/logger/open_positions_logger.py`
- **Any** (8 connections)
- **._read_open_snapshot()** (7 connections) — `utils/logger/open_positions_logger.py`
- **._compact_legacy_to_snapshot()** (6 connections) — `utils/logger/open_positions_logger.py`
- **._finalize_row_for_csv()** (6 connections) — `utils/logger/open_positions_logger.py`
- **._format_timestamp()** (6 connections) — `utils/logger/open_positions_logger.py`
- **.record_fill()** (6 connections) — `utils/logger/open_positions_logger.py`
- **._write_snapshot()** (5 connections) — `utils/logger/open_positions_logger.py`
- **.__init__()** (4 connections) — `utils/logger/open_positions_logger.py`
- **._now()** (4 connections) — `utils/logger/open_positions_logger.py`
- **._path_for_strategy()** (4 connections) — `utils/logger/open_positions_logger.py`
- **._ensure_csv_schema()** (3 connections) — `utils/logger/open_positions_logger.py`
- **._safe_strategy_name()** (2 connections) — `utils/logger/open_positions_logger.py`
- **_has_ownership()** (1 connections) — `utils/logger/open_positions_logger.py`
- **_merge_ownership()** (1 connections) — `utils/logger/open_positions_logger.py`
- **- Fills (paper + live): updates that symbol's row when qty changes; removes the…** (1 connections) — `utils/logger/open_positions_logger.py`
- **On startup, collapse older append-only logs to one row per still-open symbol.** (1 connections) — `utils/logger/open_positions_logger.py`
- **One-time migrate older CSVs when new columns are introduced (rewrite in place).** (1 connections) — `utils/logger/open_positions_logger.py`
- **IST date + time only, e.g. 2026-05-22 22:48:23 (no timezone / microseconds).** (1 connections) — `utils/logger/open_positions_logger.py`
- **Last row wins per symbol; keep only symbols that are still open (net_qty != 0…** (1 connections) — `utils/logger/open_positions_logger.py`
- **Live: rewrite open-positions CSV from PM after broker sync. Ownership fields…** (1 connections) — `utils/logger/open_positions_logger.py`

## Relationships

- [factory.py](factory.py.md) (5 shared connections)
- [.create_live_engine](create_live_engine.md) (2 shared connections)
- [.reconcile_with_broker](reconcile_with_broker.md) (1 shared connections)

## Source Files

- `utils/logger/open_positions_logger.py`

## Audit Trail

- EXTRACTED: 51 (98%)
- INFERRED: 1 (2%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*