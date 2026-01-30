import os
import sys
import pandas as pd
from dotenv import load_dotenv
from Dhan_Tradehull import Tradehull
from core.data.sources.NSEClient import NSEClient
import pdb

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

load_dotenv()


class DhanSource:
    def __init__(self):
        client_id = os.getenv("DHAN_CLIENT_CODE")
        access_token = os.getenv("DHAN_ACCESS_TOKEN")

        if not client_id or not access_token:
            raise RuntimeError("❌ Dhan credentials missing")

        self.tsl = Tradehull(client_id, access_token)
        self.expiry_cache = {}
        self.nse_client = NSEClient()

    def get_nse_expiries(self, symbol, year, instrument="OPTIDX"):
        key = (symbol, year, instrument)

        if key not in self.expiry_cache:
            # sync wrapper, returns list
            self.expiry_cache[key] = self.nse_client.get_expiries(
                symbol, year, instrument
            )

        return self.expiry_cache[key]

    def get_latest_candles(self, symbols, debug):
        # """
        # Returns:
        # {
        #     "NIFTY": { open, high, low, close, ltp, ... },
        #     "BANKNIFTY": {...}
        # }
        # """
        return self.tsl.get_ohlc_data(symbols, debug)

    #  long term historical data
    def get_intraday(self, symbol, start_date, end_date, timeframe, exchange, sector):
        df = self.tsl.get_long_term_historical_data(
            tradingsymbol=symbol,
            exchange=exchange,
            timeframe=timeframe,
            from_date=start_date,
            to_date=end_date,
            sector=sector,
        )

        if df is None or df.empty:
            return None

        # Normalize timestamp
        if "timestamp" in df.columns:
            df["timestamp"] = pd.to_datetime(df["timestamp"])
        elif "date" in df.columns:
            df["timestamp"] = pd.to_datetime(df["date"])
        elif "start_Time" in df.columns:
            df["timestamp"] = pd.to_datetime(df["start_Time"])
        else:
            return None

        df = df.sort_values("timestamp").reset_index(drop=True)

        # Market hours filter
        df["time"] = df["timestamp"].dt.time
        # df = df[(df["time"] >= START_TIME) & (df["time"] <= END_TIME)]

        return df.reset_index(drop=True)

    def get_live_expiry(self, symbol, exchange):
        expiry_list = self.tsl.get_expiry_list(Underlying=symbol, exchange=exchange)
        return expiry_list

    def get_expired_optionchain(
        self,
        symbol,
        monthlyExpiryDate,
        exchange,
        interval,
        expiry_flag,
        expiry_code,
        strike,
        option_type,
        from_date,
        to_date,
    ):
        data = self.tsl.get_expired_option_data(
            tradingsymbol=symbol,
            exchange=exchange,
            interval=interval,  # 1-hour candle
            expiry_flag=expiry_flag,  # Monthly expiry
            expiry_code=expiry_code,  # March 2023 expiry (check your DHAN expiry sequence)
            strike=strike,  # OTM strike relative to ATM
            option_type=option_type,
            from_date=from_date,  # start of month
            to_date=to_date,  # expiry date
        )

        return data

    def get_atm_options(self, symbol, expiry_index=0):
        ce, pe, strike = self.tsl.ATM_Strike_Selection(symbol, expiry_index)

        return {"ce": ce, "pe": pe, "strike": strike}

    def get_otm_options(self, symbol, expiry_index=0, distance=1):
        ce, pe, ce_strike, pe_strike = self.tsl.OTM_Strike_Selection(
            symbol, expiry_index, distance
        )

        return {"ce": ce, "pe": pe, "ce_strike": ce_strike, "pe_strike": pe_strike}

    def get_itm_options(self, symbol, expiry_index=0, distance=1):
        ce, pe, ce_strike, pe_strike = self.tsl.ITM_Strike_Selection(
            symbol, expiry_index, distance
        )

        return {"ce": ce, "pe": pe, "ce_strike": ce_strike, "pe_strike": pe_strike}

    def get_live_option_chain(
        self,
        symbol: str,
        exchange: str,
        expiry_index: int,
        strikes_around_atm: int,
    ):
        """
        Simple engine-friendly wrapper.
        Returns ATM strike + filtered option chain df.
        """

        df = self.tsl.get_option_chain(
            Underlying=symbol,
            exchange=exchange,
            expiry=expiry_index,
            num_strikes=strikes_around_atm,
        )

        return {
            "symbol": symbol,
            "exchange": exchange,
            "chain": df,
        }

    def get_positions(self, debug="NO"):
        return self.tsl.get_positions(debug=debug)

    def exit_position(position):
        print(position)

    def place_order(
        self,
        tradingsymbol: str,
        exchange: str,
        quantity: int,
        price: int = 0,
        trigger_price: int = 0,
        order_type: str = "MARKET",
        transaction_type: str = "BUY",
        trade_type: str = "MARGIN",
        disclosed_quantity: int = 0,
        after_market_order: bool = False,
        validity: str = "DAY",
        amo_time: str = "OPEN",
        bo_profit_value=None,
        bo_stop_loss_value=None,
        tag: str | None = None,
    ):
        """
        Thin execution wrapper for Dhan.
        No strategy / portfolio logic here.
        """

        return self.tsl.order_placement(
            tradingsymbol=tradingsymbol.upper(),
            exchange=exchange.upper(),
            quantity=int(quantity),
            price=int(price),
            trigger_price=int(trigger_price),
            order_type=order_type.upper(),
            transaction_type=transaction_type.upper(),
            trade_type=trade_type.upper(),
            disclosed_quantity=disclosed_quantity,
            after_market_order=after_market_order,
            validity=validity,
            amo_time=amo_time,
            bo_profit_value=bo_profit_value,
            bo_stop_loss_value=bo_stop_loss_value,
            tag=tag,
        )
