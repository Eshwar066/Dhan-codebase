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

try:
    from core.utils.json_numeric import round_json_floats
except ImportError:
    round_json_floats = None  # type: ignore

from core.utils import indicator_history as ind_hist


class IndicatorManager:
    """
    Shared indicator layer for live engine.

    Maintains per-(symbol,timeframe) base candle history and per-strategy enriched
    indicator state.

    Bootstrap (L2 candles log → L2b RSI history → L3 API):
    - Primary: closed candles from ``logs/{strategy}/{engine_id}_candles.log`` (single append-only file).
    - Secondary: ``logs/indicators/{symbol}/{tf}/indicator_history.jsonl`` (and legacy
      ``{strategy}_rsi_history.log``) when the candle log is short.
    - ``get_intraday`` only when both logs are missing or insufficient; same-day API rows are stripped
      so today's OHLC comes only from closed ``*_candles.log`` lines.
    - RSI history on disk is treated as already seeded on restart (append-only ``live_append``).
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
        self._rsi_session_hydrated: set = set()
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
    def _strategy_persisted_indicator_keys(strategy: Any) -> List[str]:
        fn = getattr(strategy, "persisted_indicator_keys", None)
        if callable(fn):
            try:
                keys = list(fn() or [])
                return [str(k) for k in keys if k]
            except Exception:
                return []
        return []

    @classmethod
    def _strategy_uses_indicator_history(cls, strategy: Any) -> bool:
        return bool(cls._strategy_persisted_indicator_keys(strategy)) or cls._strategy_requires_rsi(
            strategy
        )

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

    @staticmethod
    def _safe_strategy_dir(strategy_id: str) -> str:
        raw = str(strategy_id or "GLOBAL").strip() or "GLOBAL"
        return raw.replace("/", "_").replace("\\", "_").replace(" ", "_")

    @staticmethod
    def _is_candles_log_filename(name: str) -> bool:
        """Single append-only ``{engine_id}_candles.log`` (excludes old ``*.log.YYYY-MM-DD`` rotators)."""
        return name.endswith("_candles.log") and "_candles.log." not in name

    def _list_candles_log_paths(self, strategy_id: Optional[str] = None) -> List[str]:
        logs_root = self._rsi_log_root
        paths: List[str] = []
        if strategy_id:
            scan_dirs = [os.path.join(logs_root, self._safe_strategy_dir(strategy_id))]
        else:
            scan_dirs = [logs_root]
        for scan_dir in scan_dirs:
            if not os.path.isdir(scan_dir):
                continue
            if strategy_id:
                for name in sorted(os.listdir(scan_dir)):
                    if self._is_candles_log_filename(name):
                        paths.append(os.path.join(scan_dir, name))
            else:
                for root, _, files in os.walk(scan_dir):
                    for name in sorted(files):
                        if self._is_candles_log_filename(name):
                            paths.append(os.path.join(root, name))
        return paths

    @staticmethod
    def _parse_bar_timestamp_ist_to_aware(bar_ist: Any) -> Optional[dt.datetime]:
        """Parse ``bar_timestamp_ist`` / ``candle_timestamp_ist`` from logs (ISO or ``YYYY-MM-DD HH:MM`` IST)."""
        s = str(bar_ist).strip()
        if not s:
            return None
        try:
            if "T" in s:
                t = dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
                if t.tzinfo is None:
                    t = t.replace(tzinfo=IST)
                return t.astimezone(IST).replace(second=0, microsecond=0)
            if len(s) >= 16 and s[4] == "-" and s[10] == " ":
                t = dt.datetime.strptime(s[:16], "%Y-%m-%d %H:%M")
                return t.replace(tzinfo=IST)
        except Exception:
            return None
        return None

    def _rsi_history_path(self, strategy_id: str) -> str:
        sid = str(strategy_id or "GLOBAL").strip() or "GLOBAL"
        return os.path.join(self._rsi_log_root, sid, f"{sid}_rsi_history.log")

    @staticmethod
    def _dedupe_rows_by_timestamp(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Keep the last row per ``timestamp`` (handles duplicate log lines on restart)."""
        if not rows:
            return rows
        by_ts: Dict[Any, Dict[str, Any]] = {}
        for row in rows:
            ts = row.get("timestamp")
            if ts is not None:
                by_ts[ts] = row
        out = list(by_ts.values())
        out.sort(key=lambda r: r["timestamp"])
        return out

    def _hydrate_rsi_session_state_from_disk(
        self, strategy_id: str, symbol: str, tf: str
    ) -> None:
        """Mark indicator history streams on disk so restarts only append new bars."""
        stream_key = (symbol, tf)
        if stream_key in self._rsi_session_hydrated:
            return
        self._rsi_session_hydrated.add(stream_key)
        found = ind_hist.hydrate_session_keys_from_disk(
            symbol,
            tf,
            strategy_id,
            self._rsi_logged_keys,
            self._rsi_seeded_streams,
            log_root=self._rsi_log_root,
        )
        if found <= 0:
            self._rsi_session_hydrated.discard(stream_key)

    def _load_rsi_history_rows(
        self, strategy_id: str, symbol: str, tf: str, max_rows: int
    ) -> List[Dict[str, Any]]:
        """Load recent bars from shared indicator history (+ legacy RSI log)."""
        merged = ind_hist.load_indicator_history_rows(
            symbol,
            tf,
            max_rows=max_rows,
            log_root=self._rsi_log_root,
            strategy_id=strategy_id,
        )
        rows: List[Dict[str, Any]] = []
        for item in merged:
            row = {
                "timestamp": item["timestamp"],
                "open": item["open"],
                "high": item["high"],
                "low": item["low"],
                "close": item["close"],
                "volume": item.get("volume", 0.0),
                "symbol": item["symbol"],
                "exchange": item.get("exchange") or self._live_exchange or "INDEX",
            }
            for k, v in (item.get("indicators") or {}).items():
                row[k] = v
            rows.append(row)
        return self._dedupe_rows_by_timestamp(rows)

    def _load_candles_from_rsi_history(
        self, strategy_id: str, symbol: str, tf: str, tail_rows: int
    ) -> Any:
        """Bootstrap OHLC frame from deduped RSI history closes when candle logs are short."""
        rows = self._load_rsi_history_rows(strategy_id, symbol, tf, max_rows=tail_rows)
        out = self._candle_rows_to_sorted_df(rows, symbol)
        return self._strip_same_day_bars(out)

    def _merge_rsi_history_into_base_df(
        self,
        df: Any,
        strategy_id: str,
        symbol: str,
        tf: str,
        max_rows: int = 400,
    ) -> Any:
        """Prepend close-only bars from RSI history so the first live bar of the day gets a valid RSI."""
        import pandas as pd

        if df is None or len(df) == 0:
            return df
        hist = self._load_rsi_history_rows(strategy_id, symbol, tf, max_rows=max_rows)
        if not hist:
            return df
        hdf = pd.DataFrame(hist)
        base = df.copy()
        base["timestamp"] = pd.to_datetime(base["timestamp"], utc=True, errors="coerce")
        base = base.dropna(subset=["timestamp"])
        hdf["timestamp"] = pd.to_datetime(hdf["timestamp"], utc=True, errors="coerce")
        hdf = hdf.dropna(subset=["timestamp"])
        merged = pd.concat([hdf, base], ignore_index=True)
        merged = merged.sort_values("timestamp").drop_duplicates(subset=["timestamp"], keep="last")
        cap = max(max_rows, len(base) + 80)
        if len(merged) > cap:
            merged = merged.iloc[-cap:].reset_index(drop=True)
        return merged.reset_index(drop=True)

    def _collect_candle_closed_rows_from_logs(
        self,
        symbol_u: str,
        tf_s: str,
        ist_day: Optional[dt.date] = None,
        strategy_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Scan strategy ``logs/{strategy}/{engine_id}_candles.log`` (append-only).

        When ``strategy_id`` is omitted, scans all strategies under ``logs/``.
        When ``ist_day`` is set, only rows whose bar open falls on that IST calendar date.
        """
        rows: List[Dict[str, Any]] = []
        if not symbol_u or not tf_s:
            return rows
        try:
            for path in self._list_candles_log_paths(strategy_id):
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
                            bar_dt = self._parse_bar_timestamp_ist_to_aware(bar_ist)
                            if bar_dt is None:
                                continue
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
            logger.exception(
                "Failed collecting candle rows symbol=%s tf=%s strategy=%s",
                symbol_u,
                tf_s,
                strategy_id,
            )
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

    def _load_candles_from_logs(
        self, symbol: str, tf: str, tail_rows: int, strategy_id: Optional[str] = None
    ) -> Any:
        """Load the most recent ``tail_rows`` closed candles for symbol|timeframe from disk logs."""
        import pandas as pd

        symbol_u = str(symbol or "").strip().upper()
        tf_s = str(tf or "").strip()
        rows = self._collect_candle_closed_rows_from_logs(
            symbol_u, tf_s, ist_day=None, strategy_id=strategy_id
        )
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
        strategy: Any = None,
        *,
        exchange: Optional[str] = None,
        append_live: bool = True,
    ) -> None:
        """Append indicator snapshot row(s) to shared history (symbol + timeframe)."""
        if df is None or len(df) == 0 or "timestamp" not in df.columns:
            return
        keys = self._strategy_persisted_indicator_keys(strategy) if strategy else []
        if not keys and "rsi" in df.columns:
            keys = ["rsi", "prev_rsi"]
        if not keys:
            return

        self._hydrate_rsi_session_state_from_disk(strategy_id, symbol, tf)
        stream_key = (symbol, tf)
        seeded = stream_key in self._rsi_seeded_streams
        if seeded and not append_live:
            return
        rows = [df.iloc[-1]] if seeded else [r for _, r in df.iterrows()]
        source = "live_append" if seeded else "historical_seed"

        for row in rows:
            ind_hist.append_indicator_history_row(
                symbol,
                tf,
                row,
                keys,
                source=source,
                log_root=self._rsi_log_root,
                logged_keys=self._rsi_logged_keys,
                round_fn=round_json_floats,
                exchange=exchange,
            )
        self._rsi_seeded_streams.add(stream_key)

    def _load_today_live_candles(
        self, symbol: str, tf: str, strategy_id: Optional[str] = None
    ) -> Any:
        import pandas as pd

        symbol_u = str(symbol or "").strip().upper()
        tf_s = str(tf or "").strip()
        if not symbol_u or not tf_s:
            return pd.DataFrame()
        ist_today = dt.datetime.now(IST).date()
        rows = self._collect_candle_closed_rows_from_logs(
            symbol_u, tf_s, ist_day=ist_today, strategy_id=strategy_id
        )
        return self._candle_rows_to_sorted_df(rows, symbol)

    def _merge_today_live_candles(
        self, df: Any, symbol: str, tf: str, strategy_id: Optional[str] = None
    ) -> Any:
        import pandas as pd

        if df is None or len(df) == 0 or "timestamp" not in df.columns:
            return df
        live_df = self._load_today_live_candles(symbol, tf, strategy_id=strategy_id)
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

    @staticmethod
    def _strip_same_day_bars(df: Any) -> Any:
        """Remove today's rows from API bootstrap; today's OHLC comes from closed-candle logs."""
        import pandas as pd

        if df is None or len(df) == 0 or "timestamp" not in df.columns:
            return df
        ist_today = dt.datetime.now(IST).date()
        ts = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
        mask = ts.dt.tz_convert(IST).dt.date < ist_today
        out = df.loc[mask].reset_index(drop=True)
        return out

    @staticmethod
    def _indicator_row_for_candle(df: Any, row_ts: Any) -> Any:
        """Return the indicator dataframe row matching the live candle bar open time."""
        import pandas as pd

        if df is None or len(df) == 0:
            return None
        target = pd.to_datetime(row_ts, utc=True, errors="coerce")
        if pd.isna(target):
            return None
        tss = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
        matches = df.loc[tss == target]
        if len(matches) > 0:
            return matches.iloc[-1]
        # Do not fall back to df.iloc[-1]: that attaches forming-bar RSI to a closed
        # aggregator candle and causes repeated / contradictory entry signals.
        return None

    def _bootstrap_base_candle_state(
        self,
        symbol: str,
        tf: str,
        exchange: str,
        sector: str,
        window: int,
        strategy_id: Optional[str] = None,
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
        df_log = self._load_candles_from_logs(symbol, tf, need_tail, strategy_id=strategy_id)
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

        if df is None and strategy_id:
            df_rsi = self._load_candles_from_rsi_history(
                strategy_id, symbol, tf, need_tail
            )
            if len(df_rsi) > 0:
                ok, reason = self._validate_log_candles(df_rsi, tf, exchange, window)
                if ok:
                    df = df_rsi.copy()
                    source = "indicator_history"
                else:
                    logger.info(
                        "BOOTSTRAP_RSI_HISTORY_REJECT symbol=%s tf=%s strategy=%s reason=%s rows=%s need=%s",
                        symbol,
                        tf,
                        strategy_id,
                        reason,
                        len(df_rsi),
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
                df = self._strip_same_day_bars(df.copy())

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
        df = self._merge_today_live_candles(df, symbol, tf, strategy_id=strategy_id)
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
        elif source == "indicator_history":
            logger.info(
                "BOOTSTRAP_PRIMARY_INDICATOR_HISTORY symbol=%s tf=%s strategy=%s rows=%s window=%s",
                symbol,
                tf,
                strategy_id,
                len(df),
                window,
            )
        return new_state

    def enrich_candle_for_strategy(
        self,
        strategy: Any,
        candle: Dict[str, Any],
        candle_bucket_fn: Any,
        out_meta: Optional[Dict[str, Any]] = None,
        allow_live_persist: bool = True,
    ) -> Dict[str, Any]:
        import pandas as pd

        tf = str(getattr(strategy, "timeframe", "") or "")
        if not tf:
            return dict(candle)

        symbol = str(candle.get("symbol") or "")
        if not symbol:
            return dict(candle)

        exchange = str(candle.get("exchange") or self._live_exchange or "INDEX")
        sector = str(self._live_sector or "NO")
        strategy_id = str(getattr(strategy, "name", "unknown_strategy"))
        window = self.indicator_window_size(strategy)
        if self._strategy_uses_indicator_history(strategy):
            self._hydrate_rsi_session_state_from_disk(strategy_id, symbol, tf)
        base_state = self._bootstrap_base_candle_state(
            symbol, tf, exchange, sector, window, strategy_id=strategy_id
        )
        base_df = base_state.get("df")
        if base_df is None:
            return dict(candle)

        bucket = candle.get("bucket_ts")
        if bucket is None:
            bucket = candle_bucket_fn(candle)
        bar_closed_for_append = False
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
                # Reject stale live candle older than history (skip when same IST day — partial bootstrap).
                if not pd.isna(last_hist_ts) and row_ts < last_hist_ts:
                    same_ist_day = (
                        pd.Timestamp(row_ts).tz_convert(IST).date()
                        == pd.Timestamp(last_hist_ts).tz_convert(IST).date()
                    )
                    if not same_ist_day:
                        base_state["last_bucket"] = bucket
                        return dict(candle)
                    # Same-day rows from logs/API ahead of this close are dropped.
                    tss = pd.to_datetime(base_df["timestamp"], utc=True, errors="coerce")
                    row_ist_date = pd.Timestamp(row_ts).tz_convert(IST).date()
                    keep = (tss.dt.tz_convert(IST).dt.date != row_ist_date) | (tss <= row_ts)
                    base_df = base_df.loc[keep].reset_index(drop=True)
                    base_state["df"] = base_df
                    last_hist_ts = (
                        pd.to_datetime(base_df.iloc[-1].get("timestamp"), utc=True, errors="coerce")
                        if len(base_df) > 0
                        else pd.NaT
                    )
                # If candle timestamp matches last history row, replace last row with live OHLC.
                # This keeps continuity and fixes close/RSI drift on boundary buckets.
                if not pd.isna(last_hist_ts) and last_hist_ts == row_ts:
                    last_idx = base_df.index[-1]
                    for col, value in row.items():
                        base_df.at[last_idx, col] = value
                    base_state["df"] = base_df
                    base_state["last_bucket"] = bucket
                    base_state["update_seq"] = int(base_state.get("update_seq", 0)) + 1
                    bar_closed_for_append = False
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
                    bar_closed_for_append = True
                    if out_meta is not None:
                        out_meta["bar_closed_for_append"] = True
            else:
                base_df = pd.concat([base_df, pd.DataFrame([row])], ignore_index=True)
                if len(base_df) > int(base_state.get("window") or window):
                    base_df = base_df.iloc[-int(base_state.get("window") or window) :].reset_index(drop=True)
                base_state["df"] = base_df
                base_state["last_bucket"] = bucket
                base_state["continuity_checked"] = True
                base_state["update_seq"] = int(base_state.get("update_seq", 0)) + 1
                bar_closed_for_append = True
                if out_meta is not None:
                    out_meta["bar_closed_for_append"] = True

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
                work_df = df.copy()
                if self._strategy_uses_indicator_history(strategy):
                    work_df = self._merge_rsi_history_into_base_df(
                        work_df,
                        strategy_id=str(getattr(strategy, "name", "unknown_strategy")),
                        symbol=symbol,
                        tf=tf,
                    )
                try:
                    work_df = strategy.prepare_indicators(work_df)
                except Exception:
                    pass
                df = work_df
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
                    strategy=strategy,
                    exchange=exchange,
                    append_live=bool(bar_closed_for_append and allow_live_persist),
                )
            elif self._strategy_persisted_indicator_keys(strategy):
                self._append_rsi_history_log(
                    strategy_id=str(getattr(strategy, "name", "unknown_strategy")),
                    symbol=symbol,
                    tf=tf,
                    df=df,
                    strategy=strategy,
                    exchange=exchange,
                    append_live=bool(bar_closed_for_append and allow_live_persist),
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

        bar_row_ts = None
        if bucket is not None:
            bar_row_ts = pd.to_datetime(bucket, unit="s", utc=True, errors="coerce")
        if bar_row_ts is None or pd.isna(bar_row_ts):
            bar_row_ts = pd.to_datetime(candle.get("timestamp"), utc=True, errors="coerce")
        latest = self._indicator_row_for_candle(df, bar_row_ts)
        if latest is None and bar_closed_for_append and len(df) > 0:
            latest = df.iloc[-1]
        if latest is None:
            if out_meta is not None and bar_closed_for_append:
                out_meta["bar_closed_for_append"] = True
            return out
        latest_dict = latest.to_dict() if hasattr(latest, "to_dict") else dict(latest)
        preserve = {
            "symbol",
            "exchange",
            "timestamp",
            "bucket_ts",
            "open",
            "high",
            "low",
            "close",
            "volume",
        }
        for k, v in latest_dict.items():
            if k in preserve:
                continue
            out[k] = v
        if out_meta is not None:
            out_meta["bar_closed_for_append"] = bool(bar_closed_for_append)
        return out

