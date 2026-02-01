"""
Paper Trading runner for Inside Bar Candle Strategy.
Runs paper trading with simulated orders and logging.
"""
import os
import sys
import time
import datetime as dt
from dotenv import load_dotenv
import logging

# ---- Project root fix ----
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from core.broker.paper import PaperBroker
import pandas as pd
import talib

# ================= CONFIG =================

MAX_TRADES = 2
API_SLEEP = 0.7  # rate-limit protection
RSI_PERIOD = 14

# Market hours
START_TIME = dt.time(9, 20)
END_TIME = dt.time(14, 30)

# ================= LOGIN =================
load_dotenv()
client_code = os.getenv("DHAN_CLIENT_CODE")
token_id = os.getenv("DHAN_ACCESS_TOKEN")

if not client_code or not token_id:
    raise SystemExit("[ERROR] Missing DHAN credentials")

broker = PaperBroker(client_code, token_id)
data_provider = broker.data

# ================= CAPITAL =================

INITIAL_CAPITAL = 100000  # Paper trading capital
broker._balance = INITIAL_CAPITAL
available_balance = broker.get_balance()
per_trade_margin = available_balance / MAX_TRADES

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

log_dir = os.path.join(_ROOT, "Dependencies", "paper_trade_logs")
os.makedirs(log_dir, exist_ok=True)
log_file = os.path.join(log_dir, f"inside_bar_paper_{dt.datetime.now().strftime('%Y%m%d_%H%M%S')}.log")

# Unicode-safe handler for Windows console
class UnicodeSafeHandler(logging.StreamHandler):
    """Handler that safely handles Unicode characters on Windows console."""
    def emit(self, record):
        try:
            msg = self.format(record)
            # Replace emoji and Unicode characters with ASCII alternatives
            msg = msg.replace('⚠️', '[WARNING]')
            msg = msg.replace('📊', '[ENTRY]')
            msg = msg.replace('🚪', '[EXIT]')
            msg = msg.replace('❌', '[ERROR]')
            msg = msg.replace('📈', '[BUY]')
            msg = msg.replace('📉', '[SELL]')
            msg = msg.replace('✅', '[OK]')
            msg = msg.replace('₹', 'Rs.')
            # Try to encode and write
            try:
                stream = self.stream
                stream.write(msg + self.terminator)
                self.flush()
            except UnicodeEncodeError:
                # If encoding fails, try with error handling
                try:
                    stream.write(msg.encode('ascii', 'replace').decode('ascii') + self.terminator)
                    self.flush()
                except:
                    # Last resort: write ASCII-only version
                    safe_msg = msg.encode('ascii', 'ignore').decode('ascii')
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
        UnicodeSafeHandler(sys.stdout)  # Use safe handler directly
    ]
)
logger = logging.getLogger(__name__)

# ================= STATE =================

traded_symbols = set()
trade_count = 0
open_positions = {}  # {symbol: {"order_id": str, "side": "BUY"/"SELL", "entry_price": float, "qty": int, "entry_time": datetime}}

# ================= STRATEGY LOOP =================

def check_market_hours():
    """Check if current time is within market hours."""
    now = dt.datetime.now().time()
    return START_TIME <= now <= END_TIME

def process_stock(stock):
    """Process a single stock for trading signals."""
    global trade_count
    
    if trade_count >= MAX_TRADES:
        return False
    
    if stock in traded_symbols:
        return False
    
    try:
        # Get today's date
        today = dt.datetime.now().strftime("%Y-%m-%d")
        
        # Fetch intraday data for today
        chart = data_provider.get_intraday_data(
            stock, "NSE", 1, from_date=today, to_date=today
        )
        
        if chart is None or chart.empty or len(chart) < 20:
            return False
        
        # Calculate RSI
        chart["rsi"] = talib.RSI(chart["close"], RSI_PERIOD)
        
        if chart["rsi"].isna().iloc[-2]:
            return False
        
        # Filter by market hours
        if "timestamp" in chart.columns:
            chart["time"] = pd.to_datetime(chart["timestamp"]).dt.time
        elif "date" in chart.columns:
            chart["time"] = pd.to_datetime(chart["date"]).dt.time
        elif "start_Time" in chart.columns:
            chart["time"] = pd.to_datetime(chart["start_Time"]).dt.time
        else:
            return False
        
        chart = chart[(chart["time"] >= START_TIME) & (chart["time"] <= END_TIME)].copy()
        
        if len(chart) < 20:
            return False
        
        # Candle references
        base = chart.iloc[-4]
        inside = chart.iloc[-3]
        last = chart.iloc[-2]
        current = chart.iloc[-1]
        
        # Trend
        uptrend = last["rsi"] > 60
        downtrend = last["rsi"] < 40
        
        # Inside bar (correct definition)
        inside_candle = inside["high"] < base["high"] and inside["low"] > base["low"]
        
        # Breakouts
        upper_break = current["high"] > base["high"]
        lower_break = current["low"] < base["low"]
        
        # Quantity
        qty = int(per_trade_margin / current["close"])
        if qty <= 0:
            return False
        
        # ================= BUY =================
        if uptrend and inside_candle and upper_break:
            logger.info(f"[BUY] {stock} BUY setup detected")
            logger.info(f"   RSI: {last['rsi']:.2f} | Entry Price: Rs.{current['close']:.2f} | Qty: {qty}")
            
            # Place paper order
            order_id = broker.place_order(
                stock, "NSE", qty, 0, 0, "MARKET", "BUY", "MIS"
            )
            
            if order_id:
                open_positions[stock] = {
                    "order_id": order_id,
                    "side": "BUY",
                    "entry_price": current["close"],
                    "qty": qty,
                    "entry_time": dt.datetime.now()
                }
                traded_symbols.add(stock)
                trade_count += 1
                logger.info(f"   [OK] Paper BUY order placed: {order_id}")
                return True
        
        # ================= SELL =================
        elif downtrend and inside_candle and lower_break:
            logger.info(f"[SELL] {stock} SELL setup detected")
            logger.info(f"   RSI: {last['rsi']:.2f} | Entry Price: Rs.{current['close']:.2f} | Qty: {qty}")
            
            # Place paper order
            order_id = broker.place_order(
                stock, "NSE", qty, 0, 0, "MARKET", "SELL", "MIS"
            )
            
            if order_id:
                open_positions[stock] = {
                    "order_id": order_id,
                    "side": "SELL",
                    "entry_price": current["close"],
                    "qty": qty,
                    "entry_time": dt.datetime.now()
                }
                traded_symbols.add(stock)
                trade_count += 1
                logger.info(f"   [OK] Paper SELL order placed: {order_id}")
                return True
        
        return False
        
    except Exception as e:
        logger.error(f"[ERROR] Error processing {stock}: {str(e)}")
        return False

def check_exits():
    """Check and exit open positions if conditions are met."""
    global trade_count
    
    if not open_positions:
        return
    
    now = dt.datetime.now()
    
    # Simple exit: end of day
    if now.time() >= END_TIME:
        for symbol in list(open_positions.keys()):
            pos = open_positions[symbol]
            try:
                # Get current price
                today = dt.datetime.now().strftime("%Y-%m-%d")
                chart = data_provider.get_intraday_data(
                    symbol, "NSE", 1, from_date=today, to_date=today
                )
                
                if chart is None or chart.empty:
                    continue
                
                exit_price = chart.iloc[-1]["close"]
                
                # Place opposite order to exit
                if pos["side"] == "BUY":
                    exit_side = "SELL"
                else:
                    exit_side = "BUY"
                
                exit_order_id = broker.place_order(
                    symbol, "NSE", pos["qty"], 0, 0, "MARKET", exit_side, "MIS"
                )
                
                if exit_order_id:
                    # Calculate PnL
                    if pos["side"] == "BUY":
                        pnl = (exit_price - pos["entry_price"]) * pos["qty"]
                    else:
                        pnl = (pos["entry_price"] - exit_price) * pos["qty"]
                    
                    logger.info(f"[EXIT] {pos['side']} {symbol} | Entry: Rs.{pos['entry_price']:.2f} | Exit: Rs.{exit_price:.2f} | Qty: {pos['qty']} | PnL: Rs.{pnl:.2f}")
                    
                    del open_positions[symbol]
                    trade_count -= 1  # Free up trade slot
                    traded_symbols.discard(symbol)
                    
            except Exception as e:
                logger.error(f"[ERROR] Error exiting {symbol}: {str(e)}")

def main():
    """Main paper trading loop."""
    logger.info("=" * 80)
    logger.info("INSIDE BAR CANDLE STRATEGY - PAPER TRADING")
    logger.info("=" * 80)
    logger.info(f"Initial Capital: Rs.{INITIAL_CAPITAL:,.2f}")
    logger.info(f"Per Trade Margin: Rs.{per_trade_margin:,.2f}")
    logger.info(f"Max Trades: {MAX_TRADES}")
    logger.info(f"Market Hours: {START_TIME} - {END_TIME}")
    logger.info("=" * 80)
    
    iteration = 0
    
    while True:
        if not check_market_hours():
            logger.info("[PAUSED] Outside market hours. Waiting...")
            time.sleep(60)  # Check every minute
            continue
        
        iteration += 1
        logger.info(f"\n--- Iteration {iteration} ---")
        
        # Check exits first
        check_exits()
        
        # Process watchlist
        for stock in watchlist:
            if trade_count >= MAX_TRADES:
                break
            
            if process_stock(stock):
                time.sleep(API_SLEEP)
        
        # Show current positions
        if open_positions:
            logger.info(f"\n[POSITIONS] Open Positions: {len(open_positions)}")
            for symbol, pos in open_positions.items():
                logger.info(f"   {symbol}: {pos['side']} {pos['qty']} @ Rs.{pos['entry_price']:.2f} | Entry: {pos['entry_time'].strftime('%H:%M:%S')}")
        
        # Wait before next iteration
        time.sleep(API_SLEEP * 2)
        
        if trade_count >= MAX_TRADES and not open_positions:
            logger.info("[OK] Max trades reached and all positions closed. Exiting.")
            break

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("\n[WARNING] Paper trading stopped by user")
    except Exception as e:
        logger.error(f"[ERROR] Fatal error: {str(e)}", exc_info=True)
