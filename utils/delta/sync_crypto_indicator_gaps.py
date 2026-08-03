#!/usr/bin/env python3
"""
Watch crypto indicator JSONL for BTCUSD / PAXGUSD and backfill gaps via Delta REST.

Checks every configured timeframe under::

    logs/indicators/{SYMBOL}/{tf}/indicator_history.jsonl

A TF is considered stale when the last stored bar is **more than one candle**
behind the latest *closed* exchange bar (or the file is missing). Optional
internal gap scan flags holes larger than one bar in recent history.

On gap, runs ``refresh_crypto_indicator_history.py`` (same commands as that
script's docstring examples), e.g.::

    python utils/delta/refresh_crypto_indicator_history.py --symbol BTCUSD --only 60,4h,1d --no-cache
    python utils/delta/refresh_crypto_indicator_history.py --symbol BTCUSD --only 1 --no-cache
    python utils/delta/refresh_crypto_indicator_history.py --symbol PAXGUSD --only 4h --days 90 --no-cache

Usage (from repo root)::

    # One-shot (startup / cron)
    python utils/delta/sync_crypto_indicator_gaps.py
    python utils/delta/sync_crypto_indicator_gaps.py --dry-run

    # Startup check, then every hour
    python utils/delta/sync_crypto_indicator_gaps.py --loop --interval 3600

    python utils/delta/sync_crypto_indicator_gaps.py --symbols BTCUSD,PAXGUSD --only 60,4h,1d
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Iterable, List, Optional, Sequence, Tuple
from zoneinfo import ZoneInfo

_DELTA_UTILS_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(os.path.dirname(_DELTA_UTILS_DIR))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from core.data.candle_aggregator import _resolution_to_seconds  # noqa: E402
from core.utils.indicator_history import (  # noqa: E402
    indicator_history_path,
    normalize_ist_bar_key,
    parse_bar_timestamp_ist_to_aware,
)

# Keep in sync with refresh_crypto_indicator_history (5m excluded for now).
SUPER_TREND_TIMEFRAMES = ("60", "4h", "1d")
STRUCTURE_TIMEFRAMES = ("1",)
ALL_TIMEFRAMES = SUPER_TREND_TIMEFRAMES + STRUCTURE_TIMEFRAMES

DEFAULT_SYMBOLS = ("BTCUSD", "PAXGUSD")
DEFAULT_DAYS_BY_TF = {
    "1": 14,
    "60": 60,
    "4h": 120,
    "1d": 365,
}

IST = ZoneInfo("Asia/Kolkata")
REFRESH_SCRIPT = os.path.join(_DELTA_UTILS_DIR, "refresh_crypto_indicator_history.py")

logger = logging.getLogger("sync_crypto_indicator_gaps")


@dataclass(frozen=True)
class GapFinding:
    symbol: str
    timeframe: str
    reason: str
    last_bar_ist: Optional[str]
    expected_closed_ist: str
    lag_bars: float


def _parse_csv_list(raw: Optional[str], default: Sequence[str]) -> List[str]:
    if not raw:
        return [str(x) for x in default]
    out: List[str] = []
    for part in str(raw).split(","):
        item = part.strip()
        if not item:
            continue
        if item in ("1h", "60m"):
            item = "60"
        if item not in out:
            out.append(item)
    return out


def _normalize_tf(tf: str) -> str:
    t = str(tf or "").strip()
    if t in ("1h", "60m"):
        return "60"
    return t


def _tf_seconds(tf: str) -> int:
    return max(60, int(_resolution_to_seconds(_normalize_tf(tf))))


def _expected_last_closed_open(now_ts: Optional[float], tf: str) -> datetime:
    """UTC-aware open time of the latest fully closed bar for ``tf``."""
    tf_sec = _tf_seconds(tf)
    now = float(now_ts if now_ts is not None else time.time())
    forming_open = int(now) - (int(now) % tf_sec)
    last_closed_open = forming_open - tf_sec
    return datetime.fromtimestamp(last_closed_open, tz=IST)


def _last_bar_from_jsonl(path: str) -> Tuple[Optional[str], Optional[datetime]]:
    if not os.path.isfile(path):
        return None, None
    last_key: Optional[str] = None
    # Prefer max key (file may not be strictly sorted after merges).
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                key = normalize_ist_bar_key(row.get("candle_timestamp_ist"))
                if not key:
                    continue
                if last_key is None or key > last_key:
                    last_key = key
    except OSError as e:
        logger.warning("Could not read %s: %s", path, e)
        return None, None
    if not last_key:
        return None, None
    return last_key, parse_bar_timestamp_ist_to_aware(last_key)


def _scan_internal_gaps(
    path: str,
    tf: str,
    *,
    lookback_bars: int = 500,
) -> Optional[str]:
    """Return a reason string if recent consecutive bars skip >1 candle."""
    if not os.path.isfile(path):
        return None
    keys: List[str] = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                key = normalize_ist_bar_key(row.get("candle_timestamp_ist"))
                if key:
                    keys.append(key)
    except OSError:
        return None
    if len(keys) < 2:
        return None
    keys = sorted(set(keys))[-max(2, int(lookback_bars)) :]
    tf_sec = _tf_seconds(tf)
    # Allow tiny clock skew; flag anything clearly beyond one missing bar.
    max_ok = tf_sec * 1.5
    prev_dt = parse_bar_timestamp_ist_to_aware(keys[0])
    for key in keys[1:]:
        cur_dt = parse_bar_timestamp_ist_to_aware(key)
        if prev_dt is None or cur_dt is None:
            prev_dt = cur_dt
            continue
        delta = (cur_dt - prev_dt).total_seconds()
        if delta > max_ok:
            missing = max(0.0, (delta / tf_sec) - 1.0)
            return (
                f"internal_gap after {prev_dt.strftime('%Y-%m-%d %H:%M')} "
                f"-> {cur_dt.strftime('%Y-%m-%d %H:%M')} "
                f"(~{missing:.1f} missing bars)"
            )
        prev_dt = cur_dt
    return None


def check_symbol_timeframe(
    *,
    log_root: str,
    symbol: str,
    timeframe: str,
    now_ts: Optional[float] = None,
    check_internal: bool = True,
) -> Optional[GapFinding]:
    """Return a GapFinding when lag > 1 candle or an internal gap is found."""
    tf = _normalize_tf(timeframe)
    path = indicator_history_path(symbol, tf, log_root=log_root)
    expected = _expected_last_closed_open(now_ts, tf)
    expected_key = expected.strftime("%Y-%m-%d %H:%M")
    last_key, last_dt = _last_bar_from_jsonl(path)

    if last_key is None or last_dt is None:
        return GapFinding(
            symbol=symbol,
            timeframe=tf,
            reason="missing_or_empty_history",
            last_bar_ist=None,
            expected_closed_ist=expected_key,
            lag_bars=float("inf"),
        )

    tf_sec = _tf_seconds(tf)
    lag_sec = (expected - last_dt).total_seconds()
    lag_bars = lag_sec / float(tf_sec)
    # More than one closed candle behind the expected last closed open.
    if lag_bars > 1.0 + 1e-6:
        return GapFinding(
            symbol=symbol,
            timeframe=tf,
            reason="lag_gt_one_candle",
            last_bar_ist=last_key,
            expected_closed_ist=expected_key,
            lag_bars=lag_bars,
        )

    if check_internal:
        internal = _scan_internal_gaps(path, tf)
        if internal:
            return GapFinding(
                symbol=symbol,
                timeframe=tf,
                reason=internal,
                last_bar_ist=last_key,
                expected_closed_ist=expected_key,
                lag_bars=max(0.0, lag_bars),
            )
    return None


def find_gaps(
    *,
    log_root: str,
    symbols: Sequence[str],
    timeframes: Sequence[str],
    now_ts: Optional[float] = None,
    check_internal: bool = True,
) -> List[GapFinding]:
    findings: List[GapFinding] = []
    for symbol in symbols:
        for tf in timeframes:
            hit = check_symbol_timeframe(
                log_root=log_root,
                symbol=str(symbol).upper(),
                timeframe=tf,
                now_ts=now_ts,
                check_internal=check_internal,
            )
            if hit is not None:
                findings.append(hit)
    return findings


def _python_bin() -> str:
    return sys.executable or "python3"


def _build_refresh_commands(
    *,
    findings: Sequence[GapFinding],
    log_root: str,
    no_cache: bool,
) -> List[List[str]]:
    """
    Group gaps into refresh_crypto_indicator_history invocations.

    Prefer one call per (symbol, TF-group): SuperTrend vs structure.
    """
    by_symbol: Dict[str, set] = {}
    for g in findings:
        by_symbol.setdefault(g.symbol, set()).add(g.timeframe)

    cmds: List[List[str]] = []
    py = _python_bin()
    for symbol, tfs in sorted(by_symbol.items()):
        st = [t for t in SUPER_TREND_TIMEFRAMES if t in tfs]
        struct = [t for t in STRUCTURE_TIMEFRAMES if t in tfs]
        if st:
            cmd = [
                py,
                REFRESH_SCRIPT,
                "--log-root",
                log_root,
                "--symbol",
                symbol,
                "--only",
                ",".join(st),
            ]
            # Deep 4h backfill when 4h is among the gaps (matches docstring example).
            if "4h" in st and len(st) == 1:
                cmd.extend(["--days", str(DEFAULT_DAYS_BY_TF["4h"])])
            if no_cache:
                cmd.append("--no-cache")
            cmds.append(cmd)
        if struct:
            cmd = [
                py,
                REFRESH_SCRIPT,
                "--log-root",
                log_root,
                "--symbol",
                symbol,
                "--only",
                ",".join(struct),
            ]
            if no_cache:
                cmd.append("--no-cache")
            cmds.append(cmd)
    return cmds


def run_sync(
    *,
    log_root: str,
    symbols: Sequence[str],
    timeframes: Sequence[str],
    dry_run: bool = False,
    no_cache: bool = True,
    check_internal: bool = True,
) -> int:
    """
    Check gaps and sync. Returns process exit code (0 = ok / nothing to do,
    1 = sync attempted with failures, 2 = check error).
    """
    findings = find_gaps(
        log_root=log_root,
        symbols=symbols,
        timeframes=timeframes,
        check_internal=check_internal,
    )
    if not findings:
        logger.info(
            "No candle gaps (>1 bar) for symbols=%s tfs=%s",
            ",".join(symbols),
            ",".join(timeframes),
        )
        return 0

    for g in findings:
        logger.warning(
            "GAP %s/%s reason=%s last=%s expected_closed=%s lag_bars=%.2f",
            g.symbol,
            g.timeframe,
            g.reason,
            g.last_bar_ist,
            g.expected_closed_ist,
            g.lag_bars if g.lag_bars != float("inf") else -1.0,
        )

    cmds = _build_refresh_commands(
        findings=findings, log_root=log_root, no_cache=no_cache
    )
    failures = 0
    for cmd in cmds:
        pretty = " ".join(cmd)
        if dry_run:
            logger.info("DRY-RUN would run: %s", pretty)
            continue
        logger.info("Syncing: %s", pretty)
        try:
            proc = subprocess.run(
                cmd,
                cwd=_REPO_ROOT,
                check=False,
            )
        except OSError as e:
            logger.error("Failed to spawn refresh: %s", e)
            failures += 1
            continue
        if proc.returncode != 0:
            logger.error("Refresh exited %s for: %s", proc.returncode, pretty)
            failures += 1
        else:
            logger.info("Refresh OK: %s", pretty)

    if dry_run:
        return 0
    return 1 if failures else 0


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Detect >1-candle gaps in logs/indicators/{BTCUSD,PAXGUSD}/* and "
            "sync via refresh_crypto_indicator_history.py"
        )
    )
    parser.add_argument(
        "--log-root",
        default=os.path.join(_REPO_ROOT, "logs"),
        help="Logs root (default: repo logs/)",
    )
    parser.add_argument(
        "--symbols",
        default=",".join(DEFAULT_SYMBOLS),
        help="Comma-separated symbols (default: BTCUSD,PAXGUSD)",
    )
    parser.add_argument(
        "--only",
        default=",".join(ALL_TIMEFRAMES),
        help="Comma-separated TFs to watch (default: 1,60,4h,1d; 5m excluded)",
    )
    parser.add_argument(
        "--loop",
        action="store_true",
        help="Run once at start, then every --interval seconds",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=3600,
        help="Seconds between checks in --loop mode (default: 3600)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report gaps / print refresh commands without writing",
    )
    parser.add_argument(
        "--use-cache",
        action="store_true",
        help="Allow Delta intraday cache (default: pass --no-cache to refresh)",
    )
    parser.add_argument(
        "--skip-internal-gaps",
        action="store_true",
        help="Only check lag vs now (skip holes inside the JSONL)",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="DEBUG logging",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    if not os.path.isfile(REFRESH_SCRIPT):
        logger.error("Refresh script not found: %s", REFRESH_SCRIPT)
        return 2

    symbols = [s.upper() for s in _parse_csv_list(args.symbols, DEFAULT_SYMBOLS)]
    timeframes = [_normalize_tf(t) for t in _parse_csv_list(args.only, ALL_TIMEFRAMES)]
    for tf in timeframes:
        if tf not in ALL_TIMEFRAMES:
            logger.error("Unknown timeframe %r; choose from %s", tf, ALL_TIMEFRAMES)
            return 2

    log_root = os.path.abspath(args.log_root)
    no_cache = not args.use_cache
    check_internal = not args.skip_internal_gaps

    def _once() -> int:
        return run_sync(
            log_root=log_root,
            symbols=symbols,
            timeframes=timeframes,
            dry_run=args.dry_run,
            no_cache=no_cache,
            check_internal=check_internal,
        )

    rc = _once()
    if not args.loop:
        return rc

    interval = max(60, int(args.interval or 3600))
    logger.info("Looping every %ss (startup check done, rc=%s)", interval, rc)
    while True:
        time.sleep(interval)
        try:
            rc = _once()
        except Exception:
            logger.exception("Gap sync iteration failed")
            rc = 2


if __name__ == "__main__":
    raise SystemExit(main())
