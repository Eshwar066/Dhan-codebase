import pandas as pd
import datetime as dt


class BacktestEngine:
    def __init__(self, data_provider, portfolio, instrument, strategy):
        self.data = data_provider
        self.portfolio = portfolio
        self.instrument = instrument
        self.strategy = strategy

    def run(self, symbols, start_date, end_date):
        for date in pd.date_range(start_date, end_date):
            if date.weekday() >= 5:  # skip weekends
                continue

            for symbol in symbols:
                df = self.data.get_intraday(symbol, date)

                if df is None or len(df) < 20:
                    continue

                df["symbol"] = symbol
                df = self.strategy.prepare_indicators(df)

                for idx in range(len(df)):
                    candle = df.iloc[idx]

                    # ---- EXIT LOGIC ----
                    if self.portfolio.has_position(symbol):
                        pos = self.portfolio.get_position(symbol)

                        if self.strategy.should_exit(pos, candle):
                            self.portfolio.exit(symbol, candle)
                            break  # one trade per day per symbol

                    # ---- ENTRY LOGIC ----
                    if not self.portfolio.has_position(symbol):
                        position = self.strategy.on_candle(idx, df, self.portfolio)

                        if position:
                            self.portfolio.enter(position)
                            break  # one trade per day per symbol

        self.portfolio.report()
