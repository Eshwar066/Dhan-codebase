"""
Dhan data and order execution via in-project Tradehull library.
All data feeding (candles, LTP, option chain, expiries) and order placement
go through this source; the data layer (DhanDataProvider) and broker layer
(DhanBrokerApi) wrap it for engines and order management.
"""

import os
import sys
import pandas as pd
from pathlib import Path
from dotenv import load_dotenv
import requests
import json
import pdb

# Use in-project Dhan Tradehull library
from core.library.dhan_tradehull import Tradehull
from core.data.sources.NSEClient import NSEClient

load_dotenv()

# Project root: parent of 'core' so that Dependencies/ and instrument file paths work
PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


class DhanSource:
    """
    Single entry point for Dhan: market data (for data layer) and order placement (for broker).
    Uses core.library.dhan_tradehull.Tradehull for all Dhan API calls.
    """

    def __init__(self, client_id=None, access_token=None, dependencies_path=None):
        client_id = client_id or os.getenv("DHAN_CLIENT_CODE")
        access_token = access_token or os.getenv("DHAN_ACCESS_TOKEN")
        if not client_id or not access_token:
            raise RuntimeError(
                "❌ Dhan credentials missing (DHAN_CLIENT_CODE, DHAN_ACCESS_TOKEN)"
            )

        self._deps_path = Path(dependencies_path or PROJECT_ROOT / "Dependencies")
        self._ensure_deps_path()

        self.tsl = Tradehull(client_id, access_token)
        self.expiry_cache = {}
        self.nse_client = NSEClient()

    def _ensure_deps_path(self):
        """Ensure Dependencies folder exists for Tradehull instrument file."""
        self._deps_path.mkdir(parents=True, exist_ok=True)
        # Tradehull uses os.listdir("Dependencies") and "Dependencies\\file" - run from project root
        if os.getcwd() != str(PROJECT_ROOT):
            os.chdir(PROJECT_ROOT)

    # -------------------------------------------------------------------------
    # Data: Candles / OHLC
    # -------------------------------------------------------------------------
    def get_latest_candles(self, symbols, debug="NO"):
        """Latest OHLC/LTP per symbol. Returns dict { symbol: { open, high, low, close, ... } }."""
        if not isinstance(symbols, list):
            symbols = [symbols]
        return self.tsl.get_ohlc_data(symbols, debug)

    def get_intraday(self, symbol, start_date, end_date, timeframe, exchange, sector):
        """Long-term historical intraday candles for backtest."""
        df = self.tsl.get_long_term_historical_data(
            tradingsymbol=symbol,
            exchange=exchange,
            timeframe=timeframe,
            from_date=start_date,
            to_date=end_date,
            sector=sector or "NO",
        )
        if df is None or df.empty:
            return None
        if "timestamp" in df.columns:
            df["timestamp"] = pd.to_datetime(df["timestamp"])
        elif "date" in df.columns:
            df["timestamp"] = pd.to_datetime(df["date"])
        elif "start_Time" in df.columns:
            df["timestamp"] = pd.to_datetime(df["start_Time"])
        else:
            return None
        df = df.sort_values("timestamp").reset_index(drop=True)
        df["time"] = df["timestamp"].dt.time
        return df.reset_index(drop=True)

    # not providing exact data
    def get_Futures_historical_intraday_data(
        self,
        security_id: str,
        exchange_segment: str,
        instrument: str,
        interval: str,
        from_date: str,
        to_date: str,
        oi: bool = False,
    ):

        payload = {
            "securityId": str(security_id),
            "exchangeSegment": exchange_segment,
            "instrument": instrument,
            "interval": str(interval),
            "oi": oi,
            "fromDate": from_date,
            "toDate": to_date,
            "exchange": "NSE",
            "sector": "NO",
        }

        headers = {
            "Content-Type": "application/json",
            "access-token": os.getenv("DHAN_ACCESS_TOKEN"),
            "client-id": os.getenv("DHAN_CLIENT_CODE"),
        }

        response = requests.post(
            "https://api.dhan.co/v2/charts/intraday",
            headers=headers,
            data=json.dumps(payload),
        )

        if response.status_code != 200:
            raise Exception(f"API Error {response.status_code}: {response.text}")
        data = response.json()

        if not data or "timestamp" not in data:
            return pd.DataFrame()

        df = pd.DataFrame(
            {
                "timestamp": data["timestamp"],
                "open": data["open"],
                "high": data["high"],
                "low": data["low"],
                "close": data["close"],
                "volume": data["volume"],
            }
        )

        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="s", utc=True)
        df["timestamp"] = df["timestamp"].dt.tz_convert("Asia/Kolkata")
        pdb.set_trace()
        return df

    # -------------------------------------------------------------------------
    # Data: Expiries
    # -------------------------------------------------------------------------
    def get_live_expiry(self, symbol, exchange):
        """Live expiry list from Dhan. Returns list (format from API, typically dates/indices)."""
        return self.tsl.get_expiry_list(Underlying=symbol, exchange=exchange)

    # -------------------------------------------------------------------------
    # Data: Option chain (live)
    # -------------------------------------------------------------------------
    def get_live_option_chain(self, symbol, exchange, expiry_index, strikes_around_atm):
        """
        Engine-friendly option chain. expiry_index indexes into get_live_expiry() list.
        Returns { "symbol", "exchange", "chain": DataFrame } or None.
        """
        expiries = self.tsl.get_expiry_list(Underlying=symbol, exchange=exchange)
        if not expiries or expiry_index >= len(expiries):
            return None
        expiry = expiries[expiry_index]
        if hasattr(expiry, "strftime"):
            expiry_date = expiry
        else:
            expiry_date = pd.to_datetime(expiry)
            if hasattr(expiry_date, "date"):
                expiry_date = expiry_date.date()
            else:
                expiry_date = pd.Timestamp(expiry_date).date()
        try:
            result = self.tsl.get_option_chain(
                Underlying=symbol,
                exchange=exchange,
                expiry=expiry_date,
                num_strikes=strikes_around_atm,
            )
        except Exception:
            return None
        if result is None:
            return None
        atm_strike, df, expiry_str = result
        return {
            "symbol": symbol,
            "exchange": exchange,
            "chain": df,
            "atm_strike": atm_strike,
            "expiry": expiry_str,
        }

    # -------------------------------------------------------------------------
    # Data: Option chain (historical / expired) for backtest
    # -------------------------------------------------------------------------
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
        """Expired option data for backtest. Maps to Tradehull get_expired_option_data."""
        return self.tsl.get_expired_option_data(
            exchangeSegment=exchangeSegment,
            instrument=instrument,
            fromDate=from_date,
            toDate=to_date,
            exchange=exchange,
            interval=(
                int(interval)
                if isinstance(interval, str) and interval.isdigit()
                else interval
            ),
            securityId=securityId,
            expiry_flag=expiry_flag,
            expiry_code=int(expiry_code),
            strike=strike,
            option_type=option_type,
        )

    # -------------------------------------------------------------------------
    # Data: Strike helpers (for strategy building)
    # -------------------------------------------------------------------------
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

    def get_ltp_data(self, names, debug="NO"):
        """LTP for one or more symbols. Returns dict { symbol: values }."""
        return self.tsl.get_ltp_data(names, debug)

    def get_quote_data(self, names, debug="NO"):
        """Quote (bid/ask etc.) for symbols."""
        return self.tsl.get_quote_data(names, debug)

    # -------------------------------------------------------------------------
    # Data: NSE (historical option chain / expiries)
    # -------------------------------------------------------------------------
    def get_nse_expiries(self, symbol, year, instrument="OPTIDX"):
        key = (symbol, year, instrument)
        if key not in self.expiry_cache:
            self.expiry_cache[key] = self.nse_client.get_expiries(
                symbol, year, instrument
            )
        return self.expiry_cache[key]

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
        for strike in strikes:
            try:
                hist = self.nse_client.get_options_history(
                    symbol=symbol,
                    from_date=(
                        from_date.strftime("%Y-%m-%d")
                        if hasattr(from_date, "strftime")
                        else from_date
                    ),
                    to_date=(
                        expiry_date.strftime("%Y-%m-%d")
                        if hasattr(expiry_date, "strftime")
                        else expiry_date
                    ),
                    instrumentType=instrumentType,
                    expiry_date=(
                        expiry_date.strftime("%Y-%m-%d")
                        if hasattr(expiry_date, "strftime")
                        else str(expiry_date)
                    ),
                    strike=int(float(strike)),
                    option_type=option_type,
                    year=(
                        expiry_date.year
                        if hasattr(expiry_date, "year")
                        else pd.Timestamp(expiry_date).year
                    ),
                )
                if not hist:
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
        return {"symbol": symbol, "exchange": "OPTIDX", "chain": oc_df}

    # -------------------------------------------------------------------------
    # Orders & positions (for broker layer only)
    # -------------------------------------------------------------------------
    def get_positions(self, debug="NO"):
        return self.tsl.get_positions(debug=debug)

    def get_order_list(self):
        """Order list for idempotency / lookup. Uses Tradehull get_orderbook."""
        try:
            ob = self.tsl.get_orderbook(debug="NO")
            if ob is None:
                return []
            if isinstance(ob, pd.DataFrame):
                return ob.to_dict("records") if not ob.empty else []
            if isinstance(ob, dict) and ob.get("status") == "failure":
                return []
            if isinstance(ob, dict) and "data" in ob:
                return ob["data"] if isinstance(ob["data"], list) else []
            return []
        except Exception:
            return []

    def place_order(
        self,
        tradingsymbol,
        exchange,
        quantity,
        price=0,
        trigger_price=0,
        order_type="MARKET",
        transaction_type="BUY",
        trade_type="MARGIN",
        disclosed_quantity=0,
        after_market_order=False,
        validity="DAY",
        amo_time="OPEN",
        bo_profit_value=None,
        bo_stop_loss_value=None,
        tag=None,
    ):
        """
        Place order via Tradehull. Used only by broker layer (DhanBrokerApi).
        Returns dict with "status" ("success" | "error") and "order_id".
        """
        try:
            result = self.tsl.order_placement(
                tradingsymbol=tradingsymbol,
                exchange=exchange.upper(),
                quantity=int(quantity),
                price=int(price) if price else 0,
                trigger_price=int(trigger_price) if trigger_price else 0,
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
            if result is not None and isinstance(result, str):
                return {"status": "success", "order_id": result}
            return {"status": "error", "order_id": None}
        except Exception as e:
            print(f"place_order exception: {e}")
            return {"status": "error", "order_id": None}

    def cancel_order(self, order_id):
        """Cancel a single order."""
        return self.tsl.cancel_order(order_id)

    def get_order_detail(self, order_id, debug="NO"):
        """Single order detail."""
        return getattr(self.tsl, "get_order_detail", lambda *a, **k: None)(
            order_id, debug
        )

    def get_holdings(self, debug="NO"):
        return self.tsl.get_holdings(debug=debug)

    def get_balance(self):
        return self.tsl.get_balance()

    def get_live_pnl(self):
        return self.tsl.get_live_pnl()
