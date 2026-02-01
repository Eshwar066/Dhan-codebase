# Inside Bar Candle Strategy

This strategy identifies inside bar candle patterns with RSI-based trend confirmation and breakout signals.

## Strategy Logic

1. **Inside Bar Pattern**: A candle where the high is below the previous candle's high and the low is above the previous candle's low
2. **Trend Confirmation**: Uses RSI (14 period)
   - Uptrend: RSI > 60
   - Downtrend: RSI < 40
3. **Breakout Signals**:
   - **BUY**: Uptrend + Inside Bar + Upper Breakout (current high > base high)
   - **SELL**: Downtrend + Inside Bar + Lower Breakout (current low < base low)

## Files

- `main.py`: Original strategy implementation (for reference)
- `backtest.py`: Backtest runner for historical analysis
- `paper_trade.py`: Paper trading runner for live simulation

## Running Backtest

```bash
# From project root
python Strategies/InSideBarCandle/backtest.py
```

### Backtest Features

- **Period**: Last 30 days (configurable via `BACKTEST_DAYS`)
- **Data Source**: Uses `get_intraday_data` API once per day (not repeated calls)
- **Timeframe**: 1-minute candles, processed for full trading day
- **Logging**: 
  - All entry/exit signals logged to file and console
  - Trades exported to CSV
  - Performance metrics calculated

### Backtest Output

- Log file: `Dependencies/backtest_logs/inside_bar_backtest_YYYYMMDD_HHMMSS.log`
- Trades CSV: `Dependencies/backtest_logs/inside_bar_trades_YYYYMMDD_HHMMSS.csv`
- Console output with:
  - Total trades
  - Win rate
  - Total PnL
  - Return percentage

## Running Paper Trading

```bash
# From project root
python Strategies/InSideBarCandle/paper_trade.py
```

### Paper Trading Features

- **Real-time**: Monitors market during trading hours (9:20 AM - 2:30 PM)
- **Simulated Orders**: Uses `PaperBroker` for order simulation
- **Logging**: All trades logged with entry/exit details
- **Position Management**: 
  - Max 2 trades per day (configurable)
  - Auto-exit at end of day

### Paper Trading Output

- Log file: `Dependencies/paper_trade_logs/inside_bar_paper_YYYYMMDD_HHMMSS.log`
- Console output with real-time trade signals

## Configuration

Edit the configuration variables at the top of each file:

### Backtest (`backtest.py`)
```python
BACKTEST_DAYS = 30  # Number of days to backtest
MAX_TRADES_PER_DAY = 2  # Maximum trades per day
RSI_PERIOD = 14  # RSI period
INITIAL_CAPITAL = 100000  # Starting capital
```

### Paper Trading (`paper_trade.py`)
```python
MAX_TRADES = 2  # Maximum concurrent trades
RSI_PERIOD = 14  # RSI period
INITIAL_CAPITAL = 100000  # Paper trading capital
```

## Environment Variables

Make sure you have `.env` file in project root with:
```
DHAN_CLIENT_CODE=your_client_code
DHAN_ACCESS_TOKEN=your_access_token
```

## Notes

- The strategy uses 1-minute intraday data
- Market hours: 9:20 AM to 2:30 PM IST
- Strategy requires at least 20 candles of data
- Positions are closed at end of day (2:30 PM)
- Uses `get_intraday_data` API efficiently (one call per stock per day)
