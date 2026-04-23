from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional


@dataclass(frozen=True)
class AccountRoutingConfig:
    default_accounts: List[str]
    strategy_accounts: Dict[str, List[str]]
    symbol_accounts: Dict[str, List[str]]


def _dedupe_keep_order(values: List[str]) -> List[str]:
    out: List[str] = []
    seen = set()
    for value in values:
        key = str(value).strip()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(key)
    return out


class AccountRouter:
    """
    Deterministic, side-effect-free mapping from intent -> account ids.
    """

    def __init__(self, config: Optional[Mapping[str, Any]] = None):
        cfg = dict(config or {})
        default_accounts = cfg.get("default_accounts") or ["default"]
        strategy_accounts = cfg.get("strategy_accounts") or {}
        symbol_accounts = cfg.get("symbol_accounts") or {}
        self._config = AccountRoutingConfig(
            default_accounts=_dedupe_keep_order([str(a) for a in default_accounts]),
            strategy_accounts={
                str(k): _dedupe_keep_order([str(a) for a in (v or [])])
                for k, v in dict(strategy_accounts).items()
            },
            symbol_accounts={
                str(k): _dedupe_keep_order([str(a) for a in (v or [])])
                for k, v in dict(symbol_accounts).items()
            },
        )

    @property
    def all_accounts(self) -> List[str]:
        out = list(self._config.default_accounts)
        for accounts in self._config.strategy_accounts.values():
            out.extend(accounts)
        for accounts in self._config.symbol_accounts.values():
            out.extend(accounts)
        return _dedupe_keep_order(out)

    def route(self, intent: Any) -> List[str]:
        strategy_id = (
            getattr(intent, "strategy_id", None)
            or getattr(intent, "strategy", None)
            or getattr(intent, "strategy_name", None)
            or ""
        )
        symbol = (
            getattr(intent, "symbol", None)
            or getattr(getattr(intent, "instrument", None), "trading_symbol", None)
            or ""
        )
        accounts: List[str] = []
        if strategy_id:
            accounts.extend(self._config.strategy_accounts.get(str(strategy_id), []))
        if symbol:
            accounts.extend(self._config.symbol_accounts.get(str(symbol), []))
        if not accounts:
            accounts.extend(self._config.default_accounts)
        return _dedupe_keep_order(accounts)
