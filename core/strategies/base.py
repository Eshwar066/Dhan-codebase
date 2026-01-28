class BaseStrategy:
    name = ""
    required_context = []

    def prepare_indicators(self, df):
        return df

    def on_candle(self, candle, ctx):
        raise NotImplementedError

    def should_exit(self, position, candle, ctx=None):
        return False
