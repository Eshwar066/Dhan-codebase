main.py
 └── run_job()
      └── BacktestEngine.run()
            ├── load historical data
            ├── for each candle:
            │     └── strategy.on_candle()
            ├── place virtual orders
            └── update portfolio


