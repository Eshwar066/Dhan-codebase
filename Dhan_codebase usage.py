import os
import sys
from dotenv import load_dotenv
import pdb
import time
import datetime
import traceback
import talib

import pandas as pd
from core.library.dhan_tradehull import Tradehull


# https://pypi.org/project/Dhan-Tradehull/#history
# ================= LOGIN =================
load_dotenv()
client_code = os.getenv("DHAN_CLIENT_CODE")
token_id = os.getenv("DHAN_ACCESS_TOKEN")
tsl = Tradehull(client_code, token_id)


# #  =========historical data=====================
# data1 = tsl.get_historical_data(
#     tradingsymbol="NIFTY", exchange="INDEX", timeframe="DAY"
# )
# data2 = tsl.get_historical_data(tradingsymbol="ACC", exchange="NSE", timeframe="1")
# # sector data
# data3 = tsl.get_historical_data(
#     tradingsymbol="NIFTY 100", exchange="NSE", timeframe="DAY", sector="YES"
# )
# # print(data1, data2, data3)

# # ============long term historical data==================
# data4 = tsl.get_long_term_historical_data(
#     tradingsymbol="RELIANCE",
#     exchange="NSE",
#     timeframe="5",
#     from_date="2021-01-01",
#     to_date="2025-10-17",
# )
# sector data
# data5 = tsl.get_long_term_historical_data(
#     tradingsymbol="NIFTY 100",
#     exchange="NSE",
#     timeframe="5",
#     from_date="2022-01-01",
#     to_date="2025-12-03",
#     sector="YES",
# )

# ==========ATM Strike============
# CE_symbol_name, PE_symbol_name, strike = tsl.ATM_Strike_Selection(
#     Underlying="NIFTY", Expiry=0
# )
# ==========OTM Strike============
# CE_symbol_name, PE_symbol_name, CE_strike, PE_strike = tsl.OTM_Strike_Selection(
#     Underlying="NIFTY", Expiry=0, OTM_count=5
# )
# ==========ITM Strike============
# CE_symbol_name, PE_symbol_name, CE_strike, PE_strike = tsl.ITM_Strike_Selection(
#     Underlying="NIFTY", Expiry=0, ITM_count=1
# )
# ==========Option greeks===========
# all_values = tsl.get_option_greek(
#     strike=24400,
#     expiry=0,
#     asset="NIFTY",
#     interest_rate=10,
#     flag="all_val",
#     scrip_type="CE",
# )

# ===============Order placement================
# orderid1 = tsl.order_placement(
#     "NIFTY 21 NOV 24400 CALL", "NFO", 75, 0.05, 0, "LIMIT", "BUY", "MIS"
# )
# print(orderid1)
# orderid2 = tsl.order_placement("YESBANK", "NSE", 1, 0, 0, "MARKET", "BUY", "MIS")
# print(orderid2)

# orderid = tsl.order_placement(
#     "SENSEX 06 SEP 81900 PUT", "BFO", 10, 0, 0, "MARKET", "BUY", "MIS"
# )
# orderid = tsl.order_placement("ACC", "NSE", 1, 0, 0, "MARKET", "BUY", "MIS")
# orderid = tsl.order_placement(
#     "CRUEDOIL DEC FUT", "MCX", 1, 4567, 0, "LIMIT", "BUY", "CNC"
# )
# orderid = tsl.order_placement("ACC", "NSE", 1, 2674, 2670, "STOPLIMIT", "BUY", "MIS")
# orderid = tsl.order_placement("ACC", "NSE", 1, 0, 2670, "STOPMARKET", "BUY", "MIS")

# 1-2-26
# orderid = tsl.order_placement(
#     tradingsymbol="NIFTY 05 FEB 25300 CALL",
#     exchange="NFO",
#     quantity=65,
#     price=0.05,
#     trigger_price=0,
#     order_type="LIMIT",
#     transaction_type="BUY",
#     trade_type="MIS",
#     # after_market_order=True,
#     # amo_time="OPEN",
# )

orderid1 = tsl.order_placement(
    "NIFTY 03 FEB 28100 CALL", "NFO", 75, 0.05, 0, "LIMIT", "BUY", "MIS"
)
print(orderid1)

# orderid = tsl.order_placement(
#     "ACC",
#     "NSE",
#     quantity=1,
#     price=100,  # ignored
#     trigger_price=0,  # ignored
#     order_type="Limit",
#     transaction_type="BUY",
#     trade_type="MIS",
#     # after_market_order=True,
#     # amo_time="OPEN",
# )
# print(orderid)
pdb.set_trace()
# =========================Modify order========================
# orderid = '12241210603927'
# modified_order_id = tsl.modify_order(order_id=orderid,order_type="LIMIT",quantity=50,price=0.1,trigger_price=0)
# ========================== Available balance====================
available_balance = tsl.get_balance()
max_risk_for_the_day = -(available_balance * 1 / 100)
print("Available Balance:", available_balance)
# =================option chain==================
# option_chain = tsl.get_option_chain(
#     Underlying="NIFTY", exchange="INDEX", expiry=0, num_strikes=10
# )
# print(option_chain)

# ============expired option chain=============
# data = tsl.get_expired_option_data(
#     tradingsymbol="RELIANCE",
#     exchange="NSE",
#     interval=1,
#     expiry_flag="MONTH",
#     expiry_code=1,
#     strike="ATM",
#     option_type="CALL",
#     from_date="2023-10-10",
#     to_date="2024-11-10",
# )
# print(data)


# pdb.set_trace()

# ==========end======

# CE_symbol_name, PE_symbol_name, strike = tsl.ATM_Strike_Selection(
#     Underlying="NIFTY", Expiry=0
# )
# print(CE_symbol_name, PE_symbol_name, strike)

# ---------------- STRIKE SELECTION ----------------
# ce_name, pe_name, strike = tsl.ATM_Strike_Selection("NIFTY", expiry_date)

# otm_ce_name, otm_pe_name, ce_OTM_strike, pe_OTM_strike = tsl.OTM_Strike_Selection(
#     "NIFTY", expiry_date, 3
# )

# pdb.set_trace()


# ---------------- INDICATORS ----------------
# intraday_hist_data = tsl.get_intraday_data(otm_ce_name, "NFO", 1)
# intraday_hist_data["rsi"] = talib.RSI(intraday_hist_data["close"], timeperiod=14)

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
