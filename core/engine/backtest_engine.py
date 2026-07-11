import logging

import pandas as pd
import datetime as dt
from collections import deque
from typing import Any, Optional

from core.data.candle_aggregator import _bucket_ts, _resolution_to_seconds
from core.engine.base_engine import BaseEngine
from core.utils import indicator_history as ind_hist

logger = logging.getLogger(__name__)

_MIN_BACKTEST_BARS = 50
# Delta intraday cache sometimes stores IST wall-clock as UTC (+5:30 duplicate buckets).
_DELTA_IST_AS_UTC_OFFSET = pd.Timedelta(hours=5, minutes=30)
from core.utils.structure.liquidity import liquidity_sweep_column_names

_LIVE_APPEND_SOURCE = "live_append"
# Recompute these on OHLC during backtest; do not trust ``live_append`` disk rows.
_STRUCTURE_SIGNAL_KEYS = frozenset(
    {
        "rsi",
        "rsi_div_bull",
        "rsi_div_bear",
        "bos",
        "choch",
        "structure_trend",
        "swing_high",
        "swing_low",
        "last_swing_high",
        "last_swing_low",
        *liquidity_sweep_column_names(),
    }
)


def _position_allows_strategy_exit(pos: Any) -> bool:
    """MAIN book and post-partial trail legs (tag may become MAIN_TARGET after TARGET fill)."""
    tag_u = str(getattr(pos, "tag", None) or "").upper()
    if tag_u == "HEDGE":
        return False
    return tag_u == "MAIN" or tag_u.startswith("MAIN_")


class BacktestEngine(BaseEngine):
    def __init__(
        self,
        data_provider,
        strategy,
        instrument_store,
        order_router,
        position_manager,
        universe_service=None,
        broker_name=None,
    ):
        super().__init__(
            strategy=strategy,
            data=data_provider,
            instrument_store=instrument_store,
            position_manager=position_manager,
            universe_service=universe_service,
        )
        self.order_router = order_router
        self.position_manager = position_manager
        self.broker_name = broker_name or ""
        # Wire structure-exit callback (ONE TIME)
        self.position_manager.on_structure_exit = strategy.on_structure_exit
        self.position_manager.on_forced_exit = getattr(
            strategy, "on_forced_exit", None
        )
        # Deferred ENTRY after MAIN_EXIT fill (e.g. OneDayMagicalLine / NiftyIntradayMagicalLine reversal)
        self.position_manager.on_main_exit_fill = self._on_pm_main_exit_fill
        self.position_manager.on_main_entry_fill = self._on_pm_main_entry_fill
        self._last_candle: Any = None
        self._last_candle_buffer: list = []

    def _on_pm_main_entry_fill(self, **kwargs: Any) -> None:
        strategy = kwargs.get("strategy")
        if strategy != self.strategy.name:
            return
        fn = getattr(self.strategy, "on_main_entry_filled", None)
        if not callable(fn):
            return
        candle = getattr(self, "_last_candle", None)
        if not candle:
            return
        recent = getattr(self, "_last_candle_buffer", None) or []
        kwargs.pop("ctx", None)
        ctx = self.build_context_only(candle, recent_candles=recent)
        intents = fn(ctx=ctx, **kwargs) or []
        for intent in intents:
            inst = intent.instrument
            sym = inst.trading_symbol
            strike = getattr(inst, "strike", None)
            option_type = getattr(inst, "option_type", None)
            if not self.strategy._is_option_instrument(strike, option_type):
                px = float(intent.price)
            else:
                px = self.strategy.get_option_price_at_candle(
                    candle,
                    ctx,
                    strike,
                    option_type,
                    inst.expiry,
                    trading_symbol=sym,
                )
                if px is None:
                    px = float(intent.price)
            price_map = {sym: float(px)}
            self.order_router.process_intent(intent, price_map)

    def _on_pm_main_exit_fill(self, **kwargs: Any) -> None:
        strategy = kwargs.get("strategy")
        if strategy != self.strategy.name:
            return
        fn = getattr(self.strategy, "on_main_exit_filled", None)
        if not callable(fn):
            return
        inst = kwargs.get("instrument")
        sym = None
        if inst is not None:
            sym = getattr(inst, "underlying_symbol", None) or getattr(
                inst, "symbol", None
            )
        ts = kwargs.get("candle_ts")
        candle_stub = {"symbol": sym or "", "timestamp": ts, "close": 0.0}
        kwargs.pop("ctx", None)
        ctx = (
            self.build_context(candle_stub)
            if sym and callable(getattr(self, "build_context", None))
            else None
        )
        pairs = fn(ctx=ctx, **kwargs) or []
        for intent, candle in pairs:
            sym = candle.get("symbol")
            if not sym:
                continue
            price_map = {
                intent.instrument.trading_symbol: float(
                    intent.price
                )
            }
            self.order_router.process_intent(intent, price_map)

    def build_context(self, candle, recent_candles=None):
        intent_store = getattr(self.order_router, "intent_store", None)
        return super().build_context(
            candle, recent_candles=recent_candles, intent_store=intent_store
        )

    @staticmethod
    def _rows_to_ohlc_df(rows: list) -> Optional[pd.DataFrame]:
        if not rows:
            return None
        df = pd.DataFrame(rows)
        if df.empty or "timestamp" not in df.columns:
            return None
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
        df = df.dropna(subset=["timestamp"])
        df = (
            df.sort_values("timestamp")
            .drop_duplicates(subset=["timestamp"], keep="last")
            .reset_index(drop=True)
        )
        return df if len(df) > 0 else None

    @staticmethod
    def _persisted_indicator_keys(strategy: Any) -> list:
        fn = getattr(strategy, "persisted_indicator_keys", None)
        if not callable(fn):
            return []
        try:
            return [str(k) for k in (fn() or []) if k]
        except Exception:
            return []

    @staticmethod
    def _overlay_stored_indicators(
        df: pd.DataFrame,
        stored: Optional[pd.DataFrame],
        keys: list,
        *,
        source_col: Optional[str] = None,
        skip_live_append_keys: Optional[frozenset] = None,
    ) -> pd.DataFrame:
        """Prefer indicator_history.jsonl values over recomputed columns."""
        if (
            stored is None
            or df is None
            or len(df) == 0
            or len(stored) == 0
            or not keys
        ):
            return df
        out = df.copy()
        out["_ts_key"] = pd.to_datetime(out["timestamp"], utc=True).astype("int64")
        st = stored.copy()
        st["_ts_key"] = pd.to_datetime(st["timestamp"], utc=True).astype("int64")
        st = st.drop_duplicates(subset=["_ts_key"], keep="last").set_index("_ts_key")
        live_src = None
        if (
            source_col
            and source_col in st.columns
            and skip_live_append_keys
        ):
            live_src = out["_ts_key"].map(st[source_col]) == _LIVE_APPEND_SOURCE
        for k in keys:
            if k not in st.columns:
                continue
            mapped = out["_ts_key"].map(st[k])
            recomputed = out[k] if k in out.columns else None
            if live_src is not None and k in skip_live_append_keys:
                mapped = mapped.where(~live_src, recomputed)
            if recomputed is not None:
                out[k] = mapped.combine_first(recomputed)
            else:
                out[k] = mapped
        return out.drop(columns=["_ts_key"])

    @staticmethod
    def _filter_df_calendar_range(
        df: pd.DataFrame, start_date: str, end_date: str
    ) -> pd.DataFrame:
        start_d = ind_hist._parse_calendar_date(start_date)
        end_d = ind_hist._parse_calendar_date(end_date)
        if start_d is None or end_d is None:
            return df
        ts_ist = pd.to_datetime(df["timestamp"], utc=True).dt.tz_convert(ind_hist.IST)
        mask = (ts_ist.dt.date >= start_d) & (ts_ist.dt.date <= end_d)
        return df.loc[mask].reset_index(drop=True)

    @staticmethod
    def _hist_covers_calendar_range(
        df_hist: Optional[pd.DataFrame], start_date: str, end_date: str
    ) -> bool:
        if df_hist is None or len(df_hist) == 0:
            return False
        start_d = ind_hist._parse_calendar_date(start_date)
        end_d = ind_hist._parse_calendar_date(end_date)
        if start_d is None or end_d is None:
            return False
        tss = pd.to_datetime(df_hist["timestamp"], utc=True, errors="coerce")
        tss = tss.dropna()
        if tss.empty:
            return False
        earliest = tss.min().astimezone(ind_hist.IST).date()
        latest = tss.max().astimezone(ind_hist.IST).date()
        return earliest <= start_d and latest >= end_d

    @staticmethod
    def _drop_delta_ist_wall_clock_as_utc_api_bars(
        df_api: pd.DataFrame, df_hist: pd.DataFrame
    ) -> pd.DataFrame:
        """Drop API rows whose UTC label is IST wall-clock when history has the real UTC bar."""
        if df_api is None or df_api.empty or df_hist is None or df_hist.empty:
            return df_api
        api = df_api.copy()
        hist = df_hist.copy()
        api["timestamp"] = pd.to_datetime(api["timestamp"], utc=True, errors="coerce")
        hist["timestamp"] = pd.to_datetime(hist["timestamp"], utc=True, errors="coerce")
        api = api.dropna(subset=["timestamp"])
        hist = hist.dropna(subset=["timestamp"])
        if api.empty or hist.empty:
            return api
        hist_keys = set(hist["timestamp"].astype("int64"))
        shifted = api["timestamp"] - _DELTA_IST_AS_UTC_OFFSET
        dup_mask = shifted.astype("int64").isin(hist_keys)
        dropped = int(dup_mask.sum())
        if dropped > 0:
            logger.info(
                "Backtest dropped %s Delta API bars with IST wall-clock stored as UTC",
                dropped,
            )
        return api.loc[~dup_mask].reset_index(drop=True)

    @staticmethod
    def _merge_backtest_ohlc(
        df_hist: Optional[pd.DataFrame],
        df_api: Optional[pd.DataFrame],
        *,
        prefer_hist: bool = True,
        exchange: Optional[str] = None,
    ) -> Optional[pd.DataFrame]:
        """Merge OHLC; when ``prefer_hist``, indicator history wins on duplicate buckets."""
        parts = [d for d in (df_hist, df_api) if d is not None and len(d) > 0]
        if not parts:
            return None
        if len(parts) == 1:
            return parts[0].copy()

        hist = df_hist.copy()
        api = df_api.copy()
        if str(exchange or "").upper() == "DELTA":
            api = BacktestEngine._drop_delta_ist_wall_clock_as_utc_api_bars(api, hist)
            if api is None or api.empty:
                return hist.sort_values("timestamp").reset_index(drop=True)

        hist["timestamp"] = pd.to_datetime(hist["timestamp"], utc=True, errors="coerce")
        api["timestamp"] = pd.to_datetime(api["timestamp"], utc=True, errors="coerce")
        hist = hist.dropna(subset=["timestamp"])
        api = api.dropna(subset=["timestamp"])

        if prefer_hist and len(hist) > 0:
            hist_keys = set(hist["timestamp"].astype("int64"))
            api_gap = api.loc[~api["timestamp"].astype("int64").isin(hist_keys)]
            if len(api_gap) == 0:
                return (
                    hist.sort_values("timestamp").reset_index(drop=True)
                )
            merged = pd.concat([hist, api_gap], ignore_index=True)
            return merged.sort_values("timestamp").reset_index(drop=True)

        merged = pd.concat([hist, api], ignore_index=True)
        merged = (
            merged.sort_values("timestamp")
            .drop_duplicates(subset=["timestamp"], keep="first")
            .reset_index(drop=True)
        )
        return merged

    def _load_backtest_ohlc(
        self,
        symbol: str,
        start_date: str,
        end_date: str,
        timeframe: str,
        exchange: str,
        sector: str,
    ) -> Optional[pd.DataFrame]:
        """Prefer shared indicator history (live bootstrap file), then API."""
        strategy_id = getattr(self.strategy, "name", None)
        context_bars = 0
        try:
            fn = getattr(self.strategy, "get_structure_lookback", None)
            if callable(fn):
                context_bars = max(0, int(fn() or 0))
        except (TypeError, ValueError):
            context_bars = 0
        hist_rows = ind_hist.load_indicator_history_bars_for_backtest(
            symbol,
            str(timeframe),
            start_date,
            end_date,
            strategy_id=strategy_id,
            exchange_default=exchange,
            context_bars=context_bars,
        )
        df_hist = self._rows_to_ohlc_df(hist_rows)
        df_api = self.data.get_intraday(
            symbol=symbol,
            start_date=start_date,
            end_date=end_date,
            timeframe=timeframe,
            exchange=exchange,
            sector=sector,
        )
        if df_api is not None and len(df_api) > 0:
            df_api = df_api.copy()
            df_api["timestamp"] = pd.to_datetime(df_api["timestamp"], utc=True, errors="coerce")
            df_api = df_api.dropna(subset=["timestamp"]).reset_index(drop=True)

        n_hist = len(df_hist) if df_hist is not None else 0
        n_api = len(df_api) if df_api is not None else 0
        is_delta = str(exchange or "").upper() == "DELTA"

        if (
            n_hist >= _MIN_BACKTEST_BARS
            and is_delta
            and self._hist_covers_calendar_range(df_hist, start_date, end_date)
        ):
            logger.info(
                "Backtest OHLC source=indicator_history symbol=%s tf=%s rows=%s range=%s..%s (delta range covered)",
                symbol,
                timeframe,
                n_hist,
                start_date,
                end_date,
            )
            return df_hist

        if n_hist >= _MIN_BACKTEST_BARS and n_api == 0:
            logger.info(
                "Backtest OHLC source=indicator_history symbol=%s tf=%s rows=%s range=%s..%s",
                symbol,
                timeframe,
                n_hist,
                start_date,
                end_date,
            )
            return df_hist

        if n_hist >= _MIN_BACKTEST_BARS and n_api > 0:
            df = self._merge_backtest_ohlc(
                df_hist, df_api, prefer_hist=True, exchange=exchange
            )
            n_gap = 0 if df is None else max(0, len(df) - n_hist)
            logger.info(
                "Backtest OHLC source=indicator_history+api_gap symbol=%s tf=%s hist=%s api=%s merged=%s api_only=%s",
                symbol,
                timeframe,
                n_hist,
                n_api,
                len(df) if df is not None else 0,
                n_gap,
            )
            return df

        if n_api >= _MIN_BACKTEST_BARS:
            logger.info(
                "Backtest OHLC source=api symbol=%s tf=%s rows=%s range=%s..%s",
                symbol,
                timeframe,
                n_api,
                start_date,
                end_date,
            )
            return df_api

        if n_hist > 0 or n_api > 0:
            df = self._merge_backtest_ohlc(
                df_hist, df_api, exchange=exchange
            )
            if df is not None and len(df) > 0:
                logger.warning(
                    "Backtest OHLC sparse symbol=%s tf=%s hist=%s api=%s merged=%s (min=%s)",
                    symbol,
                    timeframe,
                    n_hist,
                    n_api,
                    len(df),
                    _MIN_BACKTEST_BARS,
                )
                return df

        hist_path = ind_hist.indicator_history_path(symbol, str(timeframe))
        logger.warning(
            "Backtest OHLC missing symbol=%s tf=%s range=%s..%s hist_file=%s hist_rows=%s api_rows=%s",
            symbol,
            timeframe,
            start_date,
            end_date,
            hist_path,
            n_hist,
            n_api,
        )
        return None

    # ==========================================================
    # MAIN RUN LOOP
    # ==========================================================
    def run(self, symbols, start_date, end_date, timeframe, exchange, sector):
        for symbol in symbols:
            df = self._load_backtest_ohlc(
                symbol=symbol,
                start_date=start_date,
                end_date=end_date,
                timeframe=timeframe,
                exchange=exchange,
                sector=sector,
            )

            if df is None or len(df) < _MIN_BACKTEST_BARS:
                logger.warning(
                    "Backtest skip symbol=%s tf=%s rows=%s (need >= %s)",
                    symbol,
                    timeframe,
                    0 if df is None else len(df),
                    _MIN_BACKTEST_BARS,
                )
                continue

            df["symbol"] = symbol
            df["exchange"] = exchange

            # -------- Indicators (strategy computes htf_trend in prepare_indicators) --------

            ts_col = pd.to_datetime(df["timestamp"], utc=True)
            # IST labels match indicator_history.jsonl ``candle_timestamp_ist`` keys.
            df["timestamp"] = ts_col.dt.tz_convert(ind_hist.IST)
            if "time" in df.columns:
                df["time"] = df["timestamp"].dt.time

            tf_sec = int(_resolution_to_seconds(str(timeframe)))
            is_delta = (
                str(self.broker_name or "").upper() == "DELTA"
                or str(exchange or "").upper() == "DELTA"
            )

            ind_keys = self._persisted_indicator_keys(self.strategy)
            store_cols = ["timestamp"] + [k for k in ind_keys if k in df.columns]
            if "indicator_source" in df.columns:
                store_cols.insert(1, "indicator_source")
            stored_ind = (
                df[store_cols].copy()
                if ind_keys and len(store_cols) > 1
                else None
            )
            prep_cols = [
                c
                for c in df.columns
                if c not in ind_keys and c != "indicator_source"
            ]
            df = self.strategy.prepare_indicators(df[prep_cols].copy())
            if stored_ind is not None and ind_keys:
                overlay_keys = [k for k in ind_keys if k in stored_ind.columns]
                df = self._overlay_stored_indicators(
                    df,
                    stored_ind,
                    overlay_keys,
                    source_col="indicator_source",
                    skip_live_append_keys=_STRUCTURE_SIGNAL_KEYS,
                )

            df = self._filter_df_calendar_range(df, start_date, end_date)
            warmup = self.strategy.get_warmup_period()
            # Include macro EMA warmup so first ~50 (slope) or ~100 (ema) candles are stable
            macro_slope = getattr(self.strategy, "macro_ema_slope_period", None)
            macro_ema = getattr(self.strategy, "macro_ema_period", None)
            macro_warmup = max(warmup, macro_slope or 0, macro_ema or 0)
            df = df.iloc[macro_warmup:].reset_index(drop=True)

            lookback = 0
            try:
                fn = getattr(self.strategy, "get_structure_lookback", None)
                if callable(fn):
                    lookback = int(fn() or 0)
            except (TypeError, ValueError):
                lookback = 0
            buf_size = max(220, lookback + 20)
            candle_buffer = deque(maxlen=buf_size)

            # -------- Candle loop (candle["htf_trend"] already set above for macro filter) --------
            for _, row in df.iterrows():
                candle = row.to_dict()
                ts = pd.to_datetime(candle["timestamp"], utc=True)
                try:
                    candle["bucket_ts"] = _bucket_ts(float(ts.timestamp()), tf_sec)
                except (OSError, OverflowError, TypeError, ValueError):
                    candle["bucket_ts"] = None
                if is_delta:
                    candle["candle_timestamp_ist"] = ind_hist.normalize_ist_bar_key(
                        ts.tz_convert(ind_hist.IST)
                    )
                if "htf_trend" not in candle or pd.isna(candle.get("htf_trend")):
                    candle["htf_trend"] = None

                # Skip weekends for equity/index; crypto (DELTA) runs 24/7
                # if self.broker_name != "DELTA" and ts.weekday() >= 5:
                #     continue

                candle_buffer.append(candle)
                self._last_candle = candle
                self._last_candle_buffer = list(candle_buffer)

                # -------- Runtime context --------
                ctx, entry_intent = self.build_context(
                    candle, recent_candles=list(candle_buffer)
                )
                self._last_ctx = ctx
                self.evaluate_sim_broker_stops(candle, ctx)
                # 🔥 ALWAYS run exits + rollover
                self._run_risk_and_rollover(symbol, candle, ctx)

                # 🔒 ONLY gate entries
                if self.strategy.should_evaluate(candle):
                    self._run_entry(symbol, candle, entry_intent)

                self.update_risk_metrics(symbol, candle["close"])

    # ==========================================================
    # EXIT + ROLLOVER (ALWAYS EXECUTES)
    # ==========================================================
    def _run_risk_and_rollover(self, symbol, candle, ctx):

        open_positions = self.position_manager.get_open_positions(
            underlying=symbol,
            strategy=self.strategy.name,
        )

        # ---------- FORCED / STRATEGY EXITS ----------
        for pos in open_positions:
            if _position_allows_strategy_exit(pos) and self.strategy.should_exit(
                pos, candle, ctx
            ):
                exit_intents = self.strategy.on_position_exit(pos, candle, ctx) or []
                for intent in exit_intents:
                    price_map = self._backtest_price_map(intent, candle, ctx)
                    if price_map is None:
                        continue
                    self.order_router.process_intent(intent, price_map)

        # ---------- HEDGE ROLLOVER ----------
        rollover_intents = (
            self.strategy.on_candle_rollover(
                open_positions=open_positions,
                candle=candle,
                ctx=ctx,
            )
            or []
        )

        for intent in rollover_intents:
            price_map = self._backtest_price_map(intent, candle, ctx)
            if price_map is None:
                continue
            self.order_router.process_intent(intent, price_map)

    def _backtest_price_map(self, intent, candle, ctx):
        """Resolve a positive fill price for backtest process_intent."""
        inst = getattr(intent, "instrument", None)
        if inst is None:
            return None
        sym = getattr(inst, "trading_symbol", None)
        if not sym:
            return None
        px = getattr(intent, "price", None)
        try:
            if px is not None and float(px) > 0:
                return {sym: float(px)}
        except (TypeError, ValueError):
            pass
        try:
            px = self.strategy.get_option_price_at_candle(
                candle,
                ctx,
                getattr(inst, "strike", None),
                getattr(inst, "option_type", None),
                getattr(inst, "expiry", None),
                trading_symbol=sym,
            )
        except Exception:
            px = None
        try:
            if px is not None and float(px) > 0:
                return {sym: float(px)}
        except (TypeError, ValueError):
            pass
        logger.warning(
            "Backtest skip intent: no price for %s action=%s",
            sym,
            getattr(intent, "action", None),
        )
        return None

    # ==========================================================
    # ENTRY (SIGNAL DRIVEN)
    # ==========================================================
    def _run_entry(self, symbol, candle, entry_intent):
        if not entry_intent:
            return

        # entry_intent can be a single OrderIntent or a list
        if not isinstance(entry_intent, list):
            entry_intent = [entry_intent]

        for intent in entry_intent:
            # Rebuild ctx from last candle for price fallback when needed.
            ctx = getattr(self, "_last_ctx", None)
            if ctx is None:
                price_map = {intent.instrument.trading_symbol: intent.price}
            else:
                price_map = self._backtest_price_map(intent, candle, ctx)
                if price_map is None:
                    price_map = {intent.instrument.trading_symbol: intent.price}
            try:
                if price_map is None or not any(
                    v is not None and float(v) > 0 for v in price_map.values()
                ):
                    logger.warning(
                        "Backtest skip entry: no price for %s",
                        getattr(getattr(intent, "instrument", None), "trading_symbol", None),
                    )
                    continue
            except (TypeError, ValueError):
                continue
            self.order_router.process_intent(intent, price_map)
    # ==========================================================
    # RISK METRICS
    # ==========================================================
    def update_risk_metrics(self, symbol, ltp):
        pos = self.position_manager.positions.get(symbol)
        if not pos or pos.net_qty == 0:
            return

        diff = ltp - pos.entry_price
        if pos.net_qty < 0:
            diff *= -1

        pos.mfe = max(pos.mfe, diff)
        pos.mae = min(pos.mae, diff)
