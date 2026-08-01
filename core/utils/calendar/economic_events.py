"""
Economic event calendar for Delta entry blackout.

Trade path uses only in-memory load of local YAML + JSON cache — no network I/O.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple, Union
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

ALLOWED_IMPACTS = frozenset({"HIGH"})
ALLOWED_CURRENCIES = frozenset({"USD"})

# Canonical keys used by fetcher mapping / filters
ALLOWED_EVENT_KEYS = frozenset(
    {"FOMC", "CPI", "NFP", "PCE", "GDP", "FED_SPEECH"}
)

# India Standard Time — DOS / Delta crypto sleeves use IST clock gates.
IST = ZoneInfo("Asia/Kolkata")
DEFAULT_ZERO_DTE_CUTOFF_IST = time(17, 30)

PathLike = Union[str, Path]
NowLike = Union[datetime, float, int, None]


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _as_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_event_time(value: Any) -> Optional[datetime]:
    """Parse ISO-8601 (Z or offset) into timezone-aware UTC datetime."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return _as_utc(value)
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), tz=timezone.utc)
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return _as_utc(datetime.fromisoformat(text))
    except ValueError:
        return None


def normalize_now(now: NowLike = None) -> datetime:
    if now is None:
        return datetime.now(timezone.utc)
    if isinstance(now, datetime):
        return _as_utc(now)
    return datetime.fromtimestamp(float(now), tz=timezone.utc)


@dataclass(frozen=True)
class EconomicEvent:
    event: str
    time: datetime
    impact: str = "HIGH"
    currency: str = "USD"
    source: str = "manual"
    event_key: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event": self.event,
            "time": self.time.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "impact": self.impact,
            "currency": self.currency,
            "source": self.source,
            **({"event_key": self.event_key} if self.event_key else {}),
        }

    @classmethod
    def from_mapping(cls, raw: Dict[str, Any]) -> Optional["EconomicEvent"]:
        if not isinstance(raw, dict):
            return None
        name = str(raw.get("event") or raw.get("name") or "").strip()
        when = parse_event_time(raw.get("time") or raw.get("datetime") or raw.get("ts"))
        if not name or when is None:
            return None
        impact = str(raw.get("impact") or "HIGH").strip().upper()
        currency = str(raw.get("currency") or "USD").strip().upper()
        source = str(raw.get("source") or "manual").strip() or "manual"
        event_key_raw = raw.get("event_key")
        event_key = (
            str(event_key_raw).strip().upper() if event_key_raw is not None else None
        )
        return cls(
            event=name,
            time=when,
            impact=impact,
            currency=currency,
            source=source,
            event_key=event_key,
        )


def _event_identity(ev: EconomicEvent) -> Tuple[str, str]:
    """Dedupe key: normalized name + exact UTC second."""
    return (
        " ".join(ev.event.upper().split()),
        ev.time.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )


def is_high_usd_event(ev: EconomicEvent) -> bool:
    return (
        ev.impact.upper() in ALLOWED_IMPACTS
        and ev.currency.upper() in ALLOWED_CURRENCIES
    )


def load_events_from_json(path: PathLike) -> List[EconomicEvent]:
    p = Path(path)
    if not p.is_file():
        return []
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Failed to load economic calendar JSON %s: %s", p, exc)
        return []
    items: Iterable[Any]
    if isinstance(raw, dict):
        items = raw.get("events") or raw.get("data") or []
    elif isinstance(raw, list):
        items = raw
    else:
        return []
    out: List[EconomicEvent] = []
    for item in items:
        ev = EconomicEvent.from_mapping(item) if isinstance(item, dict) else None
        if ev is not None:
            out.append(ev)
    return out


def load_events_from_yaml(path: PathLike) -> Tuple[List[EconomicEvent], Dict[str, Any]]:
    """
    Load manual override YAML.

    Returns (events, meta) where meta may include enabled / blackout_minutes_*.
    """
    p = Path(path)
    meta: Dict[str, Any] = {}
    if not p.is_file():
        return [], meta
    try:
        import yaml
    except ImportError:
        logger.warning("PyYAML not installed; cannot load %s", p)
        return [], meta
    try:
        raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except (OSError, Exception) as exc:
        logger.warning("Failed to load economic calendar YAML %s: %s", p, exc)
        return [], meta
    if not isinstance(raw, dict):
        return [], meta
    for key in (
        "enabled",
        "blackout_minutes_before",
        "blackout_minutes_after",
        "minutes_before",
        "minutes_after",
        "short_dte_rules_enabled",
        "zero_dte_cutoff_ist",
        "block_1dte_until_event_done",
    ):
        if key in raw:
            meta[key] = raw[key]
    events_raw = raw.get("events") or []
    out: List[EconomicEvent] = []
    if isinstance(events_raw, list):
        for item in events_raw:
            if not isinstance(item, dict):
                continue
            payload = dict(item)
            payload.setdefault("source", "manual")
            ev = EconomicEvent.from_mapping(payload)
            if ev is not None:
                out.append(ev)
    return out, meta


def merge_events(
    cache_events: Sequence[EconomicEvent],
    yaml_events: Sequence[EconomicEvent],
) -> List[EconomicEvent]:
    """
    Merge cache + YAML. YAML always wins on identity collision and is appended as extras.
    """
    by_id: Dict[Tuple[str, str], EconomicEvent] = {}
    for ev in cache_events:
        by_id[_event_identity(ev)] = ev
    for ev in yaml_events:
        by_id[_event_identity(ev)] = ev
    return sorted(by_id.values(), key=lambda e: e.time)


def active_events(
    events: Sequence[EconomicEvent],
    now: NowLike = None,
    *,
    minutes_before: int = 60,
    minutes_after: int = 60,
    high_usd_only: bool = True,
) -> List[EconomicEvent]:
    """Return events whose blackout window contains ``now``."""
    current = normalize_now(now)
    before = timedelta(minutes=max(0, int(minutes_before)))
    after = timedelta(minutes=max(0, int(minutes_after)))
    out: List[EconomicEvent] = []
    for ev in events:
        if high_usd_only and not is_high_usd_event(ev):
            continue
        start = ev.time - before
        end = ev.time + after
        if start <= current <= end:
            out.append(ev)
    return out


def parse_hhmm(value: Any, default: time = DEFAULT_ZERO_DTE_CUTOFF_IST) -> time:
    if value is None:
        return default
    if isinstance(value, time):
        return value.replace(tzinfo=None)
    text = str(value).strip()
    if not text:
        return default
    for fmt in ("%H:%M", "%H:%M:%S"):
        try:
            return datetime.strptime(text, fmt).time()
        except ValueError:
            continue
    return default


def parse_expiry_date(value: Any) -> Optional[date]:
    """Parse Delta/Dhan-style expiry (DDMMYY, ISO, date/datetime)."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    raw = str(value).strip()
    if not raw:
        return None
    for fmt in ("%d%m%y", "%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def intent_dte(intent: Any, now: NowLike = None) -> Optional[int]:
    """
    Calendar DTE in IST: expiry_date - today_ist.

    Prefers instrument.expiry; falls back to metadata_extras expiry.
    """
    current = normalize_now(now).astimezone(IST)
    today = current.date()
    inst = getattr(intent, "instrument", None)
    expiry_raw = getattr(inst, "expiry", None) if inst is not None else None
    if expiry_raw is None:
        extras = getattr(intent, "metadata_extras", None) or {}
        if isinstance(extras, dict):
            nested = extras.get("strategy_meta")
            if isinstance(nested, dict) and nested.get("expiry") is not None:
                expiry_raw = nested.get("expiry")
            else:
                expiry_raw = extras.get("expiry")
    exp = parse_expiry_date(expiry_raw)
    if exp is None:
        return None
    return (exp - today).days


def event_blackout_end(ev: EconomicEvent, *, minutes_after: int) -> datetime:
    return ev.time + timedelta(minutes=max(0, int(minutes_after)))


def pending_session_events(
    events: Sequence[EconomicEvent],
    now: NowLike = None,
    *,
    minutes_after: int = 60,
) -> List[EconomicEvent]:
    """
    HIGH USD events not yet completed that belong to today's IST session
    (including last-night events whose blackout still spans past midnight IST).
    """
    current = normalize_now(now)
    today_ist = current.astimezone(IST).date()
    yesterday = today_ist - timedelta(days=1)
    out: List[EconomicEvent] = []
    for ev in events:
        if not is_high_usd_event(ev):
            continue
        end = event_blackout_end(ev, minutes_after=minutes_after)
        if current >= end:
            continue
        ev_day = ev.time.astimezone(IST).date()
        if ev_day == today_ist or (ev_day == yesterday and current < end):
            out.append(ev)
    return sorted(out, key=lambda e: e.time)


def short_dte_block_reason(
    dte: Optional[int],
    events: Sequence[EconomicEvent],
    now: NowLike = None,
    *,
    minutes_after: int = 60,
    zero_dte_cutoff_ist: time = DEFAULT_ZERO_DTE_CUTOFF_IST,
    block_1dte_until_event_done: bool = True,
    short_dte_rules_enabled: bool = True,
) -> Optional[str]:
    """
    Extra ENTRY block for short-dated options around same-session HIGH events.

    - 0DTE: blocked after ``zero_dte_cutoff_ist`` while a same-session event
      is still incomplete (e.g. FOMC at ~23:30 IST → no 0DTE after 17:30 IST).
    - 1DTE: blocked until that event's blackout end (event completed).
    - DTE >= 2 (weekly/monthly): not affected here (only ±60m blackout applies).
    """
    if not short_dte_rules_enabled or dte is None:
        return None
    pending = pending_session_events(events, now, minutes_after=minutes_after)
    if not pending:
        return None
    current_ist = normalize_now(now).astimezone(IST)
    # Use the latest incomplete event end (e.g. FOMC press after decision).
    lead = max(
        pending,
        key=lambda e: event_blackout_end(e, minutes_after=minutes_after),
    )
    lead_end = event_blackout_end(lead, minutes_after=minutes_after)

    if int(dte) == 0 and current_ist.time() >= zero_dte_cutoff_ist:
        return (
            f"0DTE blocked after {zero_dte_cutoff_ist.strftime('%H:%M')} IST "
            f"until {lead.event} completes "
            f"(done after {lead_end.astimezone(IST).strftime('%Y-%m-%d %H:%M')} IST)"
        )
    if int(dte) == 1 and block_1dte_until_event_done:
        return (
            f"1DTE blocked until {lead.event} completes "
            f"(done after {lead_end.astimezone(IST).strftime('%Y-%m-%d %H:%M')} IST)"
        )
    return None


def is_blackout_active(
    events: Sequence[EconomicEvent],
    now: NowLike = None,
    *,
    minutes_before: int = 60,
    minutes_after: int = 60,
) -> Tuple[bool, Optional[EconomicEvent]]:
    hits = active_events(
        events,
        now,
        minutes_before=minutes_before,
        minutes_after=minutes_after,
    )
    if not hits:
        return False, None
    return True, hits[0]


class EventCalendarService:
    """In-memory economic calendar: JSON cache + YAML override (YAML wins)."""

    def __init__(
        self,
        *,
        cache_json: Optional[PathLike] = None,
        manual_yaml: Optional[PathLike] = None,
        minutes_before: int = 60,
        minutes_after: int = 60,
        enabled: bool = True,
        base_dir: Optional[PathLike] = None,
        short_dte_rules_enabled: bool = True,
        zero_dte_cutoff_ist: Any = DEFAULT_ZERO_DTE_CUTOFF_IST,
        block_1dte_until_event_done: bool = True,
    ):
        root = Path(base_dir) if base_dir else _repo_root()
        self.base_dir = root
        self.cache_json = (
            Path(cache_json)
            if cache_json
            else root / "logs" / "calendars" / "delta_economic_events.json"
        )
        if not self.cache_json.is_absolute():
            self.cache_json = root / self.cache_json
        self.manual_yaml = (
            Path(manual_yaml)
            if manual_yaml
            else root / "run" / "calendars" / "delta_event_blackout.yaml"
        )
        if not self.manual_yaml.is_absolute():
            self.manual_yaml = root / self.manual_yaml
        self.minutes_before = int(minutes_before)
        self.minutes_after = int(minutes_after)
        self.enabled = bool(enabled)
        self.short_dte_rules_enabled = bool(short_dte_rules_enabled)
        self.zero_dte_cutoff_ist = parse_hhmm(zero_dte_cutoff_ist)
        self.block_1dte_until_event_done = bool(block_1dte_until_event_done)
        self.events: List[EconomicEvent] = []
        self._reload()

    def _reload(self) -> None:
        cache_events = load_events_from_json(self.cache_json)
        yaml_events, meta = load_events_from_yaml(self.manual_yaml)
        if "enabled" in meta:
            self.enabled = bool(meta["enabled"])
        before = meta.get("blackout_minutes_before", meta.get("minutes_before"))
        after = meta.get("blackout_minutes_after", meta.get("minutes_after"))
        if before is not None:
            self.minutes_before = int(before)
        if after is not None:
            self.minutes_after = int(after)
        if "short_dte_rules_enabled" in meta:
            self.short_dte_rules_enabled = bool(meta["short_dte_rules_enabled"])
        if "zero_dte_cutoff_ist" in meta:
            self.zero_dte_cutoff_ist = parse_hhmm(meta["zero_dte_cutoff_ist"])
        if "block_1dte_until_event_done" in meta:
            self.block_1dte_until_event_done = bool(meta["block_1dte_until_event_done"])
        self.events = merge_events(cache_events, yaml_events)
        if self.enabled and not self.events:
            logger.warning(
                "Event blackout enabled but calendar is empty "
                "(cache=%s exists=%s, yaml=%s exists=%s) — no blackout windows",
                self.cache_json,
                self.cache_json.is_file(),
                self.manual_yaml,
                self.manual_yaml.is_file(),
            )
        elif self.enabled and not cache_events and yaml_events:
            logger.warning(
                "Economic calendar JSON cache missing or empty (%s); "
                "using manual YAML only (%d events)",
                self.cache_json,
                len(yaml_events),
            )
        logger.info(
            "Economic calendar loaded: %d events (enabled=%s, window=-%dm/+%dm, "
            "short_dte=%s cutoff=%s IST)",
            len(self.events),
            self.enabled,
            self.minutes_before,
            self.minutes_after,
            self.short_dte_rules_enabled,
            self.zero_dte_cutoff_ist.strftime("%H:%M"),
        )

    def reload(self) -> None:
        self._reload()

    def active_events(self, now: NowLike = None) -> List[EconomicEvent]:
        if not self.enabled:
            return []
        return active_events(
            self.events,
            now,
            minutes_before=self.minutes_before,
            minutes_after=self.minutes_after,
        )

    def is_blackout_active(
        self, now: NowLike = None
    ) -> Tuple[bool, Optional[EconomicEvent]]:
        if not self.enabled:
            return False, None
        return is_blackout_active(
            self.events,
            now,
            minutes_before=self.minutes_before,
            minutes_after=self.minutes_after,
        )

    def pending_session_events(self, now: NowLike = None) -> List[EconomicEvent]:
        if not self.enabled:
            return []
        return pending_session_events(
            self.events, now, minutes_after=self.minutes_after
        )

    def short_dte_block_reason(
        self, dte: Optional[int], now: NowLike = None
    ) -> Optional[str]:
        if not self.enabled:
            return None
        return short_dte_block_reason(
            dte,
            self.events,
            now,
            minutes_after=self.minutes_after,
            zero_dte_cutoff_ist=self.zero_dte_cutoff_ist,
            block_1dte_until_event_done=self.block_1dte_until_event_done,
            short_dte_rules_enabled=self.short_dte_rules_enabled,
        )


class EventBlackoutGuard:
    """
    OMS / engine guard: venue-scoped blackout check with start/end logging.

    No network I/O — delegates to EventCalendarService.
    """

    def __init__(
        self,
        calendar: EventCalendarService,
        *,
        venue: str = "DELTA",
        engine_logger: Optional[Any] = None,
    ):
        self.calendar = calendar
        self.venue = str(venue or "").upper()
        self.engine_logger = engine_logger
        self._was_active = False
        self._active_event_name: Optional[str] = None

    @classmethod
    def from_config(
        cls,
        cfg: Optional[Dict[str, Any]],
        *,
        venue: str = "DELTA",
        engine_logger: Optional[Any] = None,
        base_dir: Optional[PathLike] = None,
    ) -> Optional["EventBlackoutGuard"]:
        if not cfg or not isinstance(cfg, dict):
            return None
        if not bool(cfg.get("enabled", True)):
            return None
        if str(venue or "").upper() != "DELTA":
            return None
        calendar = EventCalendarService(
            cache_json=cfg.get("cache_json"),
            manual_yaml=cfg.get("manual_yaml"),
            minutes_before=int(cfg.get("minutes_before", 60) or 60),
            minutes_after=int(cfg.get("minutes_after", 60) or 60),
            enabled=True,
            base_dir=base_dir,
            short_dte_rules_enabled=bool(cfg.get("short_dte_rules_enabled", True)),
            zero_dte_cutoff_ist=cfg.get(
                "zero_dte_cutoff_ist", DEFAULT_ZERO_DTE_CUTOFF_IST
            ),
            block_1dte_until_event_done=bool(
                cfg.get("block_1dte_until_event_done", True)
            ),
        )
        return cls(calendar, venue=venue, engine_logger=engine_logger)

    def is_blackout_active(
        self,
        now: NowLike = None,
        *,
        venue: Optional[str] = None,
    ) -> bool:
        check_venue = str(venue or self.venue or "").upper()
        if check_venue != "DELTA":
            return False
        active, ev = self.calendar.is_blackout_active(now)
        name = ev.event if ev else None
        if active and not self._was_active:
            self._log_transition(
                "economic_event_blackout_started",
                f"Economic event blackout started: {name}",
                event=ev,
            )
        elif not active and self._was_active:
            self._log_transition(
                "economic_event_blackout_ended",
                f"Economic event blackout ended (was: {self._active_event_name})",
                event=None,
            )
        self._was_active = active
        self._active_event_name = name if active else None
        return active

    def should_block_entry(
        self,
        intent: Any = None,
        now: NowLike = None,
        *,
        venue: Optional[str] = None,
        dte: Optional[int] = None,
    ) -> Tuple[bool, str]:
        """
        Hard ENTRY gate: ±60m blackout OR short-DTE session rules.

        Returns (blocked, reason). Exits are not evaluated here.
        """
        check_venue = str(venue or self.venue or "").upper()
        if check_venue != "DELTA":
            return False, ""
        if self.is_blackout_active(now, venue=check_venue):
            detail = self.describe_active(now) or ""
            msg = "economic event blackout"
            if detail:
                msg = f"{msg} ({detail})"
            return True, msg
        resolved_dte = dte if dte is not None else intent_dte(intent, now)
        reason = self.calendar.short_dte_block_reason(resolved_dte, now)
        if reason:
            return True, reason
        return False, ""

    def active_event(self, now: NowLike = None) -> Optional[EconomicEvent]:
        if str(self.venue or "").upper() != "DELTA":
            return None
        _, ev = self.calendar.is_blackout_active(now)
        return ev

    def describe_active(self, now: NowLike = None) -> str:
        ev = self.active_event(now)
        if ev is None:
            return ""
        start = ev.time - timedelta(minutes=self.calendar.minutes_before)
        end = ev.time + timedelta(minutes=self.calendar.minutes_after)
        return (
            f"{ev.event} @ {ev.time.strftime('%Y-%m-%dT%H:%M:%SZ')} "
            f"window=[{start.strftime('%H:%M')}Z,{end.strftime('%H:%M')}Z]"
        )

    def _log_transition(
        self,
        event_type: str,
        msg: str,
        *,
        event: Optional[EconomicEvent],
    ) -> None:
        if self.engine_logger and hasattr(self.engine_logger, "log"):
            try:
                self.engine_logger.log(
                    event_type,
                    msg,
                    symbol=None,
                    extra={"event": event.to_dict() if event else None},
                )
                return
            except Exception:
                pass
        logger.info("%s", msg)


def write_events_json(path: PathLike, events: Sequence[EconomicEvent]) -> None:
    """Atomic JSON write used by the offline fetcher."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "events": [e.to_dict() for e in sorted(events, key=lambda x: x.time)],
    }
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, p)
