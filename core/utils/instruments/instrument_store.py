from pathlib import Path
import pandas as pd
import datetime
import pdb
from run.config import RUN_MODE, RunMode

from dataclasses import dataclass
from datetime import date


class Instrument:
    def __init__(
        self,
        trading_symbol,
        custom_symbol,
        exchange,
        segment,
        instrument_type,
        expiry=None,
        strike=None,
        option_type=None,
        lot_size=1,
        instrument_id=None,
        series=None,
    ):
        self.trading_symbol = trading_symbol
        self.custom_symbol = custom_symbol

        self.exchange = exchange
        self.segment = segment
        self.instrument_type = instrument_type

        self.expiry = expiry
        self.strike = strike
        self.option_type = option_type
        self.lot_size = int(lot_size)

        self.instrument_id = instrument_id
        self.series = series

    def __repr__(self):
        return (
            f"Instrument("
            f"{self.custom_symbol}, "
            f"{self.exchange}, "
            f"{self.segment}, "
            f"{self.instrument_type}, "
            f"expiry={self.expiry}, "
            f"strike={self.strike}, "
            f"option_type={self.option_type}"
            f")"
        )

    @property
    def contract_key(self):
        """
        Uniquely identifies a tradable contract.
        Used for netting, direction checks, hedges, and rollovers.
        """
        return (
            self.exchange,
            self.segment,
            self.instrument_type,
            self.custom_symbol.split()[0],  # underlying (NIFTY, BANKNIFTY)
            self.expiry,
            self.strike,
            self.option_type,
        )


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

    def map_row_to_instrument(self, row) -> Instrument:
        # pdb.set_trace()
        return Instrument(
            trading_symbol=row["SEM_TRADING_SYMBOL"],
            custom_symbol=row["SEM_CUSTOM_SYMBOL"],
            exchange=row["SEM_EXM_EXCH_ID"],
            segment=row["SEM_SEGMENT"],
            instrument_type=row["SEM_EXCH_INSTRUMENT_TYPE"],
            expiry=row.get("SEM_EXPIRY_DATE"),
            strike=row.get("SEM_STRIKE_PRICE"),
            option_type=row.get("SEM_OPTION_TYPE"),
            lot_size=row.get("LOT_SIZE", 1),
            instrument_id=row.get("INSTRUMENT_ID"),
            series=row.get("SEM_SERIES"),
        )

    dummy_security_counter = 100000

    def intent_creation_details(
        self, trading_symbol, exchange, expiry, option_type, strike
    ) -> Instrument | None:

        instrument_exchange = {
            "NSE": "NSE",
            "BSE": "BSE",
            "NFO": "NSE",
            "BFO": "BSE",
            "MCX": "MCX",
            "CUR": "NSE",
        }

        if RUN_MODE in (RunMode.LIVE, RunMode.PAPER):
            df = self.df[
                (
                    (self.df["SEM_TRADING_SYMBOL"] == trading_symbol)
                    | (self.df["SEM_CUSTOM_SYMBOL"] == trading_symbol)
                )
                & (self.df["SEM_EXM_EXCH_ID"] == instrument_exchange[exchange])
            ]

            if df.empty:
                print(f"❌ No instrument found for {trading_symbol} on {exchange}")
                return None

            return self.map_row_to_instrument(df.iloc[0])

        # -------------------------------
        # BACKTEST / SIMULATION MODE
        # -------------------------------
        InstrumentStore.dummy_security_counter += 1

        dummy_row = {
            "SEM_EXM_EXCH_ID": instrument_exchange.get(exchange, exchange),
            "SEM_SEGMENT": "D",
            "SEM_SMST_SECURITY_ID": InstrumentStore.dummy_security_counter,
            "SEM_TRADING_SYMBOL": trading_symbol,
            "SEM_CUSTOM_SYMBOL": trading_symbol,
            "SM_SYMBOL_NAME": trading_symbol.split()[0],
            "SEM_EXCH_INSTRUMENT_TYPE": "OP",
            "SEM_OPTION_TYPE": (
                "PE" if option_type == "PUT" or option_type == "PE" else "CE"
            ),
            "SEM_STRIKE_PRICE": strike,
            "SEM_EXPIRY_DATE": expiry,
            "SEM_LOT_UNITS": 65,
            "SEM_TICK_SIZE": 5.0,
            "SEM_SERIES": None,
        }

        return self.map_row_to_instrument(pd.Series(dummy_row))
