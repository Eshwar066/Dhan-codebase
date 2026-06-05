"""
Standalone Option Buildup scheduler.

- Runs on wall-clock IST 5-minute slots (09:15, 09:20, ...).
- Does not depend on engine candle callbacks or websocket feed.
- Polls spot via Dhan REST and calls OptionBuildup strategy methods directly.

source .venv/bin/activate

python -m run.option_buildup_scheduler --symbols NIFTY --exchange NSE
python -m run.option_buildup_scheduler --symbols NIFTY --exchange NSE --all-day

python -m run.option_buildup_scheduler --symbols GOLD --exchange MCX

sudo cp /root/Dhan-codebase/utils/systemd/option-buildup-scheduler.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl restart option-buildup-scheduler.service
sudo journalctl -u option-buildup-scheduler.service -n 20
"""

from __future__ import annotations

import argparse
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from core.data.data_router import DataRouter
from core.data.datalayer.dhan_data_provider import DhanDataProvider
from core.data.option_chain_service import OptionChainService
from core.data.sources.dhan_source import DhanSource
from core.strategies.OpenIntrest.optionbuildup import OptionBuildup

IST = timezone(timedelta(hours=5, minutes=30))


def _next_five_min_slot_ist(now_ist: datetime) -> datetime:
    base = now_ist.replace(second=0, microsecond=0)
    extra = (5 - (base.minute % 5)) % 5
    if extra == 0:
        return base + timedelta(minutes=5)
    return base + timedelta(minutes=extra)


def _is_market_window_ist(ts_ist: datetime, exchange: str) -> bool:
    t = ts_ist.time().replace(second=0, microsecond=0)
    ex = str(exchange or "").upper()
    if ex == "MCX":
        # Practical MCX window for scheduler usage.
        open_t = datetime.strptime("09:00", "%H:%M").time()
        close_t = datetime.strptime("23:30", "%H:%M").time()
    else:
        # NSE index/equity window.
        open_t = datetime.strptime("09:15", "%H:%M").time()
        close_t = datetime.strptime("15:30", "%H:%M").time()
    return open_t <= t <= close_t


def _extract_close(ohlc_payload: Any, symbol: str) -> Optional[float]:
    if not isinstance(ohlc_payload, dict):
        return None
    row = ohlc_payload.get(symbol)
    if row is None and ohlc_payload:
        row = next(iter(ohlc_payload.values()))
    if not isinstance(row, dict):
        return None
    for key in ("close", "ltp", "last_price", "LTP", "Close"):
        if key not in row:
            continue
        try:
            v = float(row[key])
            if v > 0:
                return v
        except (TypeError, ValueError):
            continue
    return None


def run_scheduler(
    *,
    symbols: list[str],
    exchange: str,
    market_window_only: bool,
    sleep_step_seconds: float,
) -> None:
    source = DhanSource()
    provider = DhanDataProvider(source)
    router = DataRouter(provider)
    option_chain_service = OptionChainService(router)
    strategy = OptionBuildup()

    print(
        f"[OptionBuildupScheduler] start symbols={symbols} exchange={exchange} market_window_only={market_window_only}"
    )
    processed_slots: set[str] = set()
    while True:
        now_ist = datetime.now(IST)
        slot_ist = _next_five_min_slot_ist(now_ist)
        wait_s = max(0.0, (slot_ist - now_ist).total_seconds())
        if wait_s > 0:
            time.sleep(wait_s)
        slot_ist = datetime.now(IST).replace(second=0, microsecond=0)

        if market_window_only and not _is_market_window_ist(slot_ist, exchange):
            time.sleep(max(0.2, float(sleep_step_seconds)))
            continue

        slot_utc = slot_ist.astimezone(timezone.utc)
        ohlc = source.get_latest_candles(symbols, debug="NO")
        for sym in symbols:
            try:
                slot_key = f"{sym}|{slot_ist.strftime('%Y-%m-%d|%H-%M')}"
                if slot_key in processed_slots:
                    continue
                close = _extract_close(ohlc, sym)
                if close is None:
                    print(
                        f"[OptionBuildupScheduler] skip symbol={sym} reason=no_close slot={slot_ist.strftime('%Y-%m-%d %H:%M')}"
                    )
                    continue
                strategy.run_snapshot_cycle(
                    symbol=sym,
                    exchange=exchange,
                    ts_utc=slot_utc,
                    spot_price=close,
                    option_chain_service=option_chain_service,
                )
                print(
                    f"[OptionBuildupScheduler] ran symbol={sym} close={close} slot={slot_ist.strftime('%Y-%m-%d %H:%M')}"
                )
                processed_slots.add(slot_key)
            except Exception as exc:
                print(f"[OptionBuildupScheduler] error symbol={sym}: {exc}")

        time.sleep(max(0.2, float(sleep_step_seconds)))


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Standalone 5-minute Option Buildup scheduler")
    p.add_argument("--symbols", nargs="+", default=["NIFTY"], help="Underlying symbols")
    p.add_argument("--exchange", default="NSE", help="Exchange value for StrategyContext")
    p.add_argument(
        "--all-day",
        action="store_true",
        help="Run all day; by default only runs 09:15-15:30 IST",
    )
    p.add_argument(
        "--sleep-step-seconds",
        type=float,
        default=1.0,
        help="Small cooldown after each cycle",
    )
    return p.parse_args()


def main() -> None:
    args = _parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )
    run_scheduler(
        symbols=[str(s).strip().upper() for s in args.symbols if str(s).strip()],
        exchange=str(args.exchange or "NSE").strip().upper(),
        market_window_only=not bool(args.all_day),
        sleep_step_seconds=float(args.sleep_step_seconds),
    )


if __name__ == "__main__":
    main()
