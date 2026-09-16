# .start

> 5 nodes

## Key Concepts

- **.start()** (7 connections) — `core/data/feeds/delta_feed.py`
- **_on_feed_recovered()** (1 connections) — `core/data/feeds/delta_feed.py`
- **_on_feed_stall()** (1 connections) — `core/data/feeds/delta_feed.py`
- **_on_subscriptions()** (1 connections) — `core/data/feeds/delta_feed.py`
- **_on_unavailable()** (1 connections) — `core/data/feeds/delta_feed.py`

## Relationships

- [DeltaWebSocketFeed](DeltaWebSocketFeed.md) (2 shared connections)
- [DeltaWebSocket](DeltaWebSocket.md) (1 shared connections)

## Source Files

- `core/data/feeds/delta_feed.py`

## Audit Trail

- EXTRACTED: 5 (71%)
- INFERRED: 2 (29%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*