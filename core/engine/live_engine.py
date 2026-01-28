import time
import datetime as dt
from core.engine.base_engine import BaseEngine


class LiveEngine(BaseEngine):
    def __init__(self, broker, strategy, risk_manager, data):
        super().__init__(strategy=strategy, data=data)
        self.broker = broker
        self.risk_manager = risk_manager

    def start(self):
        print("🚀 Live Engine Started")

        while True:
            # -------- Market hours guard --------
            now = dt.datetime.now()
            if now.hour < 9 or now.hour > 15:
                time.sleep(30)
                continue

            # -------- Get latest candle --------
            candle = self.data.get_latest_candle()

            if candle is None:
                time.sleep(1)
                continue

            # -------- Build runtime context --------
            ctx = self.build_context(candle)

            symbol = candle["symbol"]

            # ========== EXIT ==========
            for position in self.broker.get_positions(symbol=symbol):
                if self.strategy.should_exit(position, candle, ctx):
                    self.broker.exit_position(position)

            # ========== ENTRY ==========
            position = self.strategy.on_candle(
                candle=candle,
                ctx=ctx,
                portfolio=self.broker.portfolio,  # live portfolio
            )

            if position:
                if self.risk_manager.allow_trade(position):
                    self.broker.place_order(position)

            time.sleep(1)
