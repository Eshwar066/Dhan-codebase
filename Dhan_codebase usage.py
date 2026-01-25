import os
import sys
from dotenv import load_dotenv
import pdb
import time
import datetime
import traceback
import talib
from Dhan_Tradehull import Tradehull
from core.api.optionChain.dhanOptionChain import DhanOptionChain
import pandas as pd


# ================= LOGIN =================
load_dotenv()
client_code = os.getenv("DHAN_CLIENT_CODE")
token_id = os.getenv("DHAN_ACCESS_TOKEN")
tsl = Tradehull(client_code, token_id)


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
# print(">>ltp", ltp_acc, ltp_nifty)

# ---------------- HIST DATA ----------------
previous_hist_data = tsl.get_historical_data("ACC", "NSE", 5)
# print(previous_hist_data, ">>previous_hist_data")
intraday_hist_data = tsl.get_intraday_data("ACC", "NSE", 1)

# --------------option chain--------------
dhan_oc = DhanOptionChain(client_code, token_id)
oc_raw = dhan_oc.get_option_chain(
    underlying_scrip=13,
    underlying_seg="IDX_I",
    expiry="2026-01-27",
)
df_optionchain = dhan_oc.option_chain_to_df(oc_raw)
# print(df_optionchain)

#------------expiry list--------------
expiry = dhan_oc.get_upcoming_expirylist(
    underlying_scrip=13,
    underlying_seg="IDX_I",
)

#-----------------Expired-option chain data---------
rolling_data = dhan_oc.get_rolling_optionchain(
    security_id=13,
    exchange_segment="NSE_FNO",
    interval=1,
    instrument="OPTIDX",
    expiry_flag="MONTH",
    expiry_code=1,
    strike="ATM",
    option_type="CALL",
    from_date="2025-09-01",
    to_date="2025-09-30",
)
df = dhan_oc.rolling_option_to_df(rolling_data, option_type="CALL")
print(df[:12])


# ---------------- STRIKE SELECTION ----------------
# ce_name, pe_name, strike = tsl.ATM_Strike_Selection("NIFTY", expiry_date)

# otm_ce_name, otm_pe_name, ce_OTM_strike, pe_OTM_strike = tsl.OTM_Strike_Selection(
#     "NIFTY", expiry_date, 3
# )

pdb.set_trace()


# ---------------- INDICATORS ----------------
intraday_hist_data = tsl.get_intraday_data(otm_ce_name, "NFO", 1)
intraday_hist_data["rsi"] = talib.RSI(intraday_hist_data["close"], timeperiod=14)

# ---------------- LOT SIZE ----------------
lot_size = tsl.get_lot_size(otm_ce_name)
qty = 2 * lot_size

# ---------------- ORDERS ----------------
orderid1 = tsl.order_placement(otm_ce_name, "NFO", qty, 0, 0, "MARKET", "BUY", "MIS")
orderid2 = tsl.order_placement("ACC", "NSE", 65, 0, 0, "MARKET", "BUY", "MIS")
orderid2 = tsl.order_placement("ACC", "NSE", 1, 0, sl_price, "STOPMARKET", "BUY", "MIS")


# ---------------- RISK MANAGEMENT ----------------
live_pnl = tsl.get_live_pnl()

if live_pnl < max_risk_for_the_day:
    tsl.cancel_all_orders()
    tsl.kill_switch("ON")
