import csv
import os
from threading import Lock

# Standard columns for the trade log (performance analytics)
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

    def log(self, strategy, row: dict):
        if not strategy:
            strategy = "GLOBAL"

        file_path = self._get_file(strategy)
        lock = self._get_lock(strategy)

        with lock:
            write_header = not os.path.exists(file_path)

            with open(file_path, "a", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=row.keys())
                if write_header:
                    writer.writeheader()
                writer.writerow(row)

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
        strategy = trade_row.get("strategy") or "GLOBAL"
        per_strategy_path = self._get_per_strategy_trade_log_file(strategy)
        lock = self._get_lock(strategy)
        with lock:
            write_header = not os.path.exists(per_strategy_path)
            with open(per_strategy_path, "a", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=TRADE_LOG_COLUMNS)
                if write_header:
                    writer.writeheader()
                writer.writerow(row)
        agg_path = self._get_trade_log_file()
        with self._trade_log_lock:
            write_header_agg = not os.path.exists(agg_path)
            with open(agg_path, "a", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=TRADE_LOG_COLUMNS)
                if write_header_agg:
                    writer.writeheader()
                writer.writerow(row)
