# Real-time WebSocket feeds

Used by **LiveEngine** for real-time market data (and optional account updates) instead of REST polling.

## Implementations

- **DeltaWebSocketFeed** – Delta Exchange WebSocket (production: `wss://socket.india.delta.exchange`; India testnet: `wss://cdn-ind.testnet.deltaex.org`).  
  Subscribes to `v2/ticker`, `candlestick_*`, `l2_orderbook`, and optionally private channels: `orders`, `positions`.  
  **Feed stall:** If no ticks are received for the configured period (e.g. 10s), the client calls an optional `on_feed_stall` callback. When the feed is built with `engine_logger` and/or `telegram_alert` (EngineFactory), stall is logged via `engine_logger.feed_health_warning()` and an optional Telegram alert is sent.

- **DhanWebSocketFeed** – Dhan Live Market Feed WebSocket (`wss://api-feed.dhan.co`). Subscribes by ExchangeSegment + SecurityId (from `instrument_store.get_feed_instruments(symbols)`). Binary packets: Ticker, Quote, Full, OI, Prev close. Instantiated in `EngineFactory.create_live_engine()` when broker is DHAN and credentials are set.

## Interface: `RealtimeFeed`

- `start()` / `stop()` – connect/disconnect
- `is_connected()` – True if feed is connected
- `get_last_ticker(symbol)` – last LTP/ticker
- `get_last_candle(symbol, resolution)` – last candle (open, high, low, close, volume, timestamp)
- `get_orders(symbol)` / `get_positions()` – optional, for private feeds

LiveEngine uses the feed when `realtime_feed` is set and `is_connected()`; otherwise it falls back to `CandleService` / `data.get_latest_candles()`.



cd /d "c:\Users\eshwa\Desktop\Dhan\Algo" && python -c "
from core.data.feeds import RealtimeFeed, DeltaWebSocketFeed
from core.library.delta_websocket import DeltaWebSocket
print('DeltaWebSocketFeed', DeltaWebSocketFeed)
print('DeltaWebSocket', DeltaWebSocket)
print('OK')
"

cd "c:\Users\eshwa\Desktop\Dhan\Algo"; python -c "from core.data.feeds import RealtimeFeed, DeltaWebSocketFeed; from core.library.delta_websocket import DeltaWebSocket; print('OK')"


<!-- Next plans -->
⚠ Architectural Weaknesses
1️⃣ while True + sleep(1) is blocking

This limits:

Scalability

Latency

Multi-symbol expansion

Async would be better.

2️⃣ No duplicate candle guard

If feed returns same closed candle twice,
strategy may trigger twice.

You should store last processed timestamp per symbol.

3️⃣ No reconnection logic shown

If feed disconnects mid-loop,
behavior depends on is_connected().

Better to auto-reconnect.

4️⃣ No position sync on restart

If engine restarts,
does it reload open positions?

Important for live trading.