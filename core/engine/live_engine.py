import time
import datetime as dt
from core.engine.base_engine import BaseEngine


class LiveEngine(BaseEngine):
    """
    Live/paper engine. Optional realtime_feed (WebSocket) supplies real-time
    candles/ticker; when not provided or not connected, falls back to
    candle_service / data.get_latest_candles (REST polling).
    """

    def __init__(
        self,
        strategy,
        data,
        candle_service,
        symbols,
        order_router,
        instrument_store,
        position_manager,
        realtime_feed=None,
    ):
        super().__init__(strategy, data, instrument_store, position_manager)
        self.symbols = symbols
        self.candle_service = candle_service
        self.order_router = order_router
        self.position_manager = position_manager
        self.realtime_feed = realtime_feed

    def start(self, exchange, sector, rsi):
        print("🚀 Live Engine Started")
        tf = getattr(self.strategy, "timeframe", None)
        use_feed = self.realtime_feed and self.realtime_feed.is_connected()

        while True:
            # -------- TIMEFRAME MODE --------
            if tf:
                for symbol in self.symbols:
                    candle = None
                    if use_feed:
                        candle = self.realtime_feed.get_last_candle(symbol, tf)
                    if candle is None and self.candle_service:
                        candle = self.candle_service.get_latest_closed(
                            symbol, tf, exchange, sector, rsi
                        )
                    if candle is None:
                        continue

                    if isinstance(candle.get("timestamp"), (int, float)):
                        ts = candle["timestamp"]
                        if ts > 1e12:
                            candle["timestamp"] = dt.datetime.utcfromtimestamp(ts / 1e6)
                        else:
                            candle["timestamp"] = dt.datetime.utcfromtimestamp(ts)
                    candle["symbol"] = symbol
                    candle["exchange"] = exchange
                    print(candle)

                    if not self.strategy.should_evaluate(candle):
                        continue
                    ctx, intent = self.build_context(candle)
                    self._run_strategy(symbol, candle, ctx, intent)

            # -------- TICK MODE --------
            else:
                candles = None
                if use_feed:
                    candles = {}
                    for symbol in self.symbols:
                        ticker = self.realtime_feed.get_last_ticker(symbol)
                        if ticker:
                            candles[symbol] = {
                                "open": ticker.get("close"),
                                "high": ticker.get("high") or ticker.get("close"),
                                "low": ticker.get("low") or ticker.get("close"),
                                "close": ticker.get("close"),
                                "volume": ticker.get("volume", 0),
                                "symbol": symbol,
                            }
                if not candles and self.data:
                    candles = self.data.get_latest_candles(self.symbols)

                if not candles:
                    time.sleep(1)
                    continue

                for symbol, candle in candles.items():
                    candle["timestamp"] = dt.datetime.now()
                    candle["symbol"] = symbol
                    candle["exchange"] = exchange
                    ctx, intent = self.build_context(candle)
                    self._run_strategy(symbol, candle, ctx, intent)

            use_feed = self.realtime_feed and self.realtime_feed.is_connected()
            time.sleep(1)

    def get_price_map(self, symbol):
        """Current price for symbol (for order execution). From feed ticker or REST."""
        if self.realtime_feed and self.realtime_feed.is_connected():
            ticker = self.realtime_feed.get_last_ticker(symbol)
            if ticker and ticker.get("close") is not None:
                return ticker["close"]
        if self.data:
            candles = self.data.get_latest_candles([symbol])
            if (
                candles
                and symbol in candles
                and candles[symbol].get("close") is not None
            ):
                return candles[symbol]["close"]
        return None

    def _run_strategy(self, symbol, candle, ctx, intent):
        # ---------- EXIT ----------
        open_positions = self.position_manager.get_open_positions(
            symbol=symbol, strategy=self.strategy.name
        )

        for position in open_positions:
            exit_signal = self.strategy.should_exit(position, candle, ctx)

            if exit_signal:
                intent = self.strategy.create_exit_intent(position, exit_signal)
                price_map = self.get_price_map(symbol)
                if price_map is not None:
                    self.order_router.process_intent(intent, price_map)

        # ---------- ENTRY ----------
        # intent = self.strategy.on_candle(candle, ctx)

        if intent:
            price_map = candle.get("close")
            if price_map is not None:
                self.order_router.process_intent(intent, price_map)

    def update_risk_metrics(self, symbol, ltp):
        pos = self.position_manager.positions.get(symbol)
        if not pos or pos.net_qty == 0:
            return
        diff = ltp - pos.entry_price
        if pos.net_qty < 0:
            diff *= -1
        pos.mfe = max(pos.mfe, diff)
        pos.mae = min(pos.mae, diff)
