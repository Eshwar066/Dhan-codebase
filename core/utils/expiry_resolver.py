import pandas as pd
import datetime as dt
import calendar
import math


class ExpiryResolver:
    """
    Resolves expiry for:
    - NSE historical (exact expiry date)
    - DHAN option chain (expiry series)
    """

    # ============================
    # PUBLIC API
    # ============================
    @staticmethod
    def resolve(expiry_list, trade_date, api="NSE", expiry_pref="MONTHLY"):
        # NSE will check later-->Pending

        if isinstance(trade_date, str):
            trade_date = pd.to_datetime(trade_date).date()
        elif isinstance(trade_date, dt.datetime):
            trade_date = trade_date.date()

        # ---------- NSE path ----------
        if api.upper() == "NSE":
            if not expiry_list:
                return None
            return ExpiryResolver._select_nse_expiry(expiry_list, trade_date)

        # ---------- DHAN path ----------
        if api.upper() == "DHAN":
            if expiry_pref == "MONTHLY":
                return ExpiryResolver._derive_monthly_series(trade_date)
            elif expiry_pref == "QUARTERLY":
                return ExpiryResolver._derive_quarterly_series(trade_date)

        raise ValueError(f"Unsupported api={api}, expiry_pref={expiry_pref}")

    # ============================
    # NSE EXPIRY (exact date)
    # ============================

    def get_otm_strikes(self, spot, option_type, step=500, count=4):
        """
        Returns nearest OTM strikes relative to spot.
        For spot = 17700, step = 500:
        CE -> [17500, 17000, 16500]
        PE -> [18000, 18500, 19000]
        """

        atm = round(spot / step) * step

        if option_type in ("CALL", "CE"):
            # OTM calls are BELOW spot
            return [atm] + [atm + (i * step) for i in range(1, count)]

        elif option_type in ("PUT", "PE"):
            # OTM puts are ABOVE spot
            return [atm] + [atm - (i * step) for i in range(1, count)]

        else:
            raise ValueError("option_type must be CALL/CE or PUT/PE")

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

    @staticmethod
    def last_thursday(year, month):
        last_day = dt.date(year, month, 1)
        if month == 12:
            last_day = dt.date(year + 1, 1, 1) - dt.timedelta(days=1)
        else:
            last_day = dt.date(year, month + 1, 1) - dt.timedelta(days=1)

        offset = (last_day.weekday() - 3) % 7
        return last_day - dt.timedelta(days=offset)

    @staticmethod
    def current_month_expiry(trade_date):
        return ExpiryResolver.last_thursday(trade_date.year, trade_date.month)

    @staticmethod
    def next_month_expiry(trade_date):
        if trade_date.month == 12:
            return ExpiryResolver.last_thursday(trade_date.year + 1, 1)
        return ExpiryResolver.last_thursday(trade_date.year, trade_date.month + 1)

    @staticmethod
    def _select_nse_expiry(expiry_list, trade_date):
        # NSE will check later-->Pending
        """
        Select last expiry of target month/year.
        """
        target_month, target_year = ExpiryResolver._select_expiry_month(trade_date)

        expiry_dates = [pd.to_datetime(e).date() for e in expiry_list]

        matches = [
            e for e in expiry_dates if e.month == target_month and e.year == target_year
        ]

        if not matches:
            return None

        # Monthly expiry = LAST one
        return matches[-1]

    # # ============================
    # # DHAN EXPIRY SERIES
    # # ============================
    # @staticmethod
    # def _derive_monthly_series(trade_date):
    #     """
    #     Decide MONTHLY vs MONTHLY_NEXT for Dhan option chain.
    #     """
    #     year = trade_date.year
    #     month = trade_date.month

    #     last_thursday = ExpiryResolver._last_thursday(year, month)

    #     # After expiry → next monthly
    #     if trade_date > last_thursday:
    #         return "MONTHLY_NEXT"

    #     return "MONTHLY"

    @staticmethod
    def _last_thursday(year, month):
        cal = calendar.monthcalendar(year, month)
        thursdays = [
            week[calendar.THURSDAY] for week in cal if week[calendar.THURSDAY] != 0
        ]
        return dt.date(year, month, thursdays[-1])

    # ============================================================================================
    # Below functions are used for Leaps RSI 53,32
    @staticmethod
    def _derive_quarterly_series(trade_date):
        """
        Quarterly expiry label (future use).
        """
        q_month, q_year = ExpiryResolver._select_expiry_month(trade_date)

        expirySeries = (q_year - trade_date.year) * 12 + (q_month - trade_date.month)
        return expirySeries

    @staticmethod
    def _select_expiry_month(trade_date):
        """
        Quarterly month selector (used by NSE & quarterly logic).
        """
        year = trade_date.year
        month = trade_date.month
        day = trade_date.day

        quarters = [3, 6, 9, 12]
        cutoffs = {2: 15, 5: 15, 8: 20, 11: 20}

        q = next((m for m in quarters if m > month), 3)
        if q == 3 and month > 9:
            year += 1

        if month in cutoffs and day > cutoffs[month]:
            q = quarters[(quarters.index(q) + 1) % 4]
            if q == 3:
                year += 1

        return q, year
