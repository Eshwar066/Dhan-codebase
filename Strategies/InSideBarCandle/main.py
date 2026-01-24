import os
import sys

# Project root on path so Dhan_Tradehull, core, etc. import when run from Strategies/InSideBarCandle
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import pdb
from Dhan_Tradehull import Tradehull
import pandas as pd

client_code = "1000690797"
token_id = "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzUxMiJ9.eyJpc3MiOiJkaGFuIiwicGFydG5lcklkIjoiIiwiZXhwIjoxNzY5Mjk3OTkxLCJpYXQiOjE3NjkyMTE1OTEsInRva2VuQ29uc3VtZXJUeXBlIjoiU0VMRiIsIndlYmhvb2tVcmwiOiIiLCJkaGFuQ2xpZW50SWQiOiIxMDAwNjkwNzk3In0.JUH6awWUcbdInVorsI_iD_9Q8Vhb9YqIf2yFZdfStIG4DQtkh7fu2yQkPr-h0LWlGWPdYBMZf2zLXyDlCZPH2w"
tsl = Tradehull(client_code, token_id)

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

for name in watchlist:
    print(name)

# pdb.set_trace()

# intraday_hist_data = tsl.get_intraday_data(otm_ce_name, "NFO", 1)
# intraday_hist_data["rsi"] = talib.RSI(intraday_hist_data["close"], timeperiod=14)
