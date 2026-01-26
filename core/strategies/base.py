class Strategy:
    def prepare_indicators(self, df):
        return df

    def on_candle(self, idx, df, portfolio):
        return None

    def should_exit(self, position, candle):
        return False
