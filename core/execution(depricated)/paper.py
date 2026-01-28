engine = BacktestEngine(
    data_provider=LiveMarketFeed(),
    portfolio=Portfolio(100000),
    instrument=OptionInstrument(),
    strategy=ShortStrangleStrategy(),
)
engine.run_realtime()
