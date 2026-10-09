# StallWatchdog

> 13 nodes

## Key Concepts

- **StallWatchdog** (16 connections) — `core/library/dhan_ws_common.py`
- **DhanFeedSupervisor** (4 connections) — `core/library/dhan_ws_common.py`
- **.__init__()** (2 connections) — `core/library/dhan_ws_common.py`
- **.log_snapshot()** (2 connections) — `core/library/dhan_ws_common.py`
- **.__init__()** (2 connections) — `core/library/dhan_ws_common.py`
- **Any** (2 connections)
- **_add()** (1 connections) — `core/library/dhan_ws_common.py`
- **.enabled()** (1 connections) — `core/library/dhan_ws_common.py`
- **._loop()** (1 connections) — `core/library/dhan_ws_common.py`
- **.start()** (1 connections) — `core/library/dhan_ws_common.py`
- **.stop()** (1 connections) — `core/library/dhan_ws_common.py`
- **Background thread: if connected but no application traffic for stall_sec, close…** (1 connections) — `core/library/dhan_ws_common.py`
- **Optional control-plane helper: hold references to Dhan market / order / depth…** (1 connections) — `core/library/dhan_ws_common.py`

## Relationships

- [logging.py](logging.py.md) (5 shared connections)
- [.__init__](__init__.md) (2 shared connections)
- [DhanOrderUpdateClient](DhanOrderUpdateClient.md) (2 shared connections)
- [DhanDepthWebSocket](DhanDepthWebSocket.md) (1 shared connections)
- [DhanWebSocket](DhanWebSocket.md) (1 shared connections)

## Source Files

- `core/library/dhan_ws_common.py`

## Audit Trail

- EXTRACTED: 20 (87%)
- INFERRED: 3 (13%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*