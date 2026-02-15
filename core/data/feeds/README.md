# Real-time WebSocket feeds

Used by **LiveEngine** for real-time market data (and optional account updates) instead of REST polling.

## Implementations

- **DeltaWebSocketFeed** – Delta Exchange WebSocket (`wss://socket.india.delta.exchange` or testnet).  
  Subscribes to `v2/ticker`, `candlestick_*`, and optionally private channels: `orders`, `positions`.

- **DhanWebSocketFeed** (TODO) – When Dhan WebSocket API is available, implement `RealtimeFeed` in a new module and instantiate it in `run/main.py` for `BROKER_NAME == "DHAN"` (see the `# TODO: add DhanWebSocketFeed` comment).

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
