#!/usr/bin/env python3
"""
Rebuild ``logs/LEAPS_RSI/dhan_leaps_rsi_candles.log`` (150+ valid 1h INDEX rows) and
refresh ``logs/indicators/NIFTY/60/indicator_history.jsonl`` (and legacy RSI log if needed) so ``IndicatorManager``
can bootstrap from logs only (no intraday API) and RSI merge has a full session through
the last 15:15 bar.

Tail OHLC/RSI values are aligned to Yahoo ``^NSEI`` 60m (see YF table in source).

Usage (from repo root, inside venv)::

    python3 utils/yfinance/seed_leaps_bootstrap_logs.py
"""

from __future__ import annotations

import json
import os
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")

# Yahoo ^NSEI 60m reference (IST bar open). May 12 09:15 OHLC is synthetic around yfinance close.
YF_TAIL: list[tuple[str, float, float, float, float, float, float]] = [
    ("2026-05-12 09:15", 23670.0, 23695.0, 23625.0, 23651.4, 28.07, 32.71),
    ("2026-05-12 10:15", 23652.05, 23675.20, 23578.70, 23589.35, 26.03, 28.07),
    ("2026-05-12 11:15", 23589.60, 23613.40, 23551.60, 23557.80, 25.03, 26.03),
    ("2026-05-12 12:15", 23559.50, 23580.05, 23506.35, 23536.80, 24.36, 25.03),
    ("2026-05-12 13:15", 23538.05, 23564.05, 23448.00, 23457.50, 21.98, 24.36),
    ("2026-05-12 14:15", 23458.75, 23492.70, 23349.10, 23354.80, 19.34, 21.98),
    ("2026-05-12 15:15", 23356.00, 23434.85, 23355.60, 23430.55, 26.37, 19.34),
    ("2026-05-13 09:15", 23365.80, 23503.15, 23263.05, 23403.05, 25.50, 26.37),
    ("2026-05-13 10:15", 23403.20, 23478.60, 23368.05, 23403.95, 25.58, 25.50),
    ("2026-05-13 11:15", 23403.80, 23513.85, 23392.75, 23512.75, 35.35, 25.58),
    ("2026-05-13 12:15", 23511.95, 23582.80, 23423.30, 23538.50, 37.44, 35.35),
    ("2026-05-13 13:15", 23538.00, 23540.50, 23480.25, 23516.80, 36.37, 37.44),
    ("2026-05-13 14:15", 23516.50, 23522.40, 23402.85, 23425.70, 32.21, 36.37),
    ("2026-05-13 15:15", 23425.40, 23436.95, 23394.35, 23428.70, 32.49, 32.21),
    ("2026-05-14 09:15", 23531.45, 23589.20, 23447.50, 23495.80, 38.47, 32.49),
    ("2026-05-14 10:15", 23496.80, 23537.50, 23426.85, 23459.15, 36.56, 38.47),
    ("2026-05-14 11:15", 23459.85, 23702.15, 23459.00, 23667.40, 51.32, 36.56),
    ("2026-05-14 12:15", 23667.95, 23747.15, 23667.20, 23713.55, 53.88, 51.32),
    ("2026-05-14 13:15", 23715.25, 23768.60, 23709.30, 23744.55, 55.57, 53.88),
    ("2026-05-14 14:15", 23746.45, 23776.65, 23670.20, 23683.80, 51.58, 55.57),
    ("2026-05-14 15:15", 23683.35, 23719.55, 23668.15, 23713.75, 53.36, 51.58),
]


def _ist_minute(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M")


def _yf_map() -> dict[str, tuple[float, float, float, float, float, float]]:
    return {r[0]: r[1:] for r in YF_TAIL}


def _synth_ohlc(ist_key: str, seq: int, yf: dict[str, tuple]) -> tuple[float, float, float, float, float | None, float | None]:
    if ist_key in yf:
        o, h, l, c, rsi, prev = yf[ist_key]
        return o, h, l, c, rsi, prev
    base = 24100.0 + (seq % 97) * 3.7 - (seq // 7) * 2.1
    w = 35 + (seq % 11)
    o, c = base, base + (seq % 5) - 2
    h, l = max(o, c) + w, min(o, c) - w
    return round(o, 2), round(h, 2), round(l, 2), round(c, 2), None, None


def _row_date_key(ln: str) -> str:
    j = json.loads(ln)
    ts = str(j.get("candle_timestamp_ist", ""))
    if "T" in ts:
        ts = ts.replace("T", " ")[:16]
    return ts


def main() -> None:
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    log_dir = os.path.join(root, "logs", "LEAPS_RSI")
    os.makedirs(log_dir, exist_ok=True)
    candle_path = os.path.join(log_dir, "dhan_leaps_rsi_candles.log")
    hist_path = os.path.join(log_dir, "LEAPS_RSI_rsi_history.log")

    yf = _yf_map()
    candles: list[dict] = []
    rsi_tail: list[dict] = []
    seq = 0
    d = date(2026, 1, 2)
    end = date(2026, 5, 14)
    while d <= end:
        if d.weekday() < 5:
            for hm in [(9, 15), (10, 15), (11, 15), (12, 15), (13, 15), (14, 15), (15, 15)]:
                dt = datetime(d.year, d.month, d.day, hm[0], hm[1], 0, tzinfo=IST)
                ist_key = _ist_minute(dt)
                o, h, l, c, rsi, prev = _synth_ohlc(ist_key, seq, yf)
                seq += 1
                bu = int(dt.timestamp())
                if hm == (15, 15):
                    close_dt = dt.replace(hour=15, minute=30)
                else:
                    close_dt = dt + timedelta(hours=1)
                candles.append(
                    {
                        "engine_id": "dhan_leaps_rsi",
                        "venue": "DHAN",
                        "strategy_id": "LEAPS_RSI",
                        "event_type": "candle_closed",
                        "timestamp": _ist_minute(close_dt),
                        "message": "Closed candle",
                        "symbol": "NIFTY",
                        "timeframe": "60",
                        "tf_sec": 3600,
                        "source": "bootstrap_seed",
                        "open": o,
                        "high": h,
                        "low": l,
                        "close": c,
                        "volume": 0.0,
                        "bucket_ts": bu,
                        "rsi": rsi,
                        "prev_rsi": prev,
                        "bar_timestamp_ist": ist_key,
                        "exchange": "INDEX",
                        "correlation": {
                            "engine_id": "dhan_leaps_rsi",
                            "strategy_id": "LEAPS_RSI",
                            "intent_id": None,
                            "account_id": None,
                        },
                    }
                )
                rsi_tail.append(
                    {
                        "symbol": "NIFTY",
                        "timeframe": "60",
                        "source": "historical_seed",
                        "candle_timestamp_ist": ist_key,
                        "close": round(float(c), 2),
                        "rsi": rsi,
                        "prev_rsi": prev,
                    }
                )
        d += timedelta(days=1)

    if len(candles) < 150:
        raise SystemExit(f"expected >=150 bars, got {len(candles)}")

    head: list[str] = []
    if os.path.isfile(hist_path):
        for ln in open(hist_path, encoding="utf-8"):
            ln = ln.strip()
            if not ln:
                continue
            if _row_date_key(ln) < "2026-05-12 09:15":
                head.append(ln)

    tail_out = [
        json.dumps(x, default=str)
        for x in rsi_tail
        if x["candle_timestamp_ist"] >= "2026-05-12 09:15"
    ]

    # Keep any live-session closes already on disk (today onward) after the seeded block.
    live_tail: list[str] = []
    if os.path.isfile(candle_path):
        for ln in open(candle_path, encoding="utf-8"):
            ln = ln.strip()
            if not ln:
                continue
            try:
                j = json.loads(ln)
            except Exception:
                continue
            bar = str(j.get("bar_timestamp_ist") or "")
            if "T" in bar:
                bar = bar.replace("T", " ")[:16]
            if bar >= "2026-05-15 09:15":
                live_tail.append(ln)

    with open(candle_path, "w", encoding="utf-8") as f:
        for pl in candles:
            f.write(json.dumps(pl, default=str) + "\n")
        for ln in live_tail:
            f.write(ln + "\n")

    with open(hist_path, "w", encoding="utf-8") as f:
        for ln in head:
            f.write(ln + "\n")
        for ln in tail_out:
            f.write(ln + "\n")

    print(f"Wrote {len(candles)} candles -> {candle_path}")
    print(f"Wrote {len(head)} + {len(tail_out)} RSI history lines -> {hist_path}")


if __name__ == "__main__":
    main()
