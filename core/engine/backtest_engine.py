import pandas as pd
from core.engine.base_engine import BaseEngine
import pdb


class BacktestEngine(BaseEngine):
    def __init__(self, data_provider, strategy):
        super().__init__(strategy=strategy, data=data_provider)
        # self.portfolio = portfolio

    def run(self, symbols, start_date, end_date, timeframe, exchange, sector):
        for symbol in symbols:
            # ---- Fetch full data once ----
            df = self.data.get_intraday(
                symbol=symbol,
                start_date=start_date,
                end_date=end_date,
                timeframe=timeframe,
                exchange=exchange,
                sector=sector,
            )

            if df is None or len(df) < 20:
                continue

            df["symbol"] = symbol

            # ---- Indicators ----
            df = self.strategy.prepare_indicators(df)
            # pdb.set_trace()
            # ---- Iterate candle by candle ----
            for idx in range(len(df)):
                candle = df.iloc[idx].to_dict()

                # Skip weekends (extra safety)
                ts = pd.to_datetime(candle["timestamp"])
                if ts.weekday() >= 5:
                    continue

                # ---- Build runtime context ----
                ctx = self.build_context(candle)

                # ========== EXIT ==========
                if self.portfolio.has_position(symbol):
                    position = self.portfolio.get_position(symbol)

                    if self.strategy.should_exit(position, candle, ctx):
                        self.portfolio.exit(position, candle)
                        continue

                # ========== ENTRY ==========
                if not self.portfolio.has_position(symbol):
                    position = self.strategy.on_candle(
                        candle=candle,
                        ctx=ctx,
                        portfolio=self.portfolio,
                    )

                    if position:
                        self.portfolio.enter(position)

        self.portfolio.report()

    def update_risk_metrics(self, symbol, ltp):
        pos = self.position_manager.positions.get(symbol)
        if not pos or pos.net_qty == 0:
            return

        diff = ltp - pos.entry_price

        if pos.net_qty < 0:
            diff *= -1

        pos.mfe = max(pos.mfe, diff)
        pos.mae = min(pos.mae, diff)
