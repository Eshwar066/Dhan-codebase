"""
Delta Exchange–specific helpers: tick CSV strike selection (backtest), live strike
selection via ``/v2/products`` + ``/v2/tickers``, product symbol formatting, and live LTP
from strike rows. Import module functions or mix in ``DeltaMktMixins``.
"""

from __future__ import annotations

import csv
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import pandas as pd
import pdb

from core.utils.expiry_resolver import ExpiryResolver
from core.utils.lag_diag import lag_diag_enabled
from run.config import RUN_MODE, RunMode, STRATEGY_JOBS

logger = logging.getLogger(__name__)

_STRIKE_SCAN_FIELDNAMES = (
    "ts_utc",
    "candle_ts",
    "strategy_name",
    "underlying",
    "spot",
    "expiry",
    "opt_letter",
    "symbol",
    "strike",
    "dist_from_spot",
    "trade_side",
    "bid",
    "ask",
    "spread",
    "spread_ratio",
    "ltp",
    "mark_price",
    "delta",
    "abs_delta",
    "gamma",
    "vega",
    "theta",
    "min_prem",
    "max_prem",
    "delta_min",
    "delta_max",
    "max_spread_ratio",
    "target_prem_mid",
    "target_delta",
    "score",
    "reject_reason",
    "eligible",
    "winner",
)


def _strike_scan_csv_path() -> Path:
    base = Path(__file__).resolve().parents[2] / "logs" / "strike_selection"
    override = os.environ.get("ALGO_STRIKE_SCAN_DIR", "").strip()
    if override:
        base = Path(override)
    name = (
        os.environ.get("ALGO_STRIKE_SCAN_FILE", "live_strike_scan.csv").strip()
        or "live_strike_scan.csv"
    )
    return base / name


def _append_live_strike_scan_rows(rows: list[dict[str, Any]]) -> None:
    if os.environ.get("ALGO_STRIKE_SCAN_LOG", "1").strip() == "0" or not rows:
        return
    path = _strike_scan_csv_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    write_header = not path.exists() or path.stat().st_size == 0
    with path.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=_STRIKE_SCAN_FIELDNAMES, extrasaction="ignore")
        if write_header:
            w.writeheader()
        for r in rows:
            w.writerow(r)


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
        weekday = trade_date.weekday()  # Mon=0 ... Fri=4

        # ---- Correct weekly expiry logic ----
        if weekday >= 3:  # Thu (3) or Fri (4)
            days_to_friday = (4 - weekday) + 7
        else:
            days_to_friday = 4 - weekday

        weekly_expiry = trade_date + pd.Timedelta(days=days_to_friday)

        ctx.selected_expiry = pd.Timestamp(weekly_expiry).strftime("%d%m%y")

        return ctx.selected_expiry

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

    def _prepare_live_atm_otm_chain(
        self,
        candle: dict,
        ctx: Any,
        option_type: str,
        *,
        expiry: Optional[str] = None,
        max_quotes: int = 48,
        log_prefix: str = "find_strike_in_premium_range_live",
    ) -> Optional[
        tuple[
            Any,
            str,
            str,
            str,
            float,
            list[tuple[float, float, str, Any]],
            dict[str, Any],
        ]
    ]:
        """
        Shared live setup: DeltaSource, weekly/monthly expiry, ATM+OTM product list
        (sorted by distance to spot), capped ``max_quotes``, and option tickers map.
        """
        source = _delta_source_from_ctx(ctx)
        if source is None:
            logger.warning(
                "%s: DeltaSource not available on context",
                log_prefix,
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

        scored: list[tuple[float, float, str, Any]] = []
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

            if opt_letter == "C":
                if strike < spot:
                    continue
            else:
                if strike > spot:
                    continue

            scored.append((abs(strike - spot), strike, sym, p))

        if not scored:
            logger.warning(
                "%s: no ATM/OTM option products for underlying=%s expiry=%s opt=%s",
                log_prefix,
                und,
                selected_expiry,
                opt_letter,
            )
            return None
        scored.sort(key=lambda x: x[0])
        scored = scored[:max_quotes]

        tickers_map: dict[str, Any] = {}
        if hasattr(source, "get_option_tickers_for_expiry"):
            try:
                api_start = datetime.now() if lag_diag_enabled() else None
                tickers_map = source.get_option_tickers_for_expiry(
                    und, str(selected_expiry), opt_letter
                )
                if lag_diag_enabled() and api_start is not None:
                    logger.debug(
                        "%s: batch tickers API time=%.3fs",
                        log_prefix,
                        (datetime.now() - api_start).total_seconds(),
                    )
            except Exception as e:
                logger.warning(
                    "%s: batch tickers failed (%s); falling back to per-symbol get_ticker",
                    log_prefix,
                    e,
                )
                tickers_map = {}
        if tickers_map:
            logger.debug(
                "%s: batch tickers map size=%s",
                log_prefix,
                len(tickers_map),
            )

        return source, und, selected_expiry, opt_letter, spot, scored, tickers_map

    def find_strike_by_delta_live(
        self,
        candle,
        ctx,
        option_type,
        expiry=None,
        *,
        target_delta=None,
        delta_min=None,
        delta_max=None,
        side="SELL",
        max_quotes=48,
        require_quotes: bool = True,
    ):
        """
        Live/paper: pick the ATM/OTM strike whose **|delta|** is closest to
        ``target_delta``. No premium or spread filters—only valid ticker + greeks.

        - **Calls** (``C``): ``strike >= spot``.
        - **Puts** (``P``): ``strike <= spot``.

        If ``delta_min`` / ``delta_max`` are set, only strikes with
        ``delta_min <= |delta| <= delta_max`` are considered.

        Returns ``(strike, ltp, row)`` like ``find_strike_in_premium_range_live``, or
        ``None`` if no candidate has a usable delta (and quotes when ``require_quotes``).
        """
        prepared = self._prepare_live_atm_otm_chain(
            candle,
            ctx,
            option_type,
            expiry=expiry,
            max_quotes=max_quotes,
            log_prefix="find_strike_by_delta_live",
        )
        # pdb.set_trace()
        if prepared is None:
            return None
        source, und, selected_expiry, opt_letter, spot, scored, tickers_map = prepared

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
                pass

        if target_delta is None:
            if delta_min is not None and delta_max is not None:
                target_delta = (float(delta_min) + float(delta_max)) / 2.0
            else:
                target_delta = 0.25

        trade_side = str(side or "SELL").upper()

        best: Optional[tuple[float, float, str, float, float, float, float]] = None
        best_delta_dist: Optional[float] = None
        best_spot_dist: Optional[float] = None

        for spot_dist, strike, sym, _prod in scored:
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
                if require_quotes and (bid <= 0 or ask <= 0):
                    continue
                spread = ask - bid if bid > 0 and ask > 0 else 0.0
                ltp = ask if trade_side == "BUY" else bid
                if require_quotes and ltp <= 0:
                    continue

                raw_delta = greeks.get("delta")
                if raw_delta is None:
                    continue
                delta = float(raw_delta)
                abs_delta = abs(delta)
                if abs_delta <= 0 and target_delta > 0:
                    continue
                if delta_min is not None and abs_delta < float(delta_min):
                    continue
                if delta_max is not None and abs_delta > float(delta_max):
                    continue

                ddist = abs(abs_delta - float(target_delta))
                if best is None:
                    best = (strike, ltp, sym, bid, ask, spread, delta)
                    best_delta_dist = ddist
                    best_spot_dist = spot_dist
                    continue
                if best_delta_dist is None:
                    continue
                if ddist < best_delta_dist - 1e-12:
                    best = (strike, ltp, sym, bid, ask, spread, delta)
                    best_delta_dist = ddist
                    best_spot_dist = spot_dist
                elif (
                    abs(ddist - best_delta_dist) <= 1e-12 and best_spot_dist is not None
                ):
                    if spot_dist < best_spot_dist:
                        best = (strike, ltp, sym, bid, ask, spread, delta)
                        best_delta_dist = ddist
                        best_spot_dist = spot_dist
            except Exception:
                continue

        if best is None:
            logger.info(
                "find_strike_by_delta_live: no strike with usable delta (underlying=%s expiry=%s)",
                und,
                selected_expiry,
            )
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

        Only **ATM and OTM** strikes are considered (ITM excluded):
        - **Calls** (``C``): ``strike >= spot`` (spot = ``candle["close"]``).
        - **Puts** (``P``): ``strike <= spot``.

        Uses one batch ``GET /v2/tickers`` when
        ``DeltaSource.get_option_tickers_for_expiry`` is available; falls back to
        per-symbol ``get_ticker`` if the batch fails or misses a symbol.

        ``lookback_sec`` is unused (kept for signature parity with CSV path).
        """

        del lookback_sec
        prepared = self._prepare_live_atm_otm_chain(
            candle,
            ctx,
            option_type,
            expiry=expiry,
            max_quotes=48,
            log_prefix="find_strike_in_premium_range_live",
        )
        if prepared is None:
            return None
        source, und, selected_expiry, opt_letter, spot, scored, tickers_map = prepared

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
                pass

        if delta_min is None:
            delta_min = 0.15
        if delta_max is None:
            delta_max = 0.35
        if target_delta is None:
            target_delta = (delta_min + delta_max) / 2.0

        trade_side = str(side or "SELL").upper()

        scan_rows: list[dict[str, Any]] = []
        ts_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        candle_ts = str(candle.get("timestamp", ""))
        strategy_nm = str(getattr(self, "name", "") or "")

        for _, strike, sym, _prod in scored:
            rec: dict[str, Any] = {
                "ts_utc": ts_utc,
                "candle_ts": candle_ts,
                "strategy_name": strategy_nm,
                "underlying": und,
                "spot": spot,
                "expiry": selected_expiry,
                "opt_letter": opt_letter,
                "symbol": sym,
                "strike": strike,
                "dist_from_spot": round(abs(strike - spot), 8),
                "trade_side": trade_side,
                "min_prem": min_prem,
                "max_prem": max_prem,
                "delta_min": delta_min,
                "delta_max": delta_max,
                "max_spread_ratio": max_spread_ratio,
                "target_prem_mid": target,
                "target_delta": target_delta,
                "bid": "",
                "ask": "",
                "spread": "",
                "spread_ratio": "",
                "ltp": "",
                "mark_price": "",
                "delta": "",
                "abs_delta": "",
                "gamma": "",
                "vega": "",
                "theta": "",
                "score": "",
                "reject_reason": "",
                "eligible": "",
                "winner": "N",
            }
            try:
                sym_u = (sym or "").upper()
                t = tickers_map.get(sym_u) if tickers_map else None
                if t is None:
                    t = source.get_ticker(sym)

                if not isinstance(t, dict):
                    rec["reject_reason"] = "no_ticker"
                    scan_rows.append(rec)
                    continue
                quotes = t.get("quotes") or {}
                greeks = t.get("greeks") or {}
                mp = t.get("mark_price")
                rec["mark_price"] = mp if mp is not None else ""

                bid = float(quotes.get("best_bid") or 0)
                ask = float(quotes.get("best_ask") or 0)
                rec["bid"] = bid
                rec["ask"] = ask
                if bid <= 0 or ask <= 0:
                    rec["reject_reason"] = "missing_bid_ask"
                    scan_rows.append(rec)
                    continue

                spread = ask - bid
                rec["spread"] = spread
                rec["spread_ratio"] = round(spread / ask, 8) if ask > 0 else ""
                if spread < 0:
                    rec["reject_reason"] = "negative_spread"
                    scan_rows.append(rec)
                    continue
                if ask > 0 and (spread / ask) > max_spread_ratio:
                    rec["reject_reason"] = "spread_too_wide"
                    scan_rows.append(rec)
                    continue

                ltp = ask if trade_side == "BUY" else bid
                rec["ltp"] = ltp
                delta = float(greeks.get("delta") or 0)
                abs_delta = abs(delta)
                rec["delta"] = delta
                rec["abs_delta"] = abs_delta
                if greeks:
                    for gk in ("gamma", "vega", "theta"):
                        if gk in greeks and greeks[gk] is not None:
                            rec[gk] = greeks.get(gk)

                if ltp <= 0:
                    rec["reject_reason"] = "ltp_non_positive"
                    scan_rows.append(rec)
                    continue
                if not (delta_min <= abs_delta <= delta_max):
                    rec["reject_reason"] = "delta_out_of_range"
                    scan_rows.append(rec)
                    continue
                if not (min_prem <= ltp <= max_prem):
                    rec["reject_reason"] = "premium_out_of_range"
                    scan_rows.append(rec)
                    continue

                score = (
                    abs(ltp - target) * 0.6
                    + spread * 0.3
                    + abs(abs_delta - target_delta) * 0.1
                )
                rec["score"] = round(score, 8)
                rec["eligible"] = "Y"
                scan_rows.append(rec)

                if best is None or score < best_score:
                    best = (strike, ltp, sym, bid, ask, spread, delta)
                    best_score = score
            except Exception as e:
                rec["reject_reason"] = f"exception:{e!s}"
                scan_rows.append(rec)
                continue

        if scan_rows:
            if best is not None:
                bstrike, _, bsym, _, _, _, _ = best
                for r in scan_rows:
                    if (
                        r.get("eligible") == "Y"
                        and (r.get("symbol") or "").upper() == (bsym or "").upper()
                        and float(r.get("strike", 0)) == float(bstrike)
                    ):
                        r["winner"] = "Y"
                        break
            _append_live_strike_scan_rows(scan_rows)
            logger.debug(
                "find_strike_in_premium_range_live: wrote %s strike scan row(s) -> %s",
                len(scan_rows),
                _strike_scan_csv_path(),
            )

        if best is None:
            logger.info(
                "find_strike_in_premium_range_live: no strike passed "
                "premium/delta/spread among ATM/OTM candidates (underlying=%s expiry=%s)",
                und,
                selected_expiry,
            )
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

    def is_delta_testnet_enabled(self) -> bool:
        """
        Resolve whether current strategy job enables Delta testnet behavior.
        Expects strategy class to define ``name``.
        """
        strategy_name = str(getattr(self, "name", ""))
        if not strategy_name:
            return False
        for job in STRATEGY_JOBS:
            if str(job.get("name")) != strategy_name:
                continue
            if str(job.get("venue", "")).upper() != "DELTA":
                continue
            return bool(job.get("delta_testnet", False))
        return False

    def resolved_option_type_ce_pe(self, inst: Any) -> str:
        """
        Resolve CE/PE for Delta option instruments.
        Delta may leave ``instrument.option_type`` empty while trading_symbol
        contains ``P-`` / ``C-`` prefixes.
        """
        raw = getattr(inst, "option_type", None)
        if raw is not None and str(raw).strip():
            s = str(raw).strip().upper()
            if s in ("PE", "PUT", "P"):
                return "PE"
            if s in ("CE", "CALL", "C"):
                return "CE"
        sym = (
            getattr(inst, "trading_symbol", None)
            or getattr(inst, "custom_symbol", None)
            or ""
        )
        su = str(sym).strip().upper()
        if len(su) >= 2 and su[0] == "P" and su[1] == "-":
            return "PE"
        if len(su) >= 2 and su[0] == "C" and su[1] == "-":
            return "CE"
        return ""

    def find_strike_in_premium_range_by_mode(
        self,
        candle,
        ctx,
        option_type,
        *,
        min_prem=600,
        max_prem=1500,
        lookback_sec=60,
        expiry="Weekly",
        side="SELL",
        target_delta=None,
        delta_min=None,
        delta_max=None,
        max_spread_ratio=0.15,
    ):
        """
        Strategy-facing strike selection router:
        - backtest: tick CSV path
        - live/paper testnet: permissive live selection
        - live/paper prod: live selection with configured delta filters
        """
        # pdb.set_trace()
        if RUN_MODE == RunMode.BACKTEST:
            return DeltaMktMixins.find_strike_in_premium_range(
                self,
                candle,
                ctx,
                option_type,
                min_prem=min_prem,
                max_prem=max_prem,
                lookback_sec=lookback_sec,
                expiry=expiry,
            )
        if self.is_delta_testnet_enabled():
            return DeltaMktMixins.find_strike_in_premium_range_live(
                self,
                candle,
                ctx,
                option_type,
                min_prem=10,
                max_prem=2500,
                lookback_sec=lookback_sec,
                expiry=expiry,
                side=side,
                target_delta=0.1,
                delta_min=0.01,
                delta_max=1,
                max_spread_ratio=20,
            )
        return DeltaMktMixins.find_strike_by_delta_live(
            self,
            candle,
            ctx,
            option_type,
            # min_prem=min_prem,
            # max_prem=max_prem,
            # lookback_sec=lookback_sec,
            expiry=expiry,
            side=side,
            target_delta=target_delta,
            delta_min=delta_min,
            delta_max=delta_max,
            # max_spread_ratio=max_spread_ratio,
        )

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
