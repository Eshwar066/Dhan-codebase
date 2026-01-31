from pathlib import Path
import pandas as pd
import datetime

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
    def intent_creation_details(self, strike, symbol, optType):
        # use
        # instrument_store.intent_creation_details(25500, "NIFTY", "PE")
        nifty_options = self.df[
            self.df["SEM_TRADING_SYMBOL"].str.contains(symbol)
            & (self.df["SEM_OPTION_TYPE"] == optType)
        ]
        target_strike = strike
        nearest_row = nifty_options.iloc[
            (nifty_options["SEM_STRIKE_PRICE"] - target_strike).abs().argmin()
        ]
        row = self.map_row_to_instrument(nearest_row)
        return row
