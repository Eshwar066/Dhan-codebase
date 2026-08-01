import csv
import os
from threading import Lock

# Per-fill event stream: logs/{strategy}_trades.csv
TRADES_COLUMNS = [
    "candle_timestamp",
    "tag",
    "symbol",
    "trade_type",
    "side",
    "qty",
    "price",
    "pnl",
    "cumulative_pnl",
    "net_qty_after",
    "execution_source",
    "mae",
    "mfe",
    "exit_reason",
]

# Completed round-trips: logs/{strategy}_trade_log.csv and logs/trade_log.csv
TRADE_LOG_COLUMNS = [
    "trade_id",
    "entry_time",
    "exit_time",
    "side",
    "entry_price",
    "exit_price",
    "qty",
    "pnl",
    "collected_points",
    "symbol",
    "strategy",
    "exit_reason",
    "execution_source",
    # Optional strategy context (e.g. LiquiditySweepStrategy sweep details)
    "swept_level",
    "zone_side",
    "zone_source",
    "zone_bar_key",
    "sweep_bar_key",
]


class TradeLogger:
    def __init__(self, base_dir="logs"):
        self.base_dir = base_dir
        self._locks = {}
        self._trade_log_lock = Lock()
        os.makedirs(base_dir, exist_ok=True)

    def _get_file(self, strategy):
        return os.path.join(self.base_dir, f"{strategy}_trades.csv")

    def _get_trade_log_file(self):
        return os.path.join(self.base_dir, "trade_log.csv")

    def _get_per_strategy_trade_log_file(self, strategy: str) -> str:
        """Per-strategy trade-summary file (same schema as aggregate trade_log.csv)."""
        return os.path.join(self.base_dir, f"{strategy}_trade_log.csv")

    def _get_lock(self, strategy):
        if strategy not in self._locks:
            self._locks[strategy] = Lock()
        return self._locks[strategy]

    @staticmethod
    def _header_matches(path: str, expected: list) -> bool:
        if not os.path.isfile(path) or os.path.getsize(path) == 0:
            return True
        try:
            with open(path, newline="", encoding="utf-8") as f:
                reader = csv.reader(f)
                header = next(reader, None)
        except OSError:
            return False
        if not header:
            return True
        return list(header) == list(expected)

    def _ensure_schema_or_rotate(self, path: str, expected: list) -> None:
        """If an existing file has a stale/misaligned header, drop it and start fresh.

        No ``.bak`` sidecars — misaligned CSVs are discarded so logs stay clean.
        """
        if self._header_matches(path, expected):
            return
        try:
            os.remove(path)
        except OSError:
            try:
                open(path, "w", encoding="utf-8").close()
            except OSError:
                pass

    def log(self, strategy, row: dict):
        """Append one per-fill row using a fixed ``TRADES_COLUMNS`` schema."""
        if not strategy:
            strategy = "GLOBAL"

        file_path = self._get_file(strategy)
        lock = self._get_lock(strategy)
        out = {k: row.get(k, "") for k in TRADES_COLUMNS}
        # Preserve empty strings; coerce None → ""
        for k, v in list(out.items()):
            if v is None:
                out[k] = ""

        with lock:
            self._ensure_schema_or_rotate(file_path, TRADES_COLUMNS)
            write_header = not os.path.exists(file_path) or os.path.getsize(file_path) == 0
            with open(file_path, "a", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(
                    f, fieldnames=TRADES_COLUMNS, extrasaction="ignore"
                )
                if write_header:
                    writer.writeheader()
                writer.writerow(out)

    def log_trade(self, trade_row: dict):
        """
        Log a completed trade (round-trip) for performance analytics.

        trade_row must contain: trade_id, entry_time, exit_time, side,
        entry_price, exit_price, qty, pnl, and optionally symbol, strategy.

        Writes to two files (both with ``TRADE_LOG_COLUMNS`` schema):
          * ``logs/{strategy}_trade_log.csv`` — per-strategy summary
          * ``logs/trade_log.csv``            — aggregate across strategies

        NOTE: ``{strategy}_trades.csv`` is reserved for per-fill rows
        written by :meth:`log` (different schema, consumed by quarterly_report).
        Mixing the two schemas in one file produced misaligned rows.
        """
        row = {k: trade_row.get(k, "") for k in TRADE_LOG_COLUMNS}
        for k, v in list(row.items()):
            if v is None:
                row[k] = ""
        strategy = trade_row.get("strategy") or "GLOBAL"
        per_strategy_path = self._get_per_strategy_trade_log_file(strategy)
        lock = self._get_lock(strategy)
        with lock:
            self._ensure_schema_or_rotate(per_strategy_path, TRADE_LOG_COLUMNS)
            write_header = (
                not os.path.exists(per_strategy_path)
                or os.path.getsize(per_strategy_path) == 0
            )
            with open(per_strategy_path, "a", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(
                    f, fieldnames=TRADE_LOG_COLUMNS, extrasaction="ignore"
                )
                if write_header:
                    writer.writeheader()
                writer.writerow(row)
        agg_path = self._get_trade_log_file()
        with self._trade_log_lock:
            self._ensure_schema_or_rotate(agg_path, TRADE_LOG_COLUMNS)
            write_header_agg = (
                not os.path.exists(agg_path) or os.path.getsize(agg_path) == 0
            )
            with open(agg_path, "a", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(
                    f, fieldnames=TRADE_LOG_COLUMNS, extrasaction="ignore"
                )
                if write_header_agg:
                    writer.writeheader()
                writer.writerow(row)
