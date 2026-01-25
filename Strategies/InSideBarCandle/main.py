import os
import sys
import time
import datetime as dt
from dotenv import load_dotenv


# ---- Project root fix ----
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from Dhan_Tradehull import Tradehull
import pandas as pd
import talib

# ================= CONFIG =================

PAPER_TRADING = True  # 🔴 Set False for live
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
    raise SystemExit("❌ Missing DHAN credentials")

tsl = Tradehull(client_code, token_id)

# ================= CAPITAL =================

available_balance = tsl.get_balance()
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

# ================= STATE =================

traded_symbols = set()
trade_count = 0

# ================= STRATEGY LOOP =================
while True:
    for stock in watchlist:

        if trade_count >= MAX_TRADES:
            break

        # now = dt.datetime.now().time()
        # if not (START_TIME <= now <= END_TIME):
        #     break

        # ---- Fetch data ----
        if stock in traded_symbols:
            continue

        chart = tsl.get_intraday_data(
            stock, "NSE", 1, from_date="2026-01-23", to_date="2026-01-23"
        )

        if chart is None or chart.empty or len(chart) < 20:
            continue

        # ---- Indicators ----
        chart["rsi"] = talib.RSI(chart["close"], RSI_PERIOD)

        if chart["rsi"].isna().iloc[-2]:
            continue

        # ---- Candle references ----
        base = chart.iloc[-4]
        inside = chart.iloc[-3]
        last = chart.iloc[-2]

        # ---- Trend ----
        uptrend = last["rsi"] > 60
        downtrend = last["rsi"] < 40

        # ---- Inside bar (correct definition) ----
        inside_candle = inside["high"] < base["high"] and inside["low"] > base["low"]

        # ---- Breakouts ----
        upper_break = last["high"] > base["high"]
        lower_break = last["low"] < base["low"]

        # ---- Quantity ----
        qty = int(per_trade_margin / last["close"])
        if qty <= 0:
            continue

        # ================= BUY =================
        if uptrend and inside_candle and upper_break:

            print(f"📈 {stock} BUY setup")

            if not PAPER_TRADING:
                tsl.order_placement(stock, "NSE", qty, 0, 0, "MARKET", "BUY", "MIS")

            traded_symbols.add(stock)
            trade_count += 1

        # ================= SELL =================
        elif downtrend and inside_candle and lower_break:

            print(f"📉 {stock} SELL setup")

            if not PAPER_TRADING:
                tsl.order_placement(stock, "NSE", qty, 0, 0, "MARKET", "SELL", "MIS")

            traded_symbols.add(stock)
            trade_count += 1

print("✅ Strategy execution completed", trade_count)
