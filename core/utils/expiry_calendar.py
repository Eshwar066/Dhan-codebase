import pandas as pd
import pdb
from pandas.tseries.offsets import WeekOfMonth


class Expiry_Calendar:
    holiday_list = [
        "2020-01-26",
        "2020-03-10",
        "2020-03-25",
        "2020-08-15",
        "2020-10-02",
        "2020-10-25",
        "2020-11-14",
        "2020-12-25",
        "2021-01-26",
        "2021-03-11",
        "2021-04-02",
        "2021-08-15",
        "2021-10-15",
        "2021-10-19",
        "2021-10-20",
        "2021-11-04",
        "2021-12-25",
        "2022-01-26",
        "2022-03-01",
        "2022-03-18",
        "2022-04-14",
        "2022-08-15",
        "2022-10-05",
        "2022-10-24",
        "2022-12-25",
        "2023-01-26",
        "2023-03-08",
        "2023-03-25",
        "2023-04-07",
        "2023-05-01",
        "2023-08-15",
        "2023-10-24",
        "2023-11-14",
        "2023-11-27",
        "2023-12-25",
        "2024-01-22",
        "2024-01-26",
        "2024-03-08",
        "2024-03-25",
        "2024-03-29",
        "2024-04-17",
        "2024-05-20",
        "2024-08-15",
        "2024-10-02",
        "2024-11-01",
        "2024-12-25",
        "2025-01-26",
        "2025-02-26",
        "2025-03-14",
        "2025-03-31",
        "2025-04-10",
        "2025-04-14",
        "2025-04-18",
        "2025-05-01",
        "2025-08-15",
        "2025-08-27",
        "2025-10-02",
        "2025-10-21",
        "2025-10-22",
        "2025-11-05",
        "2025-12-25",
        "2026-01-15",
        "2026-01-26",
        "2026-03-03",
        "2026-03-26",
        "2026-03-31",
        "2026-04-03",
        "2026-04-14",
        "2026-05-01",
        "2026-05-28",
        "2026-06-26",
        "2026-09-14",
        "2026-10-02",
        "2026-10-20",
        "2026-11-10",
        "2026-11-24",
        "2026-12-25",
    ]

    expiry_list = [
        "2020-01-30",
        "2020-02-27",
        "2020-03-26",
        "2020-04-30",
        "2020-05-28",
        "2020-06-25",
        "2020-07-30",
        "2020-08-27",
        "2020-09-24",
        "2020-10-29",
        "2020-11-26",
        "2020-12-31",
        "2021-01-28",
        "2021-02-25",
        "2021-03-25",
        "2021-04-29",
        "2021-05-27",
        "2021-06-24",
        "2021-07-29",
        "2021-08-26",
        "2021-09-30",
        "2021-10-28",
        "2021-11-25",
        "2021-12-30",
        "2022-01-27",
        "2022-02-24",
        "2022-03-31",
        "2022-04-28",
        "2022-05-26",
        "2022-06-30",
        "2022-07-28",
        "2022-08-25",
        "2022-09-29",
        "2022-10-27",
        "2022-11-24",
        "2022-12-29",
        "2023-01-26",
        "2023-02-23",
        "2023-03-29",  # shifted due to Ram Navami on 30th
        "2023-04-27",
        "2023-05-25",
        "2023-06-29",
        "2023-07-27",
        "2023-08-31",
        "2023-09-28",
        "2023-10-26",
        "2023-11-30",
        "2023-12-28",
        "2024-01-25",
        "2024-02-29",
        "2024-03-28",
        "2024-04-25",
        "2024-05-30",
        "2024-06-27",
        "2024-07-25",
        "2024-08-29",
        "2024-09-26",
        "2024-10-31",
        "2024-11-28",
        "2024-12-26",
        "2025-01-27",  # last Monday
        "2025-02-24",
        "2025-03-31",
        "2025-04-28",  # April last Monday
        "2025-05-26",
        "2025-06-30",
        "2025-07-28",
        "2025-08-25",
        "2025-09-29",
        "2025-10-27",
        "2025-11-24",
        "2025-12-29",
        "2026-01-26",  # last Monday/Tuesday regime pending but using Monday logic
        "2026-02-23",
        "2026-03-30",
        "2026-04-27",
        "2026-05-25",
        "2026-06-29",
        "2026-07-27",
        "2026-08-31",
        "2026-09-28",
        "2026-10-26",
        "2026-11-30",
        "2026-12-28",
    ]

    @staticmethod
    def get_monthly_expiry(year, month, holidays=holiday_list):

        MONTH_MAP = {
            "JANUARY": 1,
            "FEBRUARY": 2,
            "MARCH": 3,
            "APRIL": 4,
            "MAY": 5,
            "JUNE": 6,
            "JULY": 7,
            "AUGUST": 8,
            "SEPTEMBER": 9,
            "OCTOBER": 10,
            "NOVEMBER": 11,
            "DECEMBER": 12,
        }
        # 🔒 Normalize month
        if isinstance(month, str):
            month = MONTH_MAP[month.upper()]

        # Last calendar day of month
        expiry = pd.Timestamp(year, month, 1) + pd.offsets.MonthEnd(0)

        holiday_dates = set(pd.to_datetime(holidays).date)

        # Move back to last Thursday
        while expiry.weekday() != 3:  # Thursday
            expiry -= pd.Timedelta(days=1)

        # Adjust for holidays / weekends
        while expiry.date() in holiday_dates or expiry.weekday() >= 5:
            expiry -= pd.Timedelta(days=1)

        # ✅ Return in required format
        return expiry.strftime("%Y-%m-%d")

    def get_weekly_expiry(date, holidays=holiday_list):
        expiry = date + pd.offsets.Week(weekday=3)  # Thursday
        while expiry.date() in holidays:
            expiry -= pd.Timedelta(days=1)
        return expiry.date()

    def select_expiryMonth(trade_date):
        year = trade_date.year
        month = trade_date.month
        day = trade_date.day

        # Default: same year
        expiry_year = year

        if month == 1:
            expiry_month = "MARCH"

        elif month == 2:
            expiry_month = "MARCH" if day <= 15 else "JUNE"

        elif month == 3:
            expiry_month = "JUNE"

        elif month == 4:
            expiry_month = "JUNE"

        elif month == 5:
            expiry_month = "JUNE" if day <= 15 else "SEPTEMBER"

        elif month == 6:
            expiry_month = "SEPTEMBER"

        elif month == 7:
            expiry_month = "SEPTEMBER"

        elif month == 8:
            expiry_month = "SEPTEMBER" if day <= 20 else "DECEMBER"

        elif month == 9:
            expiry_month = "DECEMBER"

        elif month == 10:
            expiry_month = "DECEMBER"

        elif month == 11:
            if day <= 20:
                expiry_month = "DECEMBER"
            else:
                expiry_month = "MARCH"
                expiry_year += 1  # 🔥 next year

        elif month == 12:
            expiry_month = "MARCH"
            expiry_year += 1  # 🔥 next year

        return expiry_month, expiry_year
