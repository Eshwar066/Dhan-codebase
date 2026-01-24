import pdb
import time
import datetime
import traceback
import talib
from Dhan_Tradehull import Tradehull
from FreeNSEFetcher import FreeNSEFetcher
import pandas as pd


client_code = "1000690797"
token_id = "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzUxMiJ9.eyJpc3MiOiJkaGFuIiwicGFydG5lcklkIjoiIiwiZXhwIjoxNzY5Mjk3OTkxLCJpYXQiOjE3NjkyMTE1OTEsInRva2VuQ29uc3VtZXJUeXBlIjoiU0VMRiIsIndlYmhvb2tVcmwiOiIiLCJkaGFuQ2xpZW50SWQiOiIxMDAwNjkwNzk3In0.JUH6awWUcbdInVorsI_iD_9Q8Vhb9YqIf2yFZdfStIG4DQtkh7fu2yQkPr-h0LWlGWPdYBMZf2zLXyDlCZPH2w"

tsl = Tradehull(client_code, token_id)
freeNse = FreeNSEFetcher()

# ---------------- DATE ----------------
today = datetime.date.today()
expiry_date = today.strftime("%d-%m-%Y")

# ---------------- DATA ----------------

# tsl.get_intraday_data("ACC", "NSE", 5, from_date="2024-01-01", to_date="2024-01-23")
# tsl.get_intraday_data("NIFTY", "NSE", 5, from_date="2024-01-01", to_date="2024-01-23")

available_balance = tsl.get_balance()
max_risk_for_the_day = -(available_balance * 1 / 100)

print("Available Balance:", available_balance)

# ---------------- LTP ----------------
ltp_acc = tsl.get_ltp("ACC")
ltp_nifty = tsl.get_ltp("NIFTY")
print(">>ltp", ltp_acc, ltp_nifty)

# ---------------- HIST DATA ----------------
previous_hist_data = tsl.get_historical_data("ACC", "NSE", 5)
print(previous_hist_data, ">>previous_hist_data")
# intraday_hist_data = tsl.get_intraday_data("ACC", "NSE", 1)

pdb.set_trace()
# ---------------- STRIKE SELECTION ----------------
ce_name, pe_name, strike = tsl.ATM_Strike_Selection("NIFTY", expiry_date)

otm_ce_name, otm_pe_name, ce_OTM_strike, pe_OTM_strike = tsl.OTM_Strike_Selection(
    "NIFTY", expiry_date, 3
)


# ---------------- INDICATORS ----------------
intraday_hist_data = tsl.get_intraday_data(otm_ce_name, "NFO", 1)
intraday_hist_data["rsi"] = talib.RSI(intraday_hist_data["close"], timeperiod=14)

# ---------------- LOT SIZE ----------------
lot_size = tsl.get_lot_size(otm_ce_name)
qty = 2 * lot_size

# ---------------- ORDERS ----------------
orderid1 = tsl.order_placement(otm_ce_name, "NFO", qty, 0, 0, "MARKET", "BUY", "MIS")
orderid2 = tsl.order_placement("ACC", "NSE", 65, 0, 0, "MARKET", "BUY", "MIS")

# ---------------- RISK MANAGEMENT ----------------
live_pnl = tsl.get_live_pnl()

if live_pnl < max_risk_for_the_day:
    tsl.cancel_all_orders()
    tsl.kill_switch("ON")
