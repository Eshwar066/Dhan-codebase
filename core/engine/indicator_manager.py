from __future__ import annotations

import datetime as dt
import logging
import time
from typing import Any, Dict

logger = logging.getLogger(__name__)


class IndicatorManager:
    """
    Shared indicator layer for live engine.

    Maintains per-(symbol,timeframe) base candle history and per-strategy enriched
    indicator state. History fetch is done once per symbol/timeframe per day and
    reused across strategies.
    """

    def __init__(self, data_provider: Any, engine_logger: Any = None):
        self.data = data_provider
        self.engine_logger = engine_logger
        self._live_exchange = "INDEX"
        self._live_sector = "NO"
        self._base_candle_state: Dict[str, Dict[str, Any]] = {}
        self._strategy_indicator_state: Dict[str, Dict[str, Any]] = {}
        # Optional shared indicator cache for explicitly compatible strategies.
        # key: (symbol, timeframe, shared_signature, base_sig)
        self._indicator_cache: Dict[Any, Any] = {}

    def set_runtime_context(self, exchange: str, sector: str) -> None:
        self._live_exchange = str(exchange or "INDEX")
        self._live_sector = str(sector or "NO")

    @staticmethod
    def _key_symbol_tf(symbol: str, tf: str) -> str:
        return f"{symbol}|{tf}"

    @staticmethod
    def _key_strategy_symbol_tf(strategy: Any, symbol: str, tf: str) -> str:
        strategy_id = str(getattr(strategy, "name", "unknown_strategy"))
        return f"{strategy_id}|{symbol}|{tf}"

    @staticmethod
    def _strategy_requires_rsi(strategy: Any) -> bool:
        fn = getattr(strategy, "requires_live_rsi_patch", None)
        if not callable(fn):
            return False
        try:
            return bool(fn())
        except Exception:
            return False

    @staticmethod
    def _timeframe_to_seconds(tf: str) -> int:
        raw = str(tf or "").strip().lower()
        if not raw:
            return 60
        try:
            return max(60, int(raw) * 60)
        except Exception:
            pass
        if raw.endswith("m"):
            try:
                return max(60, int(raw[:-1]) * 60)
            except Exception:
                return 60
        if raw.endswith("h"):
            try:
                return max(60, int(raw[:-1]) * 3600)
            except Exception:
                return 3600
        return 60

    @staticmethod
    def _shared_indicator_signature(strategy: Any) -> str:
        """
        Return a stable signature only when strategy explicitly opts into
        cross-strategy indicator sharing.
        """
        fn = getattr(strategy, "shared_indicator_signature", None)
        if callable(fn):
            try:
                value = str(fn() or "").strip()
                if value:
                    return value
            except Exception:
                return ""
        return ""

    @staticmethod
    def indicator_window_size(strategy: Any) -> int:
        warmup = 0
        try:
            warmup = int(getattr(strategy, "get_warmup_period", lambda: 0)() or 0)
        except Exception:
            warmup = 0
        return max(150, warmup + 50)

    @staticmethod
    def compute_live_rsi_if_missing(df: Any, period: int = 14) -> Any:
        """
        Fallback patch only for the last row when RSI is missing/NaN.
        Never rewrites an existing valid RSI series.
        """
        import pandas as pd

        if df is None or len(df) == 0:
            return df
        if "close" not in df.columns:
            return df
        try:
            p = max(1, int(period))
        except Exception:
            p = 14

        last_idx = df.index[-1]
        has_rsi_col = "rsi" in df.columns
        if has_rsi_col and not pd.isna(df.at[last_idx, "rsi"]):
            return df
        if len(df) < p + 1:
            return df

        close = pd.to_numeric(df["close"], errors="coerce")
        if close.iloc[-(p + 1) :].isna().any():
            return df

        window = close.iloc[-(p + 1) :]
        delta = window.diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)
        avg_gain = gain.iloc[1:].mean()
        avg_loss = loss.iloc[1:].mean()
        rs = float("inf") if avg_loss == 0 else (avg_gain / avg_loss)
        rsi_last = 100 - (100 / (1 + rs))
        df.at[last_idx, "rsi"] = float(rsi_last)

        if "prev_rsi" in df.columns:
            prev_val = float("nan")
            if len(df) >= p + 2:
                prev_window = close.iloc[-(p + 2) : -1]
                if len(prev_window) == p + 1 and not prev_window.isna().any():
                    prev_delta = prev_window.diff()
                    prev_gain = prev_delta.clip(lower=0)
                    prev_loss = -prev_delta.clip(upper=0)
                    prev_avg_gain = prev_gain.iloc[1:].mean()
                    prev_avg_loss = prev_loss.iloc[1:].mean()
                    prev_rs = (
                        float("inf")
                        if prev_avg_loss == 0
                        else (prev_avg_gain / prev_avg_loss)
                    )
                    prev_val = 100 - (100 / (1 + prev_rs))
            elif has_rsi_col and len(df) >= 2:
                prev_val = df.iloc[-2].get("rsi", float("nan"))
            df.at[last_idx, "prev_rsi"] = float(prev_val)

        return df

    def _bootstrap_base_candle_state(
        self, symbol: str, tf: str, exchange: str, sector: str, window: int
    ) -> Dict[str, Any]:
        import pandas as pd

        
        def _to_business_day(d: dt.date) -> dt.date:
            # Move Sat/Sun to previous Friday so history requests stay on trading days.
            while d.weekday() >= 5:
                d -= dt.timedelta(days=1)
            return d

        key = self._key_symbol_tf(symbol, tf)
        state = self._base_candle_state.get(key)
        today = dt.datetime.utcnow().date().isoformat()
        if state and state.get("date") == today:
            return state

        utc_today = dt.datetime.utcnow().date()
        end_business_day = _to_business_day(utc_today)
        start_business_day = _to_business_day(end_business_day - dt.timedelta(days=365))
        start_date = start_business_day.strftime("%Y-%m-%d")
        end_date = end_business_day.strftime("%Y-%m-%d")
        df = None
        try:
            df = self.data.get_intraday(
                symbol=symbol,
                start_date=start_date,
                end_date=end_date,
                timeframe=tf,
                exchange=exchange,
                sector=sector,
            )
        except Exception:
            df = None

        if df is None or len(df) == 0:
            state = {
                "date": today,
                "df": pd.DataFrame(),
                "last_bucket": None,
                "window": window,
            }
            self._base_candle_state[key] = state
            return state

        df = df.copy()
        if "timestamp" in df.columns:
            df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
            df = df.dropna(subset=["timestamp"]).reset_index(drop=True)
        if "symbol" not in df.columns:
            df["symbol"] = symbol
        if "exchange" not in df.columns:
            df["exchange"] = exchange
        if len(df) > window:
            df = df.iloc[-window:].reset_index(drop=True)

        state = {
            "date": today,
            "df": df,
            "last_bucket": None,
            "window": window,
        }
        self._base_candle_state[key] = state
        return state

    def enrich_candle_for_strategy(self, strategy: Any, candle: Dict[str, Any], candle_bucket_fn: Any) -> Dict[str, Any]:
        import pandas as pd

        tf = str(getattr(strategy, "timeframe", "") or "")
        if not tf:
            return dict(candle)

        symbol = str(candle.get("symbol") or "")
        if not symbol:
            return dict(candle)

        exchange = str(candle.get("exchange") or self._live_exchange or "INDEX")
        sector = str(self._live_sector or "NO")
        window = self.indicator_window_size(strategy)
        base_state = self._bootstrap_base_candle_state(symbol, tf, exchange, sector, window)
        base_df = base_state.get("df")
        if base_df is None:
            return dict(candle)

        bucket = candle.get("bucket_ts")
        if bucket is None:
            bucket = candle_bucket_fn(candle)
        if bucket is not None and base_state.get("last_bucket") != bucket:
            row = {
                "timestamp": pd.to_datetime(candle.get("timestamp"), utc=True, errors="coerce"),
                "open": candle.get("open"),
                "high": candle.get("high"),
                "low": candle.get("low"),
                "close": candle.get("close"),
                "volume": candle.get("volume", 0),
                "symbol": symbol,
                "exchange": exchange,
            }
            row_ts = row.get("timestamp")
            if pd.isna(row_ts):
                return dict(candle)

            if len(base_df) > 0 and "timestamp" in base_df.columns:
                last_hist_ts = pd.to_datetime(base_df.iloc[-1].get("timestamp"), utc=True, errors="coerce")
                # Detect duplicated append attempts from replay/re-entrant paths.
                if not pd.isna(last_hist_ts) and last_hist_ts == row_ts:
                    base_state["last_bucket"] = bucket
                else:
                    # One-shot continuity validation between bootstrap history and first live append.
                    if not base_state.get("continuity_checked", False):
                        if not pd.isna(last_hist_ts):
                            tf_secs = self._timeframe_to_seconds(tf)
                            gap = (row_ts - last_hist_ts).total_seconds()
                            if gap <= 0 or gap > (tf_secs * 3):
                                logger.warning(
                                    "Indicator continuity mismatch: symbol=%s tf=%s last_hist=%s first_live=%s gap_sec=%.1f",
                                    symbol,
                                    tf,
                                    str(last_hist_ts),
                                    str(row_ts),
                                    float(gap),
                                )
                        base_state["continuity_checked"] = True

                    base_df = pd.concat([base_df, pd.DataFrame([row])], ignore_index=True)
                    if len(base_df) > int(base_state.get("window") or window):
                        base_df = base_df.iloc[-int(base_state.get("window") or window) :].reset_index(drop=True)
                    base_state["df"] = base_df
                    base_state["last_bucket"] = bucket
            else:
                base_df = pd.concat([base_df, pd.DataFrame([row])], ignore_index=True)
                if len(base_df) > int(base_state.get("window") or window):
                    base_df = base_df.iloc[-int(base_state.get("window") or window) :].reset_index(drop=True)
                base_state["df"] = base_df
                base_state["last_bucket"] = bucket
                base_state["continuity_checked"] = True

        strategy_key = self._key_strategy_symbol_tf(strategy, symbol, tf)
        strategy_state = self._strategy_indicator_state.get(strategy_key)
        base_df_for_sig = base_state.get("df")
        base_last_ts = None
        if base_df_for_sig is not None and len(base_df_for_sig) > 0 and "timestamp" in base_df_for_sig.columns:
            base_last_ts = base_df_for_sig.iloc[-1].get("timestamp")
        base_sig = (base_state.get("last_bucket"), base_last_ts)
        if strategy_state is None or strategy_state.get("base_sig") != base_sig:
            df = base_state.get("df")
            if df is None or len(df) == 0:
                return dict(candle)
            df = df.copy()
            shared_sig = self._shared_indicator_signature(strategy)
            cache_key = (symbol, tf, shared_sig, base_sig) if shared_sig else None
            cache_hit = False
            if cache_key is not None:
                cached_df = self._indicator_cache.get(cache_key)
                if cached_df is not None:
                    df = cached_df.copy()
                    cache_hit = True

            if not cache_hit:
                compute_start = time.time()
                try:
                    df = strategy.prepare_indicators(df)
                except Exception:
                    pass
                compute_ms = (time.time() - compute_start) * 1000.0
                if self.engine_logger:
                    try:
                        self.engine_logger.latency(
                            event_type="indicator_compute",
                            indicator_compute_ms=compute_ms,
                            strategy_id=str(getattr(strategy, "name", "unknown_strategy")),
                            symbol=symbol,
                            timeframe=tf,
                            indicator_cache_hit=False,
                        )
                    except Exception:
                        pass
                if cache_key is not None:
                    self._indicator_cache[cache_key] = df.copy()
            elif self.engine_logger:
                try:
                    self.engine_logger.latency(
                        event_type="indicator_compute",
                        indicator_compute_ms=0.0,
                        strategy_id=str(getattr(strategy, "name", "unknown_strategy")),
                        symbol=symbol,
                        timeframe=tf,
                        indicator_cache_hit=True,
                    )
                except Exception:
                    pass
            if self._strategy_requires_rsi(strategy):
                df = self.compute_live_rsi_if_missing(df)
            strategy_state = {"df": df, "base_sig": base_sig}
            self._strategy_indicator_state[strategy_key] = strategy_state

        df = strategy_state.get("df")
        out = dict(candle)
        if df is None or len(df) == 0:
            return out

        warmup = 0
        try:
            warmup = int(getattr(strategy, "get_warmup_period", lambda: 0)() or 0)
        except Exception:
            warmup = 0
        if len(df) <= warmup:
            return out

        latest = df.iloc[-1].to_dict()
        for k, v in latest.items():
            if k in ("symbol", "exchange"):
                continue
            out[k] = v
        return out

