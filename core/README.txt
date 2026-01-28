algo_trading/
│
├── core/
│   │
│   ├── execution/
│   │   ├── backtest.py          # BacktestEngine
│   │   └── live.py              # LiveEngine
│   │
│   ├── strategies/
│   │   ├── leaps_quarterly.py   # Your RSI 52/32 logic
│   │   ├── live_adapter.py      # Converts live → df
│   │   └── base.py              # Optional BaseStrategy
│   │
│   ├── data/
│   │   ├── historical_data.py   # CSV / DB / API
│   │   └── live_data.py         # Tradehull live fetch
│   │
│   ├── broker/
│   │   ├── dhan.py              # Real broker
│   │   └── paper.py             # Paper broker (optional)
│   │
│   ├── portfolio/
│   │   ├── backtest_portfolio.py
│   │   └── live_portfolio.py
│   │
│   ├── risk/
│   │   └── manager.py           # RiskManager
│   │
│   ├── utils/
│   │   ├── expiry_calendar.py
│   │   ├── time_utils.py
│   │   └── logger.py
│   │
│   └── models/
│       └── position.py          # Position dataclass
│
├── configs/
│   ├── live.yaml
│   ├── backtest.yaml
│   └── symbols.yaml
│
├── scripts/
│   ├── run_backtest.py
│   └── run_live.py
│
├── logs/
│   └── trades.log
│
├── requirements.txt
└── README.md


algo_trading/
│
├── core/
│   ├── execution/
│   │   ├── backtest.py
│   │   ├── live.py
│   │   └── runner.py
│   │
│   ├── strategies/
│   │   ├── momentum/
│   │   ├── options/
│   │   ├── volatility/
│   │   ├── factory.py
│   │   └── base.py
│   │
│   ├── data/
│   ├── broker/
│   ├── portfolio/
│   ├── risk/
│   ├── utils/
│   └── models/
│
├── configs/
│   ├── strategies/
│   │   ├── rsi_quarterly.yaml
│   │   ├── strangle.yaml
│   │   └── ironfly.yaml
│   ├── live.yaml
│   └── backtest.yaml
│
├── scripts/
│   ├── run_live.py
│   └── run_backtest.py
│
└── logs/

strategies/
├── __init__.py
├── base.py
├── live_adapter.py
├── adapters/
│   ├── __init__.py
│   ├── multi_symbol.py
│   ├── tick_adapter.py
│   └── options_adapter.py
├── momentum/
│   ├── __init__.py
│   ├── rsi_breakout.py
│   └── macd_trend.py
├── options/
│   ├── __init__.py
│   ├── leaps_quarterly.py
│   └── short_strangle.py

data/
├── historical/        # Expired and past data
├── live/              # Live feed from APIs
├── instruments/       # Metadata about symbols, strikes, expiries
├── processed/         # Preprocessed / merged data for strategies
├── logs/              # Data fetching or API errors
└── config/            # API configs, holidays, symbols


data/
├── historical/                 # Historical OHLC, indicators, options chains
│   ├── nifty/                  # Nifty index data
│   │   ├── 1min/               # 1-min candles
│   │   ├── 5min/
│   │   ├── 15min/
│   │   └── 1hr/
│   ├── stocks/                 # Individual stock historical data
│   │   ├── AAPL.csv
│   │   └── ACC.csv
│   └── options/                # Option chain history
│       ├── NIFTY_2026-01-31_CE.csv
│       └── NIFTY_2026-01-31_PE.csv
│
├── live/                       # Temporary live feeds saved (optional)
│   ├── tick_data/              # Raw tick data from adapter
│   └── order_book/             # Market depth snapshots
│
├── instruments/                # Metadata for symbols, option series, contracts
│   ├── nifty_symbols.csv
│   ├── stock_symbols.csv
│   └── options_metadata.csv    # expiry dates, strike list, lot sizes
│
├── processed/                  # Cleaned / resampled / merged data for strategies
│   ├── indicators/             # OHLC + calculated indicators (RSI, MACD)
│   └── signals/                # Strategy signals (for backtesting)
│
├── logs/                       # Strategy & trade logs
│   ├── trades/                 # Filled / rejected orders
│   ├── strategy/               # Backtesting logs
│   └── errors/                 # Errors & exceptions
│
└── config/                     # Configs for data paths, instruments, market holidays
    └── holidays.json


