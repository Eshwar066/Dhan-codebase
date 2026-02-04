from pathlib import Path
import pandas as pd
import datetime
import pdb
from run.config import RUN_MODE, RunMode

# instrument_store.df.columns.tolist()
# [
#     "Unnamed: 0",
#     "SEM_EXM_EXCH_ID",
#     "SEM_SEGMENT",
#     "SEM_SMST_SECURITY_ID",
#     "SEM_INSTRUMENT_NAME",
#     "SEM_EXPIRY_CODE",
#     "SEM_TRADING_SYMBOL",
#     "SEM_LOT_UNITS",
#     "SEM_CUSTOM_SYMBOL",
#     "SEM_EXPIRY_DATE",
#     "SEM_STRIKE_PRICE",
#     "SEM_OPTION_TYPE",
#     "SEM_TICK_SIZE",
#     "SEM_EXPIRY_FLAG",
#     "SEM_EXCH_INSTRUMENT_TYPE",
#     "SEM_SERIES",
#     "SM_SYMBOL_NAME",
# ]

#  instrument_store.df[instrument_store.df["SM_SYMBOL_NAME"] == "NIFTY" ].head()
# instrument_store.df[instrument_store.df["SEM_EXCH_INSTRUMENT_TYPE"] == "OPTIDX"]["SM_SYMBOL_NAME"].value_counts().head(10)


# 2️⃣ Filter NIFTY PE options
# nifty_options = instrument_store.df[
#     instrument_store.df["SEM_TRADING_SYMBOL"].str.contains("NIFTY")
#     & (instrument_store.df["SEM_OPTION_TYPE"] == "PE")
# ]

# # 3️⃣ Pick nearest strike to your target
# target_strike = 25000
# nearest_row = nifty_options.iloc[
#     (nifty_options["SEM_STRIKE_PRICE"] - target_strike).abs().argmin()
# ]

# ✅ Found security row:
# Unnamed: 0                                  216446
# SEM_EXM_EXCH_ID                                NSE
# SEM_SEGMENT                                      D
# SEM_SMST_SECURITY_ID                         62925
# SEM_INSTRUMENT_NAME                         OPTIDX
# SEM_EXPIRY_CODE                                  0
# SEM_TRADING_SYMBOL          NIFTY-Mar2026-24000-PE
# SEM_LOT_UNITS                                 65.0
# SEM_CUSTOM_SYMBOL           NIFTY 30 MAR 24000 PUT
# SEM_EXPIRY_DATE                         2026-03-30
# SEM_STRIKE_PRICE                           24000.0
# SEM_OPTION_TYPE                                 PE
# SEM_TICK_SIZE                                  5.0
# SEM_EXPIRY_FLAG                                  M
# SEM_EXCH_INSTRUMENT_TYPE                        OP
# SEM_SERIES                                     NaN
# SM_SYMBOL_NAME                                 NaN
from datetime import date, datetime

INDEX_TO_OPT_SYMBOL = {
    "NIFTY": "SX50OPT",
    "BANKNIFTY": "BKXOPT",
    "SENSEX": "BSXOPT",
}


class InstrumentStore:
    def __init__(self, csv_path: Path):
        self.df = pd.read_csv(csv_path, low_memory=False)
        self.df.columns = self.df.columns.str.strip()
        self.df["SEM_EXPIRY_DATE"] = pd.to_datetime(
            self.df["SEM_EXPIRY_DATE"], errors="coerce"
        ).dt.date
        self.df["SEM_STRIKE_PRICE"] = pd.to_numeric(
            self.df["SEM_STRIKE_PRICE"], errors="coerce"
        )

        csv_path = Path(csv_path).resolve()

        if not csv_path.exists():
            raise FileNotFoundError(f"Instrument file not found: {csv_path}")

    # --------------------------------------------------
    # 🔹 CORE RESOLVER
    # --------------------------------------------------

    # working
    def map_row_to_instrument(self, row):
        return {
            "exchange": row["SEM_EXM_EXCH_ID"],
            "segment": row["SEM_SEGMENT"],
            "instrument_id": int(row["SEM_SMST_SECURITY_ID"]),
            "trading_symbol": row["SEM_TRADING_SYMBOL"],
            "custom_symbol": row["SEM_CUSTOM_SYMBOL"],
            "symbol": row["SM_SYMBOL_NAME"],
            "instrument_type": row["SEM_EXCH_INSTRUMENT_TYPE"],
            "option_type": row["SEM_OPTION_TYPE"],
            "strike": (
                float(row["SEM_STRIKE_PRICE"])
                if not pd.isna(row["SEM_STRIKE_PRICE"])
                else None
            ),
            "expiry": row["SEM_EXPIRY_DATE"],
            "lot_size": int(row["SEM_LOT_UNITS"]),
            "tick_size": float(row["SEM_TICK_SIZE"]),
            "series": row["SEM_SERIES"],
        }

    # working
    def show_sample(self, n=5):
        print(self.df.head(n))

    #  main
    dummy_security_counter = 100000

    def intent_creation_details(
        self, tradingsymbol, exchange, expiry, option_type, strike
    ):
        instrument_exchange = {
            "NSE": "NSE",
            "BSE": "BSE",
            "NFO": "NSE",
            "BFO": "BSE",
            "MCX": "MCX",
            "CUR": "NSE",
        }
        if RUN_MODE == RunMode.LIVE or RUN_MODE == RunMode.PAPER:
            security_check = self.df[
                (
                    (self.df["SEM_TRADING_SYMBOL"] == tradingsymbol)
                    | (self.df["SEM_CUSTOM_SYMBOL"] == tradingsymbol)
                )
                & (self.df["SEM_EXM_EXCH_ID"] == instrument_exchange[exchange])
            ]
        else:
            InstrumentStore.dummy_security_counter += 1
            dummy_row = {
                "Unnamed: 0": 0,
                "SEM_EXM_EXCH_ID": instrument_exchange.get(exchange, exchange),
                "SEM_SEGMENT": "D",
                "SEM_SMST_SECURITY_ID": InstrumentStore.dummy_security_counter,
                "SEM_INSTRUMENT_NAME": "OPTIDX",
                "SEM_EXPIRY_CODE": 0,
                "SEM_TRADING_SYMBOL": tradingsymbol,
                "SEM_LOT_UNITS": 65.0,
                "SEM_CUSTOM_SYMBOL": tradingsymbol,
                "SEM_EXPIRY_DATE": pd.Timestamp(expiry),
                "SEM_STRIKE_PRICE": strike,
                "SEM_OPTION_TYPE": ("PE" if option_type == "PUT" else "CE"),
                "SEM_TICK_SIZE": 5.0,
                "SEM_EXPIRY_FLAG": "M",
                "SEM_EXCH_INSTRUMENT_TYPE": "OP",
                "SEM_SERIES": None,
                "SM_SYMBOL_NAME": None,
            }

            # Convert to pandas Series to mimic a row
            security_check = pd.DataFrame([dummy_row])

        # Check if present and return row(s)
        if not security_check.empty:
            # If you want the first match only
            row = security_check.iloc[0]
            print("✅ Found security row:")
            print(row)
            return row
        else:
            print(
                f"❌ No instrument found for symbol '{tradingsymbol}' on exchange '{exchange}'"
            )
