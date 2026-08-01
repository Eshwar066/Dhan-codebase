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
            "DELTA": "DELTA",
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

    @staticmethod
    def is_trading_day(day, exchange="NSE_INDEX"):
        """True when ``day`` is a weekday and not an exchange holiday."""
        exchange = SessionManager.normalize_exchange(exchange)
        if isinstance(day, dt.datetime):
            d = day.date()
        else:
            d = day
        if d.weekday() >= 5:
            return False
        probe = dt.datetime.combine(d, dt.time.min)
        return not SessionManager.is_holiday(probe, exchange)

    @staticmethod
    def hedge_rollover_target_date(
        year: int,
        month: int,
        *,
        rollover_day: int = 18,
        exchange: str = "NSE_INDEX",
    ) -> dt.date:
        """
        Nominal hedge roll calendar day (default 18th), adjusted backward for
        weekends and NSE holidays — roll on the prior session if 18th is closed.
        """
        exchange = SessionManager.normalize_exchange(exchange)
        target = dt.date(int(year), int(month), int(rollover_day))
        while not SessionManager.is_trading_day(target, exchange):
            target -= dt.timedelta(days=1)
        return target

    # ---------- Market Open ----------
    @staticmethod
    def is_market_open(exchange):
        exchange = SessionManager.normalize_exchange(exchange)

        # Delta crypto perps trade 24/7 — do not apply NSE-style weekends/holidays.
        if exchange == "DELTA":
            return True

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

    @staticmethod
    def session_end_unix_for_bar(bucket_ts, exchange="NSE_INDEX"):
        """Unix timestamp of regular session end on the bar's IST calendar day."""
        exchange = SessionManager.normalize_exchange(exchange)
        sess = MARKET_SESSIONS.get(exchange, {}).get("regular")
        if not sess:
            return None
        try:
            bt = int(float(bucket_ts))
        except (TypeError, ValueError):
            return None
        tz = SessionManager._tz(exchange)
        bar_dt = dt.datetime.fromtimestamp(bt, tz)
        end_t = sess["end"]
        session_end = bar_dt.replace(
            hour=end_t.hour,
            minute=end_t.minute,
            second=end_t.second,
            microsecond=0,
        )
        return int(session_end.timestamp())

    # ---------- Next Close ----------
    @staticmethod
    def next_candle_close(exchange, timeframe):
        last = SessionManager.get_last_candle_close(exchange, timeframe)
        tf_min = SessionManager._tf_to_minutes(timeframe)
        return last + dt.timedelta(minutes=tf_min)
