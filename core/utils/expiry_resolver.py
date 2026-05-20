import datetime as dt
import calendar
import math
from typing import Any

import pandas as pd


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
    def resolve(
        expiry_list,
        trade_date,
        api="NSE",
        expiry_pref="MONTHLY",
        *,
        dhan_calendar_rollover_day=None,
    ):
        # Normalize once to a pure date so downstream comparisons (e.g. in
        # _derive_monthly_series) never mix pd.Timestamp with datetime.date.
        trade_date = pd.Timestamp(trade_date).date()

        # ---------- NSE path ----------
        if api.upper() == "NSE":
            if not expiry_list:
                return None
            if expiry_pref == "LEAPS_ROLL":
                return ExpiryResolver._select_nse_expiry(
                    expiry_list,
                    trade_date,
                    target_month_year=ExpiryResolver._leaps_rollover_month_year(
                        trade_date
                    ),
                )
            return ExpiryResolver._select_nse_expiry(expiry_list, trade_date)

        # ---------- DHAN path ----------
        if api.upper() == "DHAN":
            if expiry_pref == "MONTHLY":
                return ExpiryResolver._derive_monthly_series(
                    trade_date, calendar_rollover_day=dhan_calendar_rollover_day
                )
            elif expiry_pref == "QUARTERLY":
                return ExpiryResolver.quarterly_target_expiry_date(trade_date)
            elif expiry_pref == "LEAPS_ROLL":
                return ExpiryResolver.leaps_rollover_target_expiry_date(trade_date)

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
    def _select_nse_expiry(expiry_list, trade_date, *, target_month_year=None):
        # NSE will check later-->Pending
        """
        Select last expiry of target month/year.
        """
        if target_month_year is None:
            target_month, target_year = ExpiryResolver._select_expiry_month(trade_date)
        else:
            target_month, target_year = target_month_year

        expiry_dates = [pd.to_datetime(e).date() for e in expiry_list]

        matches = [
            e for e in expiry_dates if e.month == target_month and e.year == target_year
        ]

        if not matches:
            return None

        # Monthly expiry = LAST one
        return matches[-1]

    @staticmethod
    def _derive_monthly_series(trade_date, calendar_rollover_day=None):
        """
        Dhan / Tradehull monthly option chain index for backtest (``expiry_code`` is int).

        ``0`` = current month's series; ``1`` = next month's series when:

        - this month's expiry Thursday has already passed, **or**
        - ``calendar_rollover_day`` is set (e.g. 15) and ``trade_date.day`` is **greater than**
          that day (intraday monthly rollover — next series from folder / chain).
        """
        this_exp = ExpiryResolver.current_month_expiry(trade_date)
        if trade_date > this_exp:
            return 1
        if (
            calendar_rollover_day is not None
            and int(calendar_rollover_day) >= 1
            and trade_date.day > int(calendar_rollover_day)
        ):
            return 1
        return 0

    @staticmethod
    def is_calendar_expiry(value: Any) -> bool:
        if value is None or isinstance(value, bool):
            return False
        if isinstance(value, (int, float)):
            try:
                import numpy as np

                if isinstance(value, np.integer):
                    return False
            except ImportError:
                pass
            return False
        if isinstance(value, (dt.date, dt.datetime)):
            return True
        if isinstance(value, str) and not str(value).strip().isdigit():
            try:
                pd.to_datetime(value)
                return True
            except (TypeError, ValueError):
                return False
        return hasattr(value, "year") and hasattr(value, "month")

    @staticmethod
    def as_calendar_date(value: Any) -> dt.date:
        if isinstance(value, dt.datetime):
            return value.date()
        if isinstance(value, dt.date):
            return value
        return pd.Timestamp(value).date()

    @staticmethod
    def index_in_expiry_list(expiries, target_date) -> int:
        """
        Index of ``target_date`` in a sorted Dhan expiry list (exact match, else nearest
        same-or-later date, else last entry).
        """
        if not expiries:
            return 0
        target = ExpiryResolver.as_calendar_date(target_date)
        parsed: list[tuple[int, dt.date]] = []
        for i, raw in enumerate(expiries):
            try:
                parsed.append((i, ExpiryResolver.as_calendar_date(raw)))
            except (TypeError, ValueError):
                continue
        if not parsed:
            return 0
        for i, d in parsed:
            if d == target:
                return i
        future = [(i, d) for i, d in parsed if d >= target]
        if future:
            return min(future, key=lambda x: x[1])[0]
        return max(parsed, key=lambda x: x[1])[0]

    @staticmethod
    def dhan_expiry_index_to_date(trade_date, expiry_index: Any):
        """
        Map DHAN ``expiry_code`` / ``ctx.selected_expiry`` to a calendar expiry date.

        - ``0`` / ``1``: front / next monthly (last Thursday)
        - ``date`` / ISO string: returned as-is
        - legacy int ``> 1``: quarterly target for ``trade_date`` (old month-offset series)
        """
        if ExpiryResolver.is_calendar_expiry(expiry_index):
            return ExpiryResolver.as_calendar_date(expiry_index)
        if isinstance(trade_date, dt.datetime):
            trade_date = trade_date.date()
        elif isinstance(trade_date, str):
            trade_date = pd.to_datetime(trade_date).date()
        idx = int(expiry_index)
        if idx <= 1:
            if idx == 0:
                return ExpiryResolver.current_month_expiry(trade_date)
            return ExpiryResolver.next_month_expiry(trade_date)
        return ExpiryResolver.quarterly_target_expiry_date(trade_date)

    @staticmethod
    def quarterly_target_expiry_date(trade_date) -> dt.date:
        """
        Legacy QUARTERLY: last Tuesday of the target quarter month from
        ``_select_expiry_month``. Prefer ``LEAPS_ROLL`` for LEAPS_RSI.
        """
        td = pd.Timestamp(trade_date).date()
        q_month, q_year = ExpiryResolver._select_expiry_month(td)
        return ExpiryResolver._last_tuesday(q_year, q_month)

    @staticmethod
    def _leaps_rollover_month_year(trade_date) -> tuple[int, int]:
        """
        LEAPS RSI monthly rollover: 1–15 vs 16–end of month maps to target expiry month.

        Jan–Dec rules per strategy spec; Nov/Dec second half and all of Dec 16–31
        can roll into Jan/Feb of the next calendar year.
        """
        td = pd.Timestamp(trade_date).date()
        month = td.month
        day = td.day
        year = td.year
        after_mid = day >= 16

        # (target if day 1–15, target if day 16–31)
        roll = {
            1: (2, 3),
            2: (3, 4),
            3: (4, 5),
            4: (5, 6),
            5: (6, 7),
            6: (7, 8),
            7: (8, 9),
            8: (9, 10),
            9: (10, 11),
            10: (11, 12),
            11: (12, 1),
            12: (1, 2),
        }
        lo, hi = roll[month]
        target_m = hi if after_mid else lo
        target_y = year
        if month >= 11 and after_mid:
            target_y = year + 1
        elif month == 12:
            target_y = year + 1
        return target_m, target_y

    @staticmethod
    def leaps_rollover_target_expiry_date(trade_date) -> dt.date:
        """
        LEAPS_RSI: last Tuesday of the rollover target month from ``_leaps_rollover_month_year``.
        """
        m, y = ExpiryResolver._leaps_rollover_month_year(trade_date)
        return ExpiryResolver._last_tuesday(y, m)

    @staticmethod
    def dhan_calendar_expiry_to_index(trade_date, calendar_expiry) -> int:
        """
        Inverse of ``dhan_expiry_index_to_date``: map a calendar expiry to DHAN ``expiry_code``
        (0/1) for the rolling option API. Used when only the instrument's expiry date is known
        (e.g. stop checks) while ``ctx.selected_expiry`` may be unset.
        """
        td = pd.Timestamp(trade_date).date()
        cal = pd.Timestamp(calendar_expiry).date()
        z = ExpiryResolver.dhan_expiry_index_to_date(td, 0)
        o = ExpiryResolver.dhan_expiry_index_to_date(td, 1)
        if cal == z:
            return 0
        if cal == o:
            return 1
        return ExpiryResolver._derive_monthly_series(td)

    @staticmethod
    def coerce_to_dhan_expiry_index(trade_date, value) -> int:
        """
        Normalize values from ``params['expiry_code']`` / ``ctx.selected_expiry`` to a DHAN
        monthly index (0/1) for expired-chain APIs. Calendar dates are mapped via
        ``dhan_calendar_expiry_to_index``; use ``dhan_expiry_index_to_date`` when you need the
        actual expiry date (including QUARTERLY).
        """
        td = pd.Timestamp(trade_date).date()
        if value is None:
            return ExpiryResolver._derive_monthly_series(td)
        if isinstance(value, bool):
            return ExpiryResolver._derive_monthly_series(td)
        if ExpiryResolver.is_calendar_expiry(value):
            return ExpiryResolver.dhan_calendar_expiry_to_index(td, value)
        if isinstance(value, (int, float)):
            idx = int(value)
            if idx > 1:
                return ExpiryResolver.dhan_calendar_expiry_to_index(
                    td, ExpiryResolver.quarterly_target_expiry_date(td)
                )
            return idx
        try:
            import numpy as np

            if isinstance(value, np.integer):
                v = int(value)
                if v > 1:
                    return ExpiryResolver.dhan_calendar_expiry_to_index(
                        td, ExpiryResolver.quarterly_target_expiry_date(td)
                    )
                return v
        except ImportError:
            pass
        return ExpiryResolver.dhan_calendar_expiry_to_index(td, value)

    @staticmethod
    def _last_thursday(year, month):
        cal = calendar.monthcalendar(year, month)
        thursdays = [
            week[calendar.THURSDAY] for week in cal if week[calendar.THURSDAY] != 0
        ]
        return dt.date(year, month, thursdays[-1])

    @staticmethod
    def _last_tuesday(year, month):
        cal = calendar.monthcalendar(year, month)
        tuesdays = [
            week[calendar.TUESDAY] for week in cal if week[calendar.TUESDAY] != 0
        ]
        return dt.date(year, month, tuesdays[-1])

    # ============================================================================================
    # Below functions are used for Leaps RSI 53,32
    @staticmethod
    def _derive_quarterly_series(trade_date):
        """
        Legacy month-offset index (deprecated for live chain fetch).

        Prefer ``quarterly_target_expiry_date`` / ``resolve(..., QUARTERLY)`` calendar dates.
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
