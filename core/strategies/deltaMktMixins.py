"""
Delta Exchange–specific helpers: tick CSV strike selection (backtest), live strike
selection via ``/v2/products`` + ``/v2/tickers``, product symbol formatting, and live LTP
from strike rows. Import module functions or mix in ``DeltaMktMixins``.
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import pandas as pd
import pdb

from core.utils.expiry_resolver import ExpiryResolver
from core.utils.lag_diag import lag_diag_enabled

logger = logging.getLogger(__name__)


def delta_option_trading_symbol(
    row: Any,
    strike: float,
    option_type: str,
    expiry_ddmmyy: str,
) -> str:
    """
    Delta ``/v2/products`` option symbol, e.g. ``P-BTC-70400-210326``.
    Prefer ``symbol`` from a tick/chain row; else build ``{P|C}-BTC-{strike}-{DDMMYY}``.
    """
    if row is not None:
        sym = row.get("symbol") if hasattr(row, "get") else None
        if sym is not None and str(sym).strip():
            return str(sym).strip()
    opt = (option_type or "CE").upper()
    letter = "P" if opt in ("PE", "PUT") else "C"
    return f"{letter}-BTC-{int(float(strike))}-{expiry_ddmmyy}"


def ltp_from_strike_row_live(strike_row) -> float:
    """
    Live/paper option LTP from a strike row (DataFrame row or Series).
    Dhan chains use ``close``; Delta tick rows use ``price``.
    """
    if strike_row is None:
        return 0.0
    row = (
        strike_row.iloc[0]
        if hasattr(strike_row, "iloc")
        and not isinstance(strike_row, pd.Series)
        and len(strike_row) > 0
        else strike_row
    )
    if isinstance(row, pd.Series):
        for key in ("price", "close", "mark_price"):
            if key in row.index and pd.notna(row.get(key)):
                return float(row[key])
    return 0.0


def _delta_underlying_prefix(underlying: str) -> str:
    """``BTCUSD`` -> ``BTC`` for Delta option symbols ``P-BTC-...``."""
    u = (underlying or "BTCUSD").upper()
    if u.endswith("USD"):
        u = u[:-3]
    return u


def _delta_source_from_ctx(ctx: Any):
    """
    Resolve ``DeltaSource`` from ``ctx.option_chain_service`` (``DataRouter`` uses the
    same data provider for ``DHAN`` / ``NSE`` adapters; Delta engines attach ``DeltaDataProvider``).
    """
    ocs = getattr(ctx, "option_chain_service", None)
    if ocs is None:
        return None
    dr = getattr(ocs, "data_router", None)
    if dr is None:
        return None
    ad = dr.adapters.get("DHAN")
    if ad is None:
        return None
    data = getattr(ad, "data", None)
    if data is None:
        return None
    src = getattr(data, "_source", None)
    if src is not None and hasattr(src, "get_products"):
        return src
    return None


class DeltaMktMixins:
    """Shared Delta option helpers and tick/CSV strike selection. Reuse via mixin or module functions."""

    delta_option_trading_symbol = staticmethod(delta_option_trading_symbol)
    ltp_from_strike_row_live = staticmethod(ltp_from_strike_row_live)

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

        ctx.delta_data = df
        self._delta_cache_date = trade_date
        self._delta_cache_file = file_path
        self._delta_cache_df = df
        return df

    def weeklyExpiry(self, candle: dict, ctx: Any):
        ts = pd.to_datetime(candle["timestamp"]).tz_localize(None)
        trade_date = ts.date()
        weekday = trade_date.weekday()  # Mon=0 ... Thu=3 ... Fri=4

        # ---- Weekly expiry logic ----
        if weekday == 3:  # Thursday → next Friday
            days_to_friday = 8
        else:
            days_to_friday = 4 - weekday
            if days_to_friday < 0:
                days_to_friday += 7

        weekly_expiry = trade_date + pd.Timedelta(days=days_to_friday)

        # 🔥 Convert to DDMMYY format (matches your data)
        ctx.selected_expiry = pd.Timestamp(weekly_expiry).strftime("%d%m%y")
        return pd.Timestamp(weekly_expiry).strftime("%d%m%y")

    def monthlyExpiry(self, candle: dict, ctx: Any):
        """Monthly expiry label ``DDMMYY`` (last Thursday month roll); aligns with ``ExpiryResolver`` NSE-style month."""
        ts = pd.to_datetime(candle["timestamp"]).tz_localize(None)
        trade_date = ts.date()
        if trade_date.day > 15:
            expiry_date = ExpiryResolver.next_month_expiry(trade_date)
        else:
            expiry_date = ExpiryResolver.current_month_expiry(trade_date)
        s = expiry_date.strftime("%d%m%y")
        ctx.selected_expiry = s
        return s

    def find_strike_in_premium_range(
        self,
        candle,
        ctx,
        option_type,
        expiry=None,
        min_prem=700,
        max_prem=1400,
        lookback_sec=600,
    ):
        df = self.load_delta_data_for_candle(candle, ctx)

        if df is None or df.empty:
            return None

        df.columns = [
            "symbol",
            "price",
            "qty",
            "timestamp",
            "side",
            "opt_type",
            "strike",
            "expiry",
        ]
        df["timestamp"] = pd.to_datetime(df["timestamp"])

        candle_time = pd.to_datetime(candle["timestamp"]).tz_localize(None)

        # ---- 🔥 parse symbol ----
        parts = df["symbol"].str.split("-", expand=True)

        df["opt_type"] = parts[0]
        df["strike"] = parts[2].astype(float)
        df["expiry"] = parts[3]  # e.g. 010226
        # ---- 🔥 resolve expiry ----
        if expiry == "Weekly":
            selected_expiry = self.weeklyExpiry(candle, ctx)
        elif expiry == "Monthly":
            selected_expiry = self.monthlyExpiry(candle, ctx)
        else:
            selected_expiry = ctx.selected_expiry  # fallback

        if selected_expiry is None:
            print(">>select expiry")
            return None

        # ---- 🔥 1. filter exact expiry ----
        df = df[df["expiry"] == selected_expiry]

        if df.empty:
            return None

        # ---- 🔥 2. filter by candle DATE ----
        candle_date = candle_time.date()
        df = df[df["timestamp"].dt.date == candle_date]

        if df.empty:
            return None

        # ---- 3. filter option type ----
        opt = option_type.strip().upper()[0]  # takes first letter safely
        df = df[df["opt_type"] == opt]

        if df.empty:
            return None

        # ---- 🔥 time filter ----
        start_time = candle_time - pd.Timedelta(seconds=600)
        end_time = candle_time + pd.Timedelta(seconds=600)

        df = df[(df["timestamp"] >= start_time) & (df["timestamp"] <= end_time)]

        if df.empty:
            return None

        # ---- 🔥 LTP per strike at candle time ----
        df = df.sort_values("timestamp")

        latest = df.groupby("strike", as_index=False).last()

        # ---- liquidity filter ----
        latest = latest[latest["qty"] > 0]
        # ---- premium range ----
        filtered = latest[(latest["price"] >= min_prem) & (latest["price"] <= max_prem)]

        if filtered.empty:
            return None

        # ---- 🔥 best strike selection ----
        target = (min_prem + max_prem) / 2

        filtered = filtered.copy()  # avoid pandas warning
        filtered["diff"] = (filtered["price"] - target).abs()

        selected = filtered.sort_values("diff").iloc[0]

        return (selected["strike"], float(selected["price"]), selected)

    def find_strike_in_premium_range_live(
        self,
        candle,
        ctx,
        option_type,
        expiry=None,
        min_prem=700,
        max_prem=1400,
        lookback_sec=600,
        side="SELL",
        target_delta=None,
        delta_min=None,
        delta_max=None,
        max_spread_ratio=0.15,
    ):
        """
        Live/paper: strike + premium from Delta ``/v2/products`` and tickers.

        Uses one batch ``GET /v2/tickers`` (underlying + expiry + call/put) when
        ``DeltaSource.get_option_tickers_for_expiry`` is available; falls back to
        per-symbol ``get_ticker`` if the batch fails or misses a symbol.

        ``lookback_sec`` is unused (kept for signature parity with CSV path).
        """

        del lookback_sec
        source = _delta_source_from_ctx(ctx)
        if source is None:
            logger.warning(
                "find_strike_in_premium_range_live: DeltaSource not available on context"
            )
            return None

        if expiry == "Weekly":
            selected_expiry = self.weeklyExpiry(candle, ctx)
        elif expiry == "Monthly":
            selected_expiry = self.monthlyExpiry(candle, ctx)
        else:
            selected_expiry = getattr(
                ctx, "selected_expiry", None
            ) or self.weeklyExpiry(candle, ctx)

        opt_letter = option_type.strip().upper()[0]
        und = _delta_underlying_prefix(candle.get("symbol", "BTCUSD"))

        products = source.get_products(use_cache=True) or []
        spot = float(candle["close"])
        step = 500
        atm = round(spot / step) * step

        scored = []
        for p in products:
            sym = (p.get("symbol") or "").upper()
            if not sym.startswith(f"{opt_letter}-{und}-"):
                continue
            parts = sym.split("-")
            if len(parts) < 4 or parts[-1] != selected_expiry:
                continue
            strike = p.get("strike_price")
            if strike is None:
                try:
                    strike = float(parts[2])
                except (ValueError, TypeError):
                    continue
            else:
                strike = float(strike)
            scored.append((abs(strike - atm), strike, sym, p))

        if not scored:
            return None
        scored.sort(key=lambda x: x[0])
        max_quotes = 48
        scored = scored[:max_quotes]

        target = (min_prem + max_prem) / 2
        best = None
        best_score = None

        strategy_delta = getattr(self, "delta", None)
        if target_delta is None and strategy_delta is not None:
            try:
                target_delta = float(strategy_delta)
            except (TypeError, ValueError):
                target_delta = None

        strategy_delta_range = getattr(self, "delta_range", None)
        if (
            (delta_min is None or delta_max is None)
            and isinstance(strategy_delta_range, (tuple, list))
            and len(strategy_delta_range) == 2
        ):
            try:
                delta_min = float(strategy_delta_range[0])
                delta_max = float(strategy_delta_range[1])
            except (TypeError, ValueError):
                delta_min = delta_min
                delta_max = delta_max

        if delta_min is None:
            delta_min = 0.15
        if delta_max is None:
            delta_max = 0.35
        if target_delta is None:
            target_delta = (delta_min + delta_max) / 2.0

        trade_side = str(side or "SELL").upper()

        # One batch REST call for this underlying + expiry + call/put (avoids N× get_ticker).
        tickers_map: dict[str, Any] = {}
        if hasattr(source, "get_option_tickers_for_expiry"):
            try:
                api_start = datetime.now() if lag_diag_enabled() else None
                tickers_map = source.get_option_tickers_for_expiry(
                    und, str(selected_expiry), opt_letter
                )
                if lag_diag_enabled() and api_start is not None:
                    print(
                        "🌐 API time:",
                        (datetime.now() - api_start).total_seconds(),
                    )
            except Exception as e:
                logger.warning(
                    "find_strike_in_premium_range_live: batch tickers failed (%s); "
                    "falling back to per-symbol get_ticker",
                    e,
                )
                tickers_map = {}
        if tickers_map:
            logger.debug(
                "find_strike_in_premium_range_live: batch tickers map size=%s",
                len(tickers_map),
            )

        for _, strike, sym, _prod in scored:
            try:
                sym_u = (sym or "").upper()
                t = tickers_map.get(sym_u) if tickers_map else None
                if t is None:
                    t = source.get_ticker(sym)

                if not isinstance(t, dict):
                    continue
                quotes = t.get("quotes") or {}
                greeks = t.get("greeks") or {}

                bid = float(quotes.get("best_bid") or 0)
                ask = float(quotes.get("best_ask") or 0)
                if bid <= 0 or ask <= 0:
                    continue

                spread = ask - bid
                if spread < 0:
                    continue
                if (spread / ask) > max_spread_ratio:
                    continue

                ltp = ask if trade_side == "BUY" else bid
                delta = float(greeks.get("delta") or 0)
                abs_delta = abs(delta)
            except Exception:
                continue
            if ltp <= 0:
                continue
            if not (delta_min <= abs_delta <= delta_max):
                continue
            if min_prem <= ltp <= max_prem:
                score = (
                    abs(ltp - target) * 0.6
                    + spread * 0.3
                    + abs(abs_delta - target_delta) * 0.1
                )
                if best is None or score < best_score:
                    best = (strike, ltp, sym, bid, ask, spread, delta)
                    best_score = score

        if best is None:
            return None
        strike, ltp, sym, bid, ask, spread, delta = best
        row = pd.Series(
            {
                "symbol": sym,
                "price": ltp,
                "strike": strike,
                "close": ltp,
                "qty": 1,
                "best_bid": bid,
                "best_ask": ask,
                "spread": spread,
                "delta": delta,
            }
        )
        return strike, ltp, row

    def find_strike(self, strike, expiry):
        df = self.load_delta_data_for_candle(candle, ctx)

        if df is None or df.empty:
            return None

        df.columns = ["symbol", "price", "qty", "timestamp", "side"]
        df["timestamp"] = pd.to_datetime(df["timestamp"])

        candle_time = pd.to_datetime(candle["timestamp"]).tz_localize(None)

        # ---- 🔥 parse symbol ----
        parts = df["symbol"].str.split("-", expand=True)

        df["opt_type"] = parts[0]
        df["strike"] = parts[2].astype(float)
        df["expiry"] = parts[3]  # e.g. 010226
        # ---- 🔥 resolve expiry ----
        if expiry == "Weekly":
            selected_expiry = self.weeklyExpiry(candle, ctx)
        elif expiry == "Monthly":
            selected_expiry = self.monthlyExpiry(candle, ctx)
        else:
            selected_expiry = ctx.selected_expiry  # fallback

        df = df[df["strike"] == strike]
        df = df[df["expiry"] == selected_expiry]
        candle_date = candle_time.date()
        df = df[df["timestamp"].dt.date == candle_date]
        opt = option_type.strip().upper()[0]  # takes first letter safely
        df = df[df["opt_type"] == opt]
        start_time = candle_time - pd.Timedelta(seconds=600)
        df = df[(df["timestamp"] >= start_time) & (df["timestamp"] <= candle_time)]
