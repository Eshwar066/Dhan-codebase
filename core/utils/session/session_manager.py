import datetime as dt
import pytz

from .market_calendar import MARKET_SESSIONS
from .holidays import HOLIDAYS


class SessionManager:

    # ---------- Exchange Mapping ----------
    @staticmethod
    def normalize_exchange(exchange):
        mapping = {
            "INDEX": "NSE_INDEX",
            "NSE_EQ": "NSE",
            "NSE_FNO": "NSE",
        }
        return mapping.get(exchange, exchange)

    # ---------- Timezone ----------
    @staticmethod
    def _tz(exchange):
        exchange = SessionManager.normalize_exchange(exchange)
        tz = MARKET_SESSIONS[exchange]["timezone"]
        return pytz.timezone(tz)

    @staticmethod
    def _now(exchange):
        return dt.datetime.now(SessionManager._tz(exchange))

    # ---------- Holidays ----------
    @staticmethod
    def is_holiday(date, exchange):
        exchange = SessionManager.normalize_exchange(exchange)
        d = date.strftime("%Y-%m-%d")
        return d in HOLIDAYS.get(exchange, set())

    # ---------- Market Open ----------
    @staticmethod
    def is_market_open(exchange):
        exchange = SessionManager.normalize_exchange(exchange)

        now = SessionManager._now(exchange)

        if now.weekday() >= 5:
            return False

        if SessionManager.is_holiday(now, exchange):
            return False

        sess = MARKET_SESSIONS[exchange]["regular"]
        return sess["start"] <= now.time() <= sess["end"]

    # ---------- TF Utils ----------
    @staticmethod
    def _tf_to_minutes(tf):
        tf = str(tf).lower()

        if tf.endswith("h"):
            return int(tf[:-1]) * 60

        return int(tf)

    # ---------- Candle Close ----------
    @staticmethod
    def get_last_candle_close(exchange, timeframe):
        exchange = SessionManager.normalize_exchange(exchange)

        now = SessionManager._now(exchange)
        tf_min = SessionManager._tf_to_minutes(timeframe)

        sess = MARKET_SESSIONS[exchange]["regular"]

        session_start = now.replace(
            hour=sess["start"].hour,
            minute=sess["start"].minute,
            second=0,
            microsecond=0,
        )

        minutes_since_open = int((now - session_start).total_seconds() / 60)
        completed = minutes_since_open // tf_min

        close = session_start + dt.timedelta(minutes=completed * tf_min)

        session_end = now.replace(
            hour=sess["end"].hour,
            minute=sess["end"].minute,
            second=0,
            microsecond=0,
        )

        return min(close, session_end)

    # ---------- Next Close ----------
    @staticmethod
    def next_candle_close(exchange, timeframe):
        last = SessionManager.get_last_candle_close(exchange, timeframe)
        tf_min = SessionManager._tf_to_minutes(timeframe)
        return last + dt.timedelta(minutes=tf_min)
