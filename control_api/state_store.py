import json
import os
from datetime import datetime, timezone
from threading import Lock
from typing import Any, Dict


class RuntimeStateStore:
    def __init__(self, path: str):
        self.path = path
        self._lock = Lock()
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        if not os.path.isfile(self.path):
            self._write({"engines": {}, "updated_at": self._now_iso()})

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    def _read(self) -> Dict[str, Any]:
        with open(self.path, "r", encoding="utf-8") as f:
            return json.load(f)

    def _write(self, data: Dict[str, Any]) -> None:
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    def get(self) -> Dict[str, Any]:
        with self._lock:
            return self._read()

    def upsert_engine(self, engine_id: str, patch: Dict[str, Any]) -> Dict[str, Any]:
        with self._lock:
            data = self._read()
            engines = data.setdefault("engines", {})
            current = engines.setdefault(engine_id, {})
            current.update(patch)
            current["updated_at"] = self._now_iso()
            data["updated_at"] = self._now_iso()
            self._write(data)
            return current

