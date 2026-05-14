from __future__ import annotations

import datetime as dt
import json
import logging
import os
import time
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)
IST = ZoneInfo("Asia/Kolkata")


class IndicatorManager:
    """
    Shared indicator layer for live engine.

    Maintains per-(symbol,timeframe) base candle history and per-strategy enriched
    indicator state.

    Bootstrap (L2 logs → L3 API only on failure):
    - Primary: closed candles from ``*_candles.log`` under ``logs/`` (canonical OHLCV + IST bar open).
    - In-process cache: reused until the dataframe cannot satisfy a larger ``window``; no UTC-midnight invalidation.
    - ``get_intraday`` is used only when logs are missing, short, discontinuous, misaligned, or unreadable.
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
        self._startup_logged: bool = False
        self._rsi_logged_keys = set()
        self._rsi_seeded_streams = set()
        self._rsi_log_root = "logs"
        self._rsi_debug_printed = False
        # Extra bars loaded beyond strategy window for continuity / validation slack.
        self._log_bootstrap_buffer = 50

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
    def _compute_rsi_columns(df: Any, period: int = 14) -> Any:
        """Compute full RSI/prev_RSI columns for strategies that explicitly require RSI."""
        import pandas as pd

        if df is None or len(df) == 0 or "close" not in df.columns:
            return df
        try:
            p = max(1, int(period))
        except Exception:
            p = 14

        close = pd.to_numeric(df["close"], errors="coerce")
        if close.isna().all():
            return df

        try:
            import talib

            rsi = talib.RSI(close.astype(float).values, timeperiod=p)
            df["rsi"] = pd.Series(rsi, index=df.index, dtype="float64")
        except Exception:
            # Fallback to Wilder-style smoothing when TA-Lib is unavailable.
            delta = close.diff()
            gain = delta.clip(lower=0)
            loss = -delta.clip(upper=0)
            avg_gain = gain.ewm(alpha=1 / p, adjust=False).mean()
            avg_loss = loss.ewm(alpha=1 / p, adjust=False).mean()
            rs = avg_gain / avg_loss
            df["rsi"] = 100 - (100 / (1 + rs))

        df["prev_rsi"] = df["rsi"].shift(1)
        return df

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
    def _to_ist_iso(ts: Any) -> str:
        try:
            dt_ts = ts
            if not isinstance(dt_ts, dt.datetime):
                dt_ts = dt.datetime.fromisoformat(str(ts))
            if dt_ts.tzinfo is None:
                dt_ts = dt_ts.replace(tzinfo=dt.timezone.utc)
            return dt_ts.astimezone(IST).isoformat()
        except Exception:
            return ""

    def _collect_candle_closed_rows_from_logs(
        self,
        symbol_u: str,
        tf_s: str,
        ist_day: Optional[dt.date] = None,
    ) -> List[Dict[str, Any]]:
        """
        Scan ``logs/**/*.`` for ``*_candles.log`` JSON lines with event_type=candle_closed.
        When ``ist_day`` is set, only rows whose bar open falls on that IST calendar date.
        """
        rows: List[Dict[str, Any]] = []
        if not symbol_u or not tf_s:
            return rows
        try:
            logs_root = self._rsi_log_root
            if not os.path.isdir(logs_root):
                return rows
            for root, _, files in os.walk(logs_root):
                for name in files:
                    if not name.endswith("_candles.log"):
                        continue
                    path = os.path.join(root, name)
                    try:
                        with open(path, "r", encoding="utf-8") as f:
                            for line in f:
                                s = line.strip()
                                if not s:
                                    continue
                                try:
                                    payload = json.loads(s)
                                except Exception:
                                    continue
                                if str(payload.get("event_type") or "") != "candle_closed":
                                    continue
                                if str(payload.get("symbol") or "").strip().upper() != symbol_u:
                                    continue
                                if str(payload.get("timeframe") or "").strip() != tf_s:
                                    continue
                                bar_ist = payload.get("bar_timestamp_ist")
                                if not bar_ist:
                                    continue
                                try:
                                    bar_dt = dt.datetime.fromisoformat(str(bar_ist))
                                except Exception:
                                    continue
                                if bar_dt.tzinfo is None:
                                    bar_dt = bar_dt.replace(tzinfo=IST)
                                bar_dt = bar_dt.astimezone(IST)
                                if ist_day is not None and bar_dt.date() != ist_day:
                                    continue
                                rows.append(
                                    {
                                        "timestamp": bar_dt.astimezone(dt.timezone.utc),
                                        "open": payload.get("open"),
                                        "high": payload.get("high"),
                                        "low": payload.get("low"),
                                        "close": payload.get("close"),
                                        "volume": payload.get("volume", 0),
                                        "symbol": symbol_u,
                                        "exchange": payload.get("exchange"),
                                    }
                                )
                    except Exception:
                        continue
        except Exception:
            return rows
        return rows

    def _candle_rows_to_sorted_df(self, rows: List[Dict[str, Any]], symbol: str) -> Any:
        import pandas as pd

        if not rows:
            return pd.DataFrame()
        out = pd.DataFrame(rows)
        out["timestamp"] = pd.to_datetime(out["timestamp"], utc=True, errors="coerce")
        out = out.dropna(subset=["timestamp"]).sort_values("timestamp")
        out = out.drop_duplicates(subset=["timestamp"], keep="last").reset_index(drop=True)
        if "symbol" in out.columns and out["symbol"].isna().all():
            out["symbol"] = symbol
        return out

    def _load_candles_from_logs(self, symbol: str, tf: str, tail_rows: int) -> Any:
        """Load the most recent ``tail_rows`` closed candles for symbol|timeframe from disk logs."""
        import pandas as pd

        symbol_u = str(symbol or "").strip().upper()
        tf_s = str(tf or "").strip()
        rows = self._collect_candle_closed_rows_from_logs(symbol_u, tf_s, ist_day=None)
        out = self._candle_rows_to_sorted_df(rows, symbol)
        if out is None or len(out) == 0:
            return pd.DataFrame()
        if len(out) > tail_rows:
            out = out.iloc[-tail_rows:].reset_index(drop=True)
        return out

    def _validate_log_candles(
        self,
        df: Any,
        tf: str,
        exchange: str,
        min_rows: int,
    ) -> Tuple[bool, str]:
        import pandas as pd

        if df is None or len(df) < min_rows:
            return False, "insufficient_bars"
        if "timestamp" not in df.columns:
            return False, "no_timestamp_column"
        tss = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
        if bool(tss.isna().any()):
            return False, "invalid_timestamps"
        if not bool(tss.is_monotonic_increasing):
            return False, "timestamps_not_sorted"
        if len(tss) != len(tss.unique()):
            return False, "duplicate_timestamps"

        tf_sec = float(self._timeframe_to_seconds(tf))
        exu = str(exchange or "").upper()
        strict_nse_index_session = tf_sec == 3600.0 and exu in ("INDEX", "NSE_INDEX", "NSE")
        if strict_nse_index_session:
            for idx, ts in enumerate(tss):
                if pd.isna(ts):
                    return False, "na_timestamp"
                ist = pd.Timestamp(ts).tz_convert(IST)
                if int(ist.minute) != 15 or int(ist.hour) < 9 or int(ist.hour) > 15:
                    return False, f"nse_index_1h_bar_open idx={idx} ist={ist.isoformat()}"

        tol = 120.0
        for i in range(len(tss) - 1):
            t1 = tss.iloc[i]
            t2 = tss.iloc[i + 1]
            delta = float((t2 - t1).total_seconds())
            if delta <= 0:
                return False, f"non_positive_delta row={i}"
            d1 = pd.Timestamp(t1).tz_convert(IST).date()
            d2 = pd.Timestamp(t2).tz_convert(IST).date()
            if abs(delta - tf_sec) <= tol:
                continue
            if d1 == d2:
                if strict_nse_index_session and delta > tf_sec * 1.5 and delta < 48 * 3600:
                    return False, f"intra_session_gap row={i} delta_sec={delta:.0f}"
                if delta < tf_sec - tol:
                    return False, f"sub_tf_delta row={i} delta_sec={delta:.0f}"
            else:
                if delta < tf_sec - tol:
                    return False, f"cross_day_short_delta row={i} delta_sec={delta:.0f}"
        return True, ""

    def _append_rsi_history_log(
        self,
        strategy_id: str,
        symbol: str,
        tf: str,
        df: Any,
    ) -> None:
        if df is None or len(df) == 0:
            return
        if "timestamp" not in df.columns or "rsi" not in df.columns:
            return

        strategy_dir = str(strategy_id or "GLOBAL").strip() or "GLOBAL"
        log_dir = os.path.join(self._rsi_log_root, strategy_dir)
        os.makedirs(log_dir, exist_ok=True)
        path = os.path.join(log_dir, f"{strategy_dir}_rsi_history.log")
        stream_key = (strategy_id, symbol, tf)
        seeded = stream_key in self._rsi_seeded_streams
        rows = [df.iloc[-1]] if seeded else [r for _, r in df.iterrows()]

        for row in rows:
            ts = row.get("timestamp")
            if ts is None:
                continue

            if hasattr(ts, "to_pydatetime"):
                ts = ts.to_pydatetime()

            ist_ts = self._to_ist_iso(ts)

            if not ist_ts:
                continue

            # remove seconds and timezone
            ist_ts = dt.datetime.fromisoformat(ist_ts).strftime("%Y-%m-%d %H:%M")

            source = "live_append" if seeded else "historical_seed"
            key = (strategy_id, symbol, tf, ist_ts, source)

            if key in self._rsi_logged_keys:
                continue
            self._rsi_logged_keys.add(key)
            payload = {
                # "strategy_id": strategy_id,
                "symbol": symbol,
                "timeframe": tf,
                "source": source,
                "candle_timestamp_ist": ist_ts,
                # "open": row.get("open"),
                # "high": row.get("high"),
                # "low": row.get("low"),
                "close": row.get("close"),
                "rsi": row.get("rsi"),
                "prev_rsi": row.get("prev_rsi"),
            }
            try:
                with open(path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(payload, default=str) + "\n")
            except Exception:
                logger.exception("Failed writing RSI history log: %s", path)
                return
        self._rsi_seeded_streams.add(stream_key)

    def _load_today_live_candles(self, symbol: str, tf: str) -> Any:
        import pandas as pd

        symbol_u = str(symbol or "").strip().upper()
        tf_s = str(tf or "").strip()
        if not symbol_u or not tf_s:
            return pd.DataFrame()
        ist_today = dt.datetime.now(IST).date()
        rows = self._collect_candle_closed_rows_from_logs(symbol_u, tf_s, ist_day=ist_today)
        return self._candle_rows_to_sorted_df(rows, symbol)

    def _merge_today_live_candles(self, df: Any, symbol: str, tf: str) -> Any:
        import pandas as pd

        if df is None or len(df) == 0 or "timestamp" not in df.columns:
            return df
        live_df = self._load_today_live_candles(symbol, tf)
        if live_df is None or len(live_df) == 0:
            return df

        hist = df.copy()
        hist["timestamp"] = pd.to_datetime(hist["timestamp"], utc=True, errors="coerce")
        hist = hist.dropna(subset=["timestamp"])

        # Live closed-candle log is source of truth for current-day candles.
        merged = hist.set_index("timestamp")
        live = live_df.set_index("timestamp")
        merged.update(live)
        live_only = live.loc[~live.index.isin(merged.index)]
        if len(live_only) > 0:
            merged = pd.concat([merged, live_only], axis=0)
        merged = merged.reset_index().sort_values("timestamp")
        merged = merged.drop_duplicates(subset=["timestamp"], keep="last").reset_index(drop=True)
        return merged

    def _bootstrap_base_candle_state(
        self, symbol: str, tf: str, exchange: str, sector: str, window: int
    ) -> Dict[str, Any]:
        import pandas as pd

        def _to_business_day(d: dt.date) -> dt.date:
            while d.weekday() >= 5:
                d -= dt.timedelta(days=1)
            return d

        key = self._key_symbol_tf(symbol, tf)
        state = self._base_candle_state.get(key)
        if state:
            df0 = state.get("df")
            prev_w = int(state.get("window") or 0)
            if (
                df0 is not None
                and len(df0) > 0
                and len(df0) >= window
                and prev_w >= window
            ):
                return state

        buf = max(10, int(self._log_bootstrap_buffer))
        need_tail = window + buf
        df_log = self._load_candles_from_logs(symbol, tf, need_tail)
        source = ""
        df: Any = None

        if len(df_log) > 0:
            ok, reason = self._validate_log_candles(df_log, tf, exchange, window)
            if ok:
                df = df_log.copy()
                source = "log"
            else:
                logger.info(
                    "BOOTSTRAP_LOG_REJECT symbol=%s tf=%s exchange=%s reason=%s rows=%s need=%s",
                    symbol,
                    tf,
                    exchange,
                    reason,
                    len(df_log),
                    window,
                )

        if df is None:
            ist_today = dt.datetime.now(IST).date()
            end_business_day = _to_business_day(ist_today)
            start_business_day = _to_business_day(end_business_day - dt.timedelta(days=20))
            start_date = start_business_day.strftime("%Y-%m-%d")
            end_date = end_business_day.strftime("%Y-%m-%d")
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
            source = "api"
            if df is not None and len(df) > 0:
                df = df.copy()

        if df is None or len(df) == 0:
            empty: Dict[str, Any] = {
                "df": pd.DataFrame(),
                "last_bucket": None,
                "window": window,
                "bootstrap_source": "none",
                "bootstrap_source_detail": "log_invalid_or_missing_and_api_empty",
                "update_seq": 0,
            }
            self._base_candle_state[key] = empty
            return empty

        if "timestamp" in df.columns:
            df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
            df = df.dropna(subset=["timestamp"]).reset_index(drop=True)
        df = self._merge_today_live_candles(df, symbol, tf)
        if "symbol" not in df.columns:
            df["symbol"] = symbol
        if "exchange" not in df.columns:
            df["exchange"] = exchange
        if len(df) > window:
            df = df.iloc[-window:].reset_index(drop=True)

        boot_ist = dt.datetime.now(IST).isoformat()
        new_state: Dict[str, Any] = {
            "df": df,
            "last_bucket": None,
            "window": window,
            "bootstrap_source": source,
            "bootstrap_at_ist": boot_ist,
            "update_seq": 0,
        }
        self._base_candle_state[key] = new_state
        if source == "log":
            logger.info(
                "BOOTSTRAP_PRIMARY_LOG symbol=%s tf=%s rows=%s window=%s",
                symbol,
                tf,
                len(df),
                window,
            )
        return new_state

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
            # Canonicalize live candle time to bar-open timestamp for continuity checks.
            # Prefer bucket_ts (seconds since epoch, bar start), then fallback to candle timestamp.
            row_ts = pd.NaT
            if bucket is not None:
                row_ts = pd.to_datetime(bucket, unit="s", utc=True, errors="coerce")
            if pd.isna(row_ts):
                row_ts = pd.to_datetime(candle.get("timestamp"), utc=True, errors="coerce")
            row = {
                "timestamp": row_ts,
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
                # Reject stale live candle older than history.
                if not pd.isna(last_hist_ts) and row_ts < last_hist_ts:
                    base_state["last_bucket"] = bucket
                    return dict(candle)
                # If candle timestamp matches last history row, replace last row with live OHLC.
                # This keeps continuity and fixes close/RSI drift on boundary buckets.
                if not pd.isna(last_hist_ts) and last_hist_ts == row_ts:
                    last_idx = base_df.index[-1]
                    for col, value in row.items():
                        base_df.at[last_idx, col] = value
                    base_state["df"] = base_df
                    base_state["last_bucket"] = bucket
                    base_state["update_seq"] = int(base_state.get("update_seq", 0)) + 1
                else:
                    # One-shot continuity validation between bootstrap history and first live append.
                    if not base_state.get("continuity_checked", False):
                        if not pd.isna(last_hist_ts):
                            tf_secs = self._timeframe_to_seconds(tf)
                            gap = (row_ts - last_hist_ts).total_seconds()
                            if not self._startup_logged:
                                logger.info(
                                    "STARTUP_CONTINUITY_STATE symbol=%s tf=%s last_hist_ts=%s first_live_ts=%s tf_sec=%s bucket_alignment=%.1f",
                                    symbol,
                                    tf,
                                    str(last_hist_ts),
                                    str(row_ts),
                                    tf_secs,
                                    float(gap),
                                )
                                self._startup_logged = True
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
                    base_state["update_seq"] = int(base_state.get("update_seq", 0)) + 1
            else:
                base_df = pd.concat([base_df, pd.DataFrame([row])], ignore_index=True)
                if len(base_df) > int(base_state.get("window") or window):
                    base_df = base_df.iloc[-int(base_state.get("window") or window) :].reset_index(drop=True)
                base_state["df"] = base_df
                base_state["last_bucket"] = bucket
                base_state["continuity_checked"] = True
                base_state["update_seq"] = int(base_state.get("update_seq", 0)) + 1

        strategy_key = self._key_strategy_symbol_tf(strategy, symbol, tf)
        strategy_state = self._strategy_indicator_state.get(strategy_key)
        base_df_for_sig = base_state.get("df")
        base_last_ts = None
        if base_df_for_sig is not None and len(base_df_for_sig) > 0 and "timestamp" in base_df_for_sig.columns:
            base_last_ts = base_df_for_sig.iloc[-1].get("timestamp")
        base_sig = (
            base_state.get("last_bucket"),
            base_last_ts,
            int(base_state.get("update_seq", 0)),
        )
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
                # Enforce clean monotonic sequence before RSI computation.
                df = (
                    df.sort_values("timestamp")
                    .drop_duplicates(subset=["timestamp"])
                    .reset_index(drop=True)
                )
                period = getattr(strategy, "rsi_period", 14)
                df = self._compute_rsi_columns(df, period=period)
                if not self._rsi_debug_printed:
                    try:
                        dbg = df.tail(20).copy()
                        dbg["timestamp_ist"] = dbg["timestamp"].apply(self._to_ist_iso)
                        print(dbg[["timestamp_ist", "close", "rsi", "prev_rsi"]])
                    except Exception:
                        pass
                    self._rsi_debug_printed = True
                self._append_rsi_history_log(
                    strategy_id=str(getattr(strategy, "name", "unknown_strategy")),
                    symbol=symbol,
                    tf=tf,
                    df=df,
                )
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

