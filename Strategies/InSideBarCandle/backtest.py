"""
Backtest runner for Inside Bar Candle Strategy.
Runs backtest for last 1 month with full day intraday data.
Uses get_intraday_data API once per day instead of calling repeatedly.
"""

import os
import sys
import datetime as dt
import pandas as pd
import talib
from dotenv import load_dotenv
import logging
import pdb

# ---- Project root fix ----
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

# from core.api.dhan_data import DhanDataProvider
from Dhan_Tradehull import Tradehull

# ================= CONFIG =================

BACKTEST_DAYS = 365  # Last 1 month
MAX_TRADES_PER_DAY = 2
RSI_PERIOD = 14
INITIAL_CAPITAL = 100000  # Starting capital for backtest

# Market hours
START_TIME = dt.time(9, 20)
END_TIME = dt.time(14, 30)

# ================= LOGIN =================
load_dotenv()
client_code = os.getenv("DHAN_CLIENT_CODE")
token_id = os.getenv("DHAN_ACCESS_TOKEN")

if not client_code or not token_id:
    raise SystemExit("[ERROR] Missing DHAN credentials")

# data_provider = DhanDataProvider(client_code, token_id)
tsl = Tradehull(client_code, token_id)

# ================= WATCHLIST =================

watchlist = [
    "HINDALCO",
    "DRREDDY",
    "TRENT",
    "JSWSTEEL",
    "TCS",
    "TATASTEEL",
    "KOTAKBANK",
    "TECHM",
    "WIPRO",
    "EICHERMOT",
    "HCLTECH",
    "ONGC",
    "JIOFIN",
    "SHRIRAMFIN",
    "NTPC",
    "BEL",
    "HINDUNILVR",
    "ETERNAL",
    "SUNPHARMA",
    "MARUTI",
    "SBIN",
    "BHARTIARTL",
    "NESTLEIND",
    "TATACONSUM",
    "INFY",
    "ITC",
    "BAJAJ-AUTO",
    "ADANIPORTS",
    "APOLLOHOSP",
    "COALINDIA",
    "AXISBANK",
    "TITAN",
    "HDFCBANK",
    "CIPLA",
    "MAXHEALTH",
    "LT",
    "ULTRACEMCO",
    "GRASIM",
    "M&M",
    "ASIANPAINT",
    "SBILIFE",
    "BAJFINANCE",
    "BAJAJFINSV",
    "POWERGRID",
    "RELIANCE",
    "TMPV",
    "ADANIENT",
    "ICICIBANK",
    "HDFCLIFE",
    "INDIGO",
]

# ================= LOGGING SETUP =================

log_dir = os.path.join(_ROOT, "Dependencies", "backtest_logs")
os.makedirs(log_dir, exist_ok=True)
log_file = os.path.join(
    log_dir, f"inside_bar_backtest_{dt.datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
)


# Unicode-safe handler for Windows console
class UnicodeSafeHandler(logging.StreamHandler):
    """Handler that safely handles Unicode characters on Windows console."""

    def emit(self, record):
        try:
            msg = self.format(record)
            # Replace emoji and Unicode characters with ASCII alternatives
            msg = msg.replace("⚠️", "[WARNING]")
            msg = msg.replace("📊", "[ENTRY]")
            msg = msg.replace("🚪", "[EXIT]")
            msg = msg.replace("❌", "[ERROR]")
            msg = msg.replace("📈", "[BUY]")
            msg = msg.replace("📉", "[SELL]")
            msg = msg.replace("✅", "[OK]")
            msg = msg.replace("₹", "Rs.")
            # Try to encode and write
            try:
                stream = self.stream
                stream.write(msg + self.terminator)
                self.flush()
            except UnicodeEncodeError:
                # If encoding fails, try with error handling
                try:
                    stream.write(
                        msg.encode("ascii", "replace").decode("ascii") + self.terminator
                    )
                    self.flush()
                except:
                    # Last resort: write ASCII-only version
                    safe_msg = msg.encode("ascii", "ignore").decode("ascii")
                    stream.write(safe_msg + self.terminator)
                    self.flush()
        except Exception:
            self.handleError(record)


# Setup logging with Unicode-safe console handler
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(log_file, encoding="utf-8"),
        UnicodeSafeHandler(sys.stdout),
    ],
    force=True,  # 🔥 THIS IS THE KEY
)
logger = logging.getLogger(__name__)

# ================= BACKTEST STATE =================


class BacktestState:
    def __init__(self, initial_capital):
        self.capital = initial_capital
        self.positions = (
            {}
        )  # {symbol: {"entry_price": float, "qty": int, "entry_time": datetime, "side": "BUY"/"SELL"}}
        self.trades = []
        self.total_trades = 0
        self.winning_trades = 0
        self.losing_trades = 0
        self.total_pnl = 0.0

    def add_trade(
        self,
        symbol,
        entry_price,
        qty,
        entry_time,
        side,
        exit_price=None,
        exit_time=None,
        pnl=None,
    ):
        trade = {
            "symbol": symbol,
            "entry_price": entry_price,
            "qty": qty,
            "entry_time": entry_time,
            "side": side,
            "exit_price": exit_price,
            "exit_time": exit_time,
            "pnl": pnl,
        }
        self.trades.append(trade)
        if pnl is not None:
            if pnl > 0:
                self.winning_trades += 1
            else:
                self.losing_trades += 1
            self.total_pnl += pnl

    def close_position(self, symbol, exit_price, exit_time):
        if symbol not in self.positions:
            return None

        pos = self.positions[symbol]
        entry_price = pos["entry_price"]
        qty = pos["qty"]
        entry_time = pos["entry_time"]
        side = pos["side"]

        # Calculate PnL
        if side == "BUY":
            pnl = (exit_price - entry_price) * qty
        else:  # SELL
            pnl = (entry_price - exit_price) * qty

        self.add_trade(
            symbol, entry_price, qty, entry_time, side, exit_price, exit_time, pnl
        )
        del self.positions[symbol]

        return pnl


# ================= STRATEGY LOGIC =================


def check_inside_bar_setup(chart, idx):
    """Check if inside bar setup exists at index idx."""
    if idx < 4 or len(chart) < idx + 1:
        return None, None

    base = chart.iloc[idx - 4]
    inside = chart.iloc[idx - 3]
    last = chart.iloc[idx - 2]
    current = chart.iloc[idx - 1]

    # Calculate RSI
    if "rsi" not in chart.columns or pd.isna(last.get("rsi")):
        return None, None

    # Inside bar condition
    inside_candle = inside["high"] < base["high"] and inside["low"] > base["low"]

    if not inside_candle:
        return None, None

    # Trend conditions
    uptrend = last["rsi"] > 60
    downtrend = last["rsi"] < 40

    # Breakout conditions
    upper_break = current["high"] > base["high"]
    lower_break = current["low"] < base["low"]

    # BUY signal
    if uptrend and upper_break:
        return "BUY", current["close"]

    # SELL signal
    if downtrend and lower_break:
        return "SELL", current["close"]

    return None, None


def should_exit_position(position, current_price, current_time):
    """Determine if position should be exited (end of day for now)."""
    # Simple exit: end of day
    if current_time.time() >= END_TIME:
        return True
    return False


# ================= MAIN BACKTEST LOOP =================


def run_backtest():
    logger.info("=" * 80)
    logger.info("INSIDE BAR CANDLE STRATEGY - BACKTEST")
    logger.info("=" * 80)
    logger.info(f"Backtest Period: Last {BACKTEST_DAYS} days")
    logger.info(f"Initial Capital: Rs.{INITIAL_CAPITAL:,.2f}")
    logger.info(f"Watchlist: {len(watchlist)} stocks")
    logger.info("=" * 80)

    state = BacktestState(INITIAL_CAPITAL)

    # Get date range
    end_date = dt.datetime.now().date()
    start_date = end_date - dt.timedelta(days=BACKTEST_DAYS)

    logger.info(f"Backtest Date Range: {start_date} to {end_date}")

    # Iterate through each day
    current_date = start_date
    while current_date <= end_date:
        # Skip weekends (Saturday=5, Sunday=6)
        if current_date.weekday() >= 5:
            current_date += dt.timedelta(days=1)
            continue

        logger.info(f"\n{'='*80}")
        logger.info(f"Processing Date: {current_date}")
        logger.info(f"{'='*80}")

        date_str = current_date.strftime("%Y-%m-%d")
        daily_trade_count = 0

        # Process each stock
        for stock in watchlist:
            print(stock)
            if daily_trade_count >= MAX_TRADES_PER_DAY:
                break

            try:
                # Get intraday data for the whole day (1-minute candles)
                logger.info(f"Fetching data for {stock} on {date_str}...")
                chart = tsl.get_intraday_data(
                    stock, "NSE", 15, from_date=date_str, to_date=date_str
                )

                if chart is None or chart.empty or len(chart) < 20:
                    logger.warning(
                        f"  [WARNING] Insufficient data for {stock} on {date_str}"
                    )
                    # pdb.set_trace()
                    continue

                # Calculate RSI
                chart["rsi"] = talib.RSI(chart["close"], RSI_PERIOD)

                # Filter data within market hours
                if "timestamp" in chart.columns:
                    chart["time"] = pd.to_datetime(chart["timestamp"]).dt.time
                elif "date" in chart.columns:
                    chart["time"] = pd.to_datetime(chart["date"]).dt.time
                elif "start_Time" in chart.columns:
                    chart["time"] = pd.to_datetime(chart["start_Time"]).dt.time
                else:
                    logger.warning(f"  [WARNING] No time column found for {stock}")
                    continue

                chart = chart[
                    (chart["time"] >= START_TIME) & (chart["time"] <= END_TIME)
                ].copy()

                if len(chart) < 20:
                    logger.warning(
                        f"  [WARNING] Insufficient data within market hours for {stock}"
                    )
                    continue

                # Reset index for easier access
                chart = chart.reset_index(drop=True)

                # Sort by time to process chronologically
                if "timestamp" in chart.columns:
                    chart = chart.sort_values("timestamp").reset_index(drop=True)
                elif "date" in chart.columns:
                    chart = chart.sort_values("date").reset_index(drop=True)
                elif "start_Time" in chart.columns:
                    chart = chart.sort_values("start_Time").reset_index(drop=True)

                # Process each candle chronologically
                entered_today = False
                for idx in range(len(chart)):
                    if idx < 4:  # Need at least 4 previous candles
                        continue

                    current_candle = chart.iloc[idx]
                    time_col = (
                        current_candle.get("timestamp")
                        or current_candle.get("date")
                        or current_candle.get("start_Time")
                    )
                    if time_col is None:
                        continue
                    current_time = pd.to_datetime(time_col)

                    # Check if we have an open position - exit conditions
                    if stock in state.positions:
                        pos = state.positions[stock]
                        if should_exit_position(
                            pos, current_candle["close"], current_time
                        ):
                            exit_price = current_candle["close"]
                            pnl = state.close_position(stock, exit_price, current_time)

                            if pnl is not None:
                                logger.info(
                                    f"  [EXIT] {pos['side']} {stock} | Entry: Rs.{pos['entry_price']:.2f} | Exit: Rs.{exit_price:.2f} | Qty: {pos['qty']} | PnL: Rs.{pnl:.2f}"
                                )
                            entered_today = True  # Mark as processed for the day
                            break

                    # Look for new entry signals (only if we don't have a position and haven't exceeded daily limit)
                    if (
                        stock not in state.positions
                        and daily_trade_count < MAX_TRADES_PER_DAY
                        and not entered_today
                    ):
                        signal, entry_price = check_inside_bar_setup(
                            chart, idx + 1
                        )  # idx+1 because function expects index after current

                        if signal:
                            # Calculate quantity
                            per_trade_margin = state.capital / MAX_TRADES_PER_DAY
                            qty = int(per_trade_margin / entry_price)

                            if qty > 0:
                                # Enter position
                                state.positions[stock] = {
                                    "entry_price": entry_price,
                                    "qty": qty,
                                    "entry_time": current_time,
                                    "side": signal,
                                }

                                state.add_trade(
                                    stock, entry_price, qty, current_time, signal
                                )
                                state.total_trades += 1
                                daily_trade_count += 1
                                entered_today = True

                                logger.info(
                                    f"  [ENTRY] {signal} {stock} | Price: Rs.{entry_price:.2f} | Qty: {qty} | Time: {current_time.strftime('%H:%M:%S')}"
                                )
                                break  # Only one entry per stock per day

            except Exception as e:
                logger.error(
                    f"  [ERROR] Error processing {stock} on {date_str}: {str(e)}"
                )
                continue

        # Close all positions at end of day
        positions_to_close = list(state.positions.keys())
        for symbol in positions_to_close:
            try:
                # Get last price from the day's data
                chart = tsl.get_intraday_data(
                    symbol, "NSE", 15, from_date=date_str, to_date=date_str
                )
                if chart is not None and not chart.empty:
                    last_price = chart.iloc[-1]["close"]
                    last_time = pd.to_datetime(
                        chart.iloc[-1].get("timestamp")
                        or chart.iloc[-1].get("date")
                        or chart.iloc[-1].get("start_Time")
                    )
                    pos_side = state.positions.get(symbol, {}).get("side", "UNKNOWN")
                    pnl = state.close_position(symbol, last_price, last_time)
                    if pnl is not None:
                        logger.info(
                            f"  [EOD EXIT] {pos_side} {symbol} | Exit: Rs.{last_price:.2f} | PnL: Rs.{pnl:.2f}"
                        )
            except Exception as e:
                logger.warning(f"  [WARNING] Error closing {symbol} at EOD: {str(e)}")

        current_date += dt.timedelta(days=1)

    # ================= FINAL REPORT =================

    logger.info("\n" + "=" * 80)
    logger.info("BACKTEST RESULTS")
    logger.info("=" * 80)
    logger.info(f"Total Trades: {state.total_trades}")
    logger.info(f"Winning Trades: {state.winning_trades}")
    logger.info(f"Losing Trades: {state.losing_trades}")
    logger.info(
        f"Win Rate: {(state.winning_trades / state.total_trades * 100) if state.total_trades > 0 else 0:.2f}%"
    )
    logger.info(f"Total PnL: Rs.{state.total_pnl:,.2f}")
    logger.info(f"Final Capital: Rs.{state.capital + state.total_pnl:,.2f}")
    logger.info(f"Return: {(state.total_pnl / state.capital * 100):.2f}%")
    logger.info("=" * 80)

    # Save trades to CSV
    if state.trades:
        trades_df = pd.DataFrame(state.trades)
        csv_file = os.path.join(
            log_dir,
            f"inside_bar_trades_{dt.datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
        )
        trades_df.to_csv(csv_file, index=False)
        logger.info(f"\nTrades saved to: {csv_file}")

    logger.info(f"\nFull log saved to: {log_file}")

    return state


if __name__ == "__main__":
    run_backtest()
