from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

import pandas as pd
import pdb


class DeltaMktMixins:
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._delta_cache_date: Optional[pd.Timestamp] = None
        self._delta_cache_file: Optional[Path] = None
        self._delta_cache_df: Optional[pd.DataFrame] = None

    def _delta_logs_dir(self) -> Path:
        # core/strategies -> core -> repo root
        return Path(__file__).resolve().parents[2] / "logs" / "delta"

    def _pick_delta_file_for_date(self, trade_date: pd.Timestamp) -> Optional[Path]:

        logs_dir = self._delta_logs_dir()

        if not logs_dir.exists():
            return None

        year = trade_date.strftime("%Y")
        month_file = trade_date.strftime("BTC_%Y-%m.csv")

        # ---- Step 1: find correct year folder ----
        year_dirs = list(logs_dir.glob(f"options-BTC-{year}.csv"))

        if not year_dirs:
            return None

        year_dir = year_dirs[0]

        # ---- Step 2: find month file ----
        file_path = year_dir / month_file

        if file_path.exists():
            return file_path

        # ---- fallback: closest month ----
        candidates = list(year_dir.glob("BTC_*.csv"))

        if not candidates:
            return None

        dated = []
        for p in candidates:
            try:
                # BTC_2026-02.csv → 2026-02
                date_str = p.stem.split("_")[1]
                parsed = pd.to_datetime(date_str, format="%Y-%m")
                dated.append((parsed, p))
            except:
                continue

        if not dated:
            return None

        dated.sort(key=lambda x: x[0])

        trade_month = trade_date.to_period("M").to_timestamp()

        prev = [d for d in dated if d[0] <= trade_month]

        if prev:
            return prev[-1][1]

        return dated[0][1]

    def load_delta_data_for_candle(
        self, candle: dict, ctx: Any
    ) -> Optional[pd.DataFrame]:

        candle_ts = pd.to_datetime(candle["timestamp"])
        trade_date = candle_ts.tz_localize(None).normalize()

        if self._delta_cache_date is not None and self._delta_cache_date == trade_date:
            ctx.delta_data = self._delta_cache_df
            return self._delta_cache_df

        file_path = self._pick_delta_file_for_date(trade_date)

        if file_path is None:
            ctx.delta_data = None
            self._delta_cache_date = trade_date
            self._delta_cache_file = None
            self._delta_cache_df = None
            return None

        try:
            df = pd.read_csv(file_path)
        except Exception:
            ctx.delta_data = None
            self._delta_cache_date = trade_date
            self._delta_cache_file = file_path
            self._delta_cache_df = None
            return None

        self._delta_cache_date = trade_date
        self._delta_cache_file = file_path
        self._delta_cache_df = df
        return df

    def weeklyExpiry():
        ts = pd.to_datetime(candle["timestamp"]).tz_localize(None)
        trade_date = ts.date()
        weekday = trade_date.weekday()  # Mon=0 ... Thu=3 ... Fri=4

        # Weekly expiry rule:
        # - default: this week's Friday
        # - on Thursday: use next week's Friday
        if weekday == 3:
            days_to_friday = 8
        else:
            days_to_friday = 4 - weekday
            if days_to_friday < 0:
                days_to_friday += 7

        weekly_expiry = trade_date + pd.Timedelta(days=days_to_friday)
        ctx.selected_expiry = pd.Timestamp(weekly_expiry).strftime("%Y-%m-%d")

    def find_strike_in_premium_range(
        self,
        candle,
        ctx,
        option_type,  # "C" or "P"
        expiry,
        min_prem=200,
        max_prem=400,
        lookback_sec=60,
        # 🔥 important for realistic fills
    ):
        # Keep data-loading responsibility inside the mixin so strategies
        # only call strike selection.
        df = self.load_delta_data_for_candle(candle, ctx)

        if df is None or df.empty:
            return None

        if expiry is "Weekly":
            weeklyExpiry()
        # ---- columns ----
        df.columns = ["symbol", "price", "qty", "timestamp", "side"]
        df["timestamp"] = pd.to_datetime(df["timestamp"])

        candle_time = pd.to_datetime(candle["timestamp"]).tz_localize(None)

        # ---- 🔥 ONLY recent trades (avoid stale LTP) ----
        start_time = candle_time - pd.Timedelta(seconds=lookback_sec)
        df = df[(df["timestamp"] >= start_time) & (df["timestamp"] <= candle_time)]

        if df.empty:
            return None

        # ---- parse symbol ----
        parts = df["symbol"].str.split("-", expand=True)
        pdb.set_trace()
        df["opt_type"] = parts[0]
        df["strike"] = parts[2].astype(float)
        df["expiry"] = parts[3]

        # ---- filter ----
        df = df[df["opt_type"] == option_type.upper()]

        # 🔥 expiry filter (CRITICAL)
        if hasattr(ctx, "selected_expiry"):
            df = df[df["expiry"] == ctx.selected_expiry]

        if df.empty:
            return None

        # ---- 🔥 build LTP per strike ----
        df = df.sort_values("timestamp")

        latest = df.groupby("strike").last().reset_index()

        # ---- 🔥 liquidity filter (avoid fake strikes) ----
        latest = latest[latest["qty"] > 0]

        # ---- premium filter ----
        filtered = latest[(latest["price"] >= min_prem) & (latest["price"] <= max_prem)]

        if filtered.empty:
            return None

        # ---- 🔥 choose best strike ----
        target = (min_prem + max_prem) / 2
        filtered["diff"] = (filtered["price"] - target).abs()

        selected = filtered.sort_values("diff").iloc[0]

        return (selected["strike"], float(selected["price"]), selected)
