import os
import sys
import pandas as pd
from dotenv import load_dotenv
from Dhan_Tradehull import Tradehull
from core.data.sources.NSEClient import NSEClient
import pdb
import datetime as dt

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
        exchange,
        interval,
        expiry_flag,
        expiry_code,
        strike,
        option_type,
        from_date,
        to_date,
        securityId,
        instrument,
        exchangeSegment,
    ):
        data = self.tsl.get_expired_option_data(
            exchange=exchange,
            interval=interval,
            expiry_flag=expiry_flag,
            expiry_code=expiry_code,
            strike=strike,
            option_type=option_type,
            fromDate=from_date,
            toDate=to_date,
            securityId=securityId,
            instrument=instrument,
            exchangeSegment=exchangeSegment,
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

        [CE OI, CE Chg in OI, CE Volume, CE IV, CE LTP, CE Bid Qty, CE Bid, CE Ask, CE Ask Qty, CE Delta, CE Theta, CE Gamma, CE Vega, Strike Price, PE Bid Qty, PE Bid, PE Ask, PE Ask Qty, PE LTP, PE IV, PE Volume, PE Chg in OI, PE OI, PE Delta, PE Theta, PE Gamma, PE Vega]
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

    def get_order_list(self):
        """For idempotency / order lookup. Uses Tradehull if available."""
        return getattr(self.tsl, "get_order_list", lambda: [])()

    def exit_position(position):
        print(position)

    def place_order(
        self,
        tradingsymbol: str,
        exchange: str,
        quantity: int,
        price: float = 0,
        trigger_price: float = 0,
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
        Thin execution wrapper for Dhan. Used only via broker layer (DhanBrokerApi).
        Returns dict with "status" and "order_id" on success.
        """
        result = self.tsl.order_placement(
            tradingsymbol=tradingsymbol,
            exchange=exchange.upper(),
            quantity=int(quantity),
            price=float(price),
            trigger_price=float(trigger_price),
            order_type=order_type.upper(),
            transaction_type=transaction_type.upper(),
            trade_type=trade_type.upper(),
            disclosed_quantity=int(disclosed_quantity),
            after_market_order=bool(after_market_order),
            validity=validity,
            amo_time=amo_time,
            bo_profit_value=bo_profit_value,
            bo_stop_loss_Value=bo_stop_loss_value,
            tag=tag or "",
        )
        return result if isinstance(result, dict) else {"status": "error", "order_id": None}

    # =============================================================================
    # NSE API
    def get_nse_expiries(self, symbol, year, instrument="OPTIDX"):
        key = (symbol, year, instrument)

        if key not in self.expiry_cache:
            # sync wrapper, returns list
            self.expiry_cache[key] = self.nse_client.get_expiries(
                symbol, year, instrument
            )

        return self.expiry_cache[key]

    # nse historical option chain

    def get_nse_optionchain_historical(
        self,
        symbol,
        from_date,
        expiry_date,
        instrumentType,
        spot_price,
        option_type,
        strikes,
    ):

        records = []
        # pdb.set_trace()
        for strike in strikes:
            try:
                hist = self.nse_client.get_options_history(
                    symbol=symbol,
                    from_date=from_date.strftime("%Y-%m-%d"),
                    to_date=expiry_date.strftime("%Y-%m-%d"),
                    instrumentType=instrumentType,
                    expiry_date=expiry_date.strftime("%Y-%m-%d"),
                    strike=int(float(strike)),
                    option_type=option_type,
                    year=expiry_date.year,
                )

                if not hist:
                    print(">>no hist")
                    continue

                row = hist[0]

                records.append(
                    {
                        "Strike Price": strike,
                        f"{option_type} LTP": row.get("FH_LAST_TRADED_PRICE", 0),
                    }
                )
            except Exception:
                continue

        if not records:
            return None

        oc_df = (
            pd.DataFrame(records)
            .groupby("Strike Price")
            .first()
            .reset_index()
            .sort_values("Strike Price")
        )
        atm_base = strikes[0]

        return {
            "symbol": symbol,
            "exchange": "OPTIDX",
            "chain": oc_df,
        }
        # return {
        #     "chain": (
        #         atm_base,
        #         oc_df,
        #         expiry_date,
        #     )
        # }
