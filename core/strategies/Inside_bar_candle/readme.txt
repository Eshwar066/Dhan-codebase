BacktestEngine
 ├── fetch intraday data
 ├── strategy.prepare_indicators(df)
 ├── for each candle idx:
 │     ├── strategy.on_candle(...)
 │     │     └── returns Position or None
 │     ├── if position exists:
 │     │     └── strategy.should_exit(...)
 │     └── portfolio updates
