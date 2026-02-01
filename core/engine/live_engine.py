import time
import datetime as dt
import pdb
from core.engine.base_engine import BaseEngine


class LiveEngine(BaseEngine):

    def __init__(
        self,
        broker,
        strategy,
        data,
        candle_service,
        symbols,
        order_router,
        instrument_store,
    ):
        super().__init__(strategy, data, instrument_store)
        self.broker = broker
        self.symbols = symbols
        self.candle_service = candle_service
        self.order_router = order_router

    def start(self, exchange, sector, rsi):
        print("🚀 Live Engine Started")
        tf = getattr(self.strategy, "timeframe", None)

        while True:
            # -------- TIMEFRAME MODE --------
            if tf:
                for symbol in self.symbols:

                    # candle = self.candle_service.get_latest_closed(
                    #     symbol, tf, exchange, sector, rsi
                    # )
                    candle = {
                        "open": 25346,
                        "close": 25342.75,
                        "high": 25359.35,
                        "low": 25159.8,
                        "volume": 63503115.0,
                        "timestamp": "2026-02-01 13:15:00+05:30",
                        "time": "13:15",
                        "rsi": 54,
                    }
                    if candle is None:
                        continue

                    candle["symbol"] = symbol
                    candle["exchange"] = exchange

                    if not self.strategy.should_evaluate(candle):
                        continue

                    ctx = self.build_context(candle)
                    # pdb.set_trace()
                    self._run_strategy(symbol, candle, ctx)

            # -------- TICK MODE --------
            else:
                candles = self.data.get_latest_candles(self.symbols)

                if not candles:
                    time.sleep(1)
                    continue

                for symbol, candle in candles.items():

                    candle["timestamp"] = dt.datetime.now()
                    candle["symbol"] = symbol
                    candle["exchange"] = exchange

                    ctx = self.build_context(candle)

                    self._run_strategy(symbol, candle, ctx)

            time.sleep(1)

    def _run_strategy(self, symbol, candle, ctx):
        # ---------- EXIT ----------
        # for position in self.broker.get_positions(symbol):
        #     exit_signal = self.strategy.should_exit(position, candle, ctx)
        #     if exit_signal:
        #         intent = self.strategy.create_exit_intent(position, exit_signal)
        #         # process via router
        #         price_map = self.get_price_map(symbol)  # fetch current market prices
        #         self.order_router.process_intent(intent, price_map)

        # ---------- ENTRY ----------
        intent = self.strategy.on_candle(candle, ctx)

        if intent:
            # pdb.set_trace()
            price_map = candle["close"]
            self.order_router.process_intent(intent, price_map)
