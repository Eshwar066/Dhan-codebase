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

    def build_option_symbol(self, symbol, expiry, strike, option_type):
        """
        Output:
        NIFTY 30 MAR 25000 PUT
        NIFTY 30 MAR 25000 CALL
        """

        # normalize expiry
        if isinstance(expiry, str):
            expiry = dt.datetime.strptime(expiry, "%Y-%m-%d").date()
        elif isinstance(expiry, dt.datetime):
            expiry = expiry.date()

        day = f"{expiry.day:02d}"  # 30
        month = expiry.strftime("%b").upper()  # MAR

        strike = int(float(strike))

        # --- normalize option type ---
        opt = option_type.upper()
        option_map = {
            "CE": "CALL",
            "PE": "PUT",
            "CALL": "CALL",
            "PUT": "PUT",
        }

        if opt not in option_map:
            raise ValueError(f"Invalid option_type: {option_type}")

        option_type = option_map[opt]

        return f"{symbol.upper()} {day} {month} {strike} {option_type}"

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
        # pdb.set_trace()
        # tradingsymbol.upper(),
        return self.tsl.order_placement(
            tradingsymbol="NIFTY-Mar2026-24500-PE",
            exchange="NFO",
            quantity=65,
            price=0.0,  # MARKET → price ignored
            trigger_price=0.0,
            order_type="MARKET",
            transaction_type="SELL",
            trade_type="MARGIN",
            disclosed_quantity=0,
            after_market_order=False,
            validity="DAY",
            amo_time="OPEN",
            bo_profit_value=None,
            bo_stop_loss_Value=None,
            tag="73f0f9a6ce3943ca82c59f9c1be74290",
        )

        # (
        #     tradingsymbol="NIFTY-Mar2026-25000-CE",
        #     exchange=exchange.upper(),
        #     quantity=int(quantity),
        #     price=int(price),
        #     trigger_price=int(trigger_price),
        #     order_type=order_type.upper(),
        #     transaction_type=transaction_type.upper(),
        #     trade_type=trade_type.upper(),
        #     # disclosed_quantity=disclosed_quantity,
        #     # after_market_order=after_market_order,
        #     validity=validity,
        #     # amo_time=amo_time,
        #     # bo_profit_value=bo_profit_value,
        #     # bo_stop_loss_Value=bo_stop_loss_value,  # ✅ Capital V
        #     tag=tag,
        # )

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

    def generate_otm_strikes(
        self,
        spot_price: float,
        step: int,
        count: int,
    ):
        """
        Example:
        spot = 23300
        step = 500
        count = 3

        → [23500, 24000, 24500]
        """

        if step not in (500, 1000):
            raise ValueError("step must be 500 or 1000")

        base = ((int(spot_price) // step) + 1) * step

        return [base + i * step for i in range(count)]

    def get_nse_optionchain_historical(
        self,
        symbol,
        from_date,
        expiry_date,
        instrumentType,
        spot_price,
        strike_step,
        strike_count,
        option_type,
    ):
        """
        strike_step → 500 / 1000
        strike_count → number of strikes OTM
        """

        strikes = self.generate_otm_strikes(
            spot_price=spot_price,
            step=strike_step,
            count=strike_count,
        )
        # pdb.set_trace()

        records = []

        for strike in strikes:
            for option_type in ("CE", "PE"):
                try:
                    hist = self.nse_client.get_options_history(
                        symbol=symbol,
                        from_date=from_date,
                        to_date=expiry_date,
                        instrumentType=instrumentType,
                        expiry_date=expiry_date,
                        strike=strike,
                        option_type=option_type,
                        year=expiry_date.year,
                    )

                    if not hist or "data" not in hist or not hist["data"]:
                        continue

                    row = hist["data"][-1]

                    records.append(
                        {
                            "Strike Price": strike,
                            f"{option_type} LTP": row.get("FH_LAST_TRADED_PRICE", 0),
                        }
                    )
                    pdb.set_trace()
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
            "chain": (
                atm_base,
                oc_df,
                expiry_date,
            )
        }
