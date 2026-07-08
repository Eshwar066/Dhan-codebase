# Real-time WebSocket feeds

Used by **LiveEngine** for real-time market data (and optional account updates) instead of REST polling.

## Implementations

- **DeltaWebSocketFeed** – Delta Exchange WebSocket (production: `wss://socket.india.delta.exchange`; India testnet: `wss://cdn-ind.testnet.deltaex.org`).  
  Subscribes to `v2/ticker`, `candlestick_*`, `l2_orderbook`, and optionally private channels: `orders`, `positions`.  
  **Feed stall:** If no ticks are received for the configured period (e.g. 10s), the client calls an optional `on_feed_stall` callback. When the feed is built with `engine_logger` and/or `telegram_alert` (EngineFactory), stall is logged via `engine_logger.feed_health_warning()` and an optional Telegram alert is sent.

- **DhanWebSocketFeed** – Dhan Live Market Feed WebSocket (`wss://api-feed.dhan.co`). Subscribes by ExchangeSegment + SecurityId (from `instrument_store.get_feed_instruments(symbols)`). Binary packets: Ticker, Quote, Full, OI, Prev close. Instantiated in `EngineFactory.create_live_engine()` when broker is DHAN and credentials are set.

- **DhanDepthFeed** – Optional depth channel used by `live_engine_common` for best bid/ask when placing or refreshing orders.

## Interface: `RealtimeFeed`

- `start()` / `stop()` – connect/disconnect
- `is_connected()` – True if feed is connected
- `get_last_ticker(symbol)` – last LTP/ticker
- `get_last_candle(symbol, resolution)` – last candle (open, high, low, close, volume, timestamp)
- `get_orders(symbol)` / `get_positions()` – optional, for private feeds

LiveEngine uses the feed when `realtime_feed` is set and `is_connected()`; otherwise it falls back to `CandleService` / `data.get_latest_candles()`.

## Quote subscription (HYBRID_GTT)

`GttFallbackBook` registers option symbols via `LiveEngine._gtt_fallback_subscribe` → `replace_instruments` on the Dhan feed. Scheduled strategies still subscribe **underlying** index symbols for spot at eval slots.

## Smoke test

```bash
cd /root/Dhan-codebase
source .venv/bin/activate
python -c "from core.data.feeds import DeltaWebSocketFeed; print('OK', DeltaWebSocketFeed)"
```

## Operational notes

- Main live loop uses `sleep(1)`; quote-driven strategies (HYBRID_GTT) poll inside `GttFallbackBook.tick()` — see `docs/EVENT_DRIVEN_STRATEGY_GUIDE.md` for push-based quote events (roadmap).
- Candle dedup: engine tracks last processed bar keys per strategy/symbol where applicable.
- Feed reconnect behavior is implementation-specific; monitor `feed_health_warning` in engine logs.
- On restart, broker position reconcile runs at engine startup (`OrderRouter` / `PositionManager`).
