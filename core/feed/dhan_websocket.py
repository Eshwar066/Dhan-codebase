"""
Dhan WebSocket LTP feed. Data from Dhan only.
Uses core.api.get_instrument_file for instrument master.
"""

import datetime
import os
import time
import warnings

import pandas as pd
import xlwings as xw
from dhanhq import marketfeed

from core.api.dhan_data import get_instrument_file

warnings.filterwarnings("ignore")

INSTRUMENT_EXCHANGE = {"NSE": "NSE", "BSE": "BSE", "NFO": "NSE", "BFO": "BSE", "MCX": "MCX", "CUR": "NSE", "BSE_IDX": "BSE", "NSE_IDX": "NSE"}
EXCHANGE_ID = {"NSE": marketfeed.NSE, "BSE": marketfeed.BSE, "MCX": marketfeed.MCX, "NFO": marketfeed.NSE_FNO, "BFO": marketfeed.BSE_FNO, "IDX": marketfeed.IDX, "BSE_IDX": marketfeed.IDX, "NSE_IDX": marketfeed.IDX}


def create_instruments(watchlist, stock_exchange, instrument_df):
    rows = {}
    row = 1
    instruments = []
    for tradingsymbol in watchlist:
        try:
            row += 1
            exchange_ = stock_exchange.get(tradingsymbol, "NSE")
            exchange = INSTRUMENT_EXCHANGE.get(exchange_, "NSE")
            security_id = instrument_df[
                ((instrument_df["SEM_TRADING_SYMBOL"] == tradingsymbol) | (instrument_df["SEM_CUSTOM_SYMBOL"] == tradingsymbol))
                & (instrument_df["SEM_EXM_EXCH_ID"] == exchange)
            ].iloc[-1]["SEM_SMST_SECURITY_ID"]
            exchange_segment = EXCHANGE_ID.get(exchange_, marketfeed.NSE)
            instruments.append((exchange_segment, str(security_id), marketfeed.Quote))
            rows[security_id] = row
        except Exception as e:
            print(f"Error: {e} for {tradingsymbol}")
            continue
    return instruments, rows


def run_feed(client_id: str, access_token: str, instruments, sheet, rows, deps_dir: str = "Dependencies"):
    try:
        data = marketfeed.DhanFeed(client_id, access_token, instruments)
        previous_watchlist = []

        while True:
            last_row_col1 = sheet.range("A1").end("down").row
            last_row_col2 = sheet.range("B1").end("down").row
            r = max(last_row_col1, last_row_col2)
            data_frame = sheet.range("A1").expand().options(pd.DataFrame, header=1, index=False).value
            stock_exchange = sheet.range(f"A2:B{r}").options(dict).value or {}
            watchlist = data_frame["Script Name"].tolist() if data_frame is not None else []

            if watchlist != previous_watchlist:
                print("Watchlist changed. Reconnecting the feed...")
                instrument_df = get_instrument_file(deps_dir)
                new_instruments, new_rows = create_instruments(watchlist, stock_exchange, instrument_df)
                data.disconnect()
                print("Disconnected from WebSocket feed.")
                previous_watchlist = watchlist
                rows.clear()
                rows.update(new_rows)
                instruments[:] = new_instruments
                data = marketfeed.DhanFeed(client_id, access_token, new_instruments)
                data.run_forever()

            response = data.get_data()
            if response and "LTP" in response:
                security_id = response["security_id"]
                row = rows.get(int(security_id))
                if row:
                    df = pd.DataFrame(response, index=[0])
                    cols = [c for c in ["LTP", "avg_price", "volume", "total_sell_quantity", "open", "close", "high", "low"] if c in df.columns]
                    if cols:
                        sheet.range(f"C{row}").value = df[cols].values.tolist()
    except Exception as e:
        print(f"WebSocket connection error: {e}")
        print("Reconnecting Again...")
        run_feed(client_id, access_token, instruments, sheet, rows, deps_dir)


def main_loop(client_id: str, access_token: str, excel_path: str = "Websocket.xlsx", sheet_name: str = "LTP", deps_dir: str = "Dependencies"):
    """Run Dhan LTP feed; instruments from Dhan (core.api.get_instrument_file)."""
    wb = xw.Book(excel_path)
    sheet = wb.sheets[sheet_name]
    instrument_df = get_instrument_file(deps_dir)

    last_row_col1 = sheet.range("A1").end("down").row
    last_row_col2 = sheet.range("B1").end("down").row
    r = max(last_row_col1, last_row_col2)
    data_frame = sheet.range("A1").expand().options(pd.DataFrame, header=1, index=False).value
    stock_exchange = sheet.range(f"A2:B{r}").options(dict).value or {}
    watchlist = data_frame["Script Name"].tolist() if data_frame is not None else []

    instruments, rows = create_instruments(watchlist, stock_exchange, instrument_df)
    run_feed(client_id, access_token, instruments, sheet, rows, deps_dir)
