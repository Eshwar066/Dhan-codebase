import csv
import os
from threading import Lock


class TradeLogger:
    def __init__(self, base_dir="logs"):
        self.base_dir = base_dir
        self._locks = {}
        os.makedirs(base_dir, exist_ok=True)

    def _get_file(self, strategy):
        return os.path.join(self.base_dir, f"{strategy}_trades.csv")

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
