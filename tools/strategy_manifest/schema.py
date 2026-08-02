"""Strategy manifest schema (validated dict → StrategyManifest)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


VALID_INSTRUMENTS = frozenset({"OPTION", "FUTURE", "EQUITY"})
VALID_MODES = frozenset({"BACKTEST", "PAPER", "LIVE"})
VALID_EVAL_MODES = frozenset({"live_feed", "scheduled"})
VALID_VENUES = frozenset({"DHAN", "DELTA", "KOTAK"})

# Event names strategies may declare under subscriptions:
VALID_SUBSCRIPTION_EVENTS = frozenset(
    {
        "BarClosed",
        "ScheduledSlot",
        "QuoteUpdated",
        "IntentCreated",
        "IntentFilled",
        "PositionClosed",
        "FeedDisconnected",
        "FeedRecovered",
    }
)

# Always-on infrastructure events (registered once per engine when any strategy loads).
INFRA_SUBSCRIPTION_EVENTS = frozenset(
    {
        "IntentCreated",
        "IntentFilled",
        "PositionClosed",
        "FeedDisconnected",
        "FeedRecovered",
    }
)


@dataclass
class ImplementationSpec:
    module: str
    class_name: str


@dataclass
class BrokerSpec:
    venue: str = "DHAN"
    api: Optional[str] = None
    delta: Optional[Dict[str, Any]] = None


@dataclass
class ScheduleSpec:
    eval_mode: str = "live_feed"
    times: List[str] = field(default_factory=list)


@dataclass
class ExecutionSpec:
    mode: str = "LIMIT"
    gtt_fallback: Optional[Dict[str, Any]] = None
    bracket_leg_tags: List[str] = field(default_factory=list)


@dataclass
class DependenciesSpec:
    mixins: List[str] = field(default_factory=list)
    required_context: List[str] = field(default_factory=list)
    expiry_type: Optional[str] = None
    meta_key: Optional[str] = None
    meta_aliases: Dict[str, str] = field(default_factory=dict)


@dataclass
class DocumentationSpec:
    title: Optional[str] = None
    overview: Optional[str] = None
    rules: Optional[str] = None
    run_command: Optional[str] = None
    generate_readme: bool = False


@dataclass
class EventSubscriptionSpec:
    """Per-event subscription declared (or inferred) for a strategy."""

    enabled: bool = True
    timeframes: List[str] = field(default_factory=list)
    symbols: List[str] = field(default_factory=list)


@dataclass
class SubscriptionsSpec:
    """Resolved event interest for bus wiring (strategy.yaml → subscriptions:)."""

    events: Dict[str, EventSubscriptionSpec] = field(default_factory=dict)

    def enabled(self, event_name: str) -> bool:
        spec = self.events.get(event_name)
        return bool(spec and spec.enabled)

    def to_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        for name, spec in sorted(self.events.items()):
            entry: Dict[str, Any] = {"enabled": bool(spec.enabled)}
            if spec.timeframes:
                entry["timeframes"] = list(spec.timeframes)
            if spec.symbols:
                entry["symbols"] = list(spec.symbols)
            out[name] = entry
        return out


@dataclass
class StrategyManifest:
    """Parsed strategy.yaml — source of truth for generated wiring."""

    id: str
    implementation: ImplementationSpec
    instrument: str
    allowed_modes: List[str]
    broker: BrokerSpec
    symbols: Optional[List[str]]
    exchange: str = "NSE"
    timeframe: Optional[str] = None
    backtest_timeframe: Optional[str] = None
    schedule: ScheduleSpec = field(default_factory=ScheduleSpec)
    execution: ExecutionSpec = field(default_factory=ExecutionSpec)
    data: Dict[str, Any] = field(default_factory=dict)
    profile: Dict[str, Any] = field(default_factory=dict)
    risk: Dict[str, Any] = field(default_factory=dict)
    dependencies: DependenciesSpec = field(default_factory=DependenciesSpec)
    documentation: DocumentationSpec = field(default_factory=DocumentationSpec)
    aliases: List[str] = field(default_factory=list)
    subscriptions: SubscriptionsSpec = field(default_factory=SubscriptionsSpec)
    source_path: Optional[Path] = None

    @property
    def class_attr_name(self) -> str:
        return self.implementation.class_name


def _parse_event_subscription(raw: Any, *, default_enabled: bool) -> EventSubscriptionSpec:
    if raw is None:
        return EventSubscriptionSpec(enabled=default_enabled)
    if isinstance(raw, bool):
        return EventSubscriptionSpec(enabled=raw)
    if isinstance(raw, dict):
        enabled = raw.get("enabled")
        if enabled is None:
            enabled = default_enabled
        tfs = raw.get("timeframes") or []
        syms = raw.get("symbols") or []
        if not isinstance(tfs, list):
            raise ValueError("subscriptions.*.timeframes must be a list")
        if not isinstance(syms, list):
            raise ValueError("subscriptions.*.symbols must be a list")
        return EventSubscriptionSpec(
            enabled=bool(enabled),
            timeframes=[str(t).strip() for t in tfs if str(t).strip()],
            symbols=[str(s).strip().upper() for s in syms if str(s).strip()],
        )
    raise ValueError(f"subscriptions entry must be bool or mapping, got {type(raw).__name__}")


def default_subscriptions_for(
    *,
    eval_mode: str,
    timeframe: Optional[str],
    symbols: Optional[List[str]],
    execution: ExecutionSpec,
) -> SubscriptionsSpec:
    """Infer bus subscriptions from schedule + execution when YAML omits them."""
    live_feed = eval_mode == "live_feed"
    scheduled = eval_mode == "scheduled"
    has_gtt = bool(execution.gtt_fallback) or execution.mode in {"GTT", "HYBRID_GTT"}
    tfs = [str(timeframe)] if timeframe else []
    syms = list(symbols) if symbols else []

    events: Dict[str, EventSubscriptionSpec] = {
        "BarClosed": EventSubscriptionSpec(enabled=live_feed, timeframes=tfs, symbols=syms),
        "ScheduledSlot": EventSubscriptionSpec(enabled=scheduled, symbols=syms),
        "QuoteUpdated": EventSubscriptionSpec(enabled=has_gtt, symbols=syms),
        "IntentCreated": EventSubscriptionSpec(enabled=True),
        "IntentFilled": EventSubscriptionSpec(enabled=True),
        "PositionClosed": EventSubscriptionSpec(enabled=True),
        "FeedDisconnected": EventSubscriptionSpec(enabled=True),
        "FeedRecovered": EventSubscriptionSpec(enabled=True),
    }
    return SubscriptionsSpec(events=events)


def resolve_subscriptions(
    raw: Optional[Dict[str, Any]],
    *,
    eval_mode: str,
    timeframe: Optional[str],
    symbols: Optional[List[str]],
    execution: ExecutionSpec,
) -> SubscriptionsSpec:
    """Merge explicit YAML subscriptions over inferred defaults."""
    base = default_subscriptions_for(
        eval_mode=eval_mode,
        timeframe=timeframe,
        symbols=symbols,
        execution=execution,
    )
    if not raw:
        return base
    if not isinstance(raw, dict):
        raise ValueError("subscriptions must be a mapping")

    for key, value in raw.items():
        name = str(key).strip()
        if name not in VALID_SUBSCRIPTION_EVENTS:
            raise ValueError(
                f"unknown subscription event {name!r}; "
                f"valid={sorted(VALID_SUBSCRIPTION_EVENTS)}"
            )
        default_enabled = base.enabled(name)
        base.events[name] = _parse_event_subscription(value, default_enabled=default_enabled)
        # Fill timeframe/symbol defaults when override is a bare bool True
        if isinstance(value, bool) and value:
            if name == "BarClosed" and timeframe and not base.events[name].timeframes:
                base.events[name].timeframes = [str(timeframe)]
            if symbols and not base.events[name].symbols and name in (
                "BarClosed",
                "ScheduledSlot",
                "QuoteUpdated",
            ):
                base.events[name].symbols = list(symbols)
    return base


def _require_dict(raw: Any, label: str) -> Dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError(f"{label} must be a mapping")
    return raw


def parse_manifest(raw: Dict[str, Any], source_path: Optional[Path] = None) -> StrategyManifest:
    if not isinstance(raw, dict):
        raise ValueError("manifest root must be a mapping")

    strategy_id = str(raw.get("id") or "").strip()
    if not strategy_id:
        raise ValueError("manifest.id is required")

    impl_raw = _require_dict(raw.get("implementation"), "implementation")
    module = str(impl_raw.get("module") or "").strip()
    class_name = str(impl_raw.get("class") or impl_raw.get("class_name") or "").strip()
    if not module or not class_name:
        raise ValueError(f"{strategy_id}: implementation.module and implementation.class are required")

    instrument = str(raw.get("instrument") or "").strip().upper()
    if instrument not in VALID_INSTRUMENTS:
        raise ValueError(f"{strategy_id}: invalid instrument {instrument!r}")

    modes_raw = raw.get("allowed_modes") or []
    if not isinstance(modes_raw, list) or not modes_raw:
        raise ValueError(f"{strategy_id}: allowed_modes must be a non-empty list")
    allowed_modes = [str(m).strip().upper() for m in modes_raw]
    for mode in allowed_modes:
        if mode not in VALID_MODES:
            raise ValueError(f"{strategy_id}: invalid allowed_mode {mode!r}")

    broker_raw = raw.get("broker") or {}
    broker = BrokerSpec(
        venue=str(broker_raw.get("venue") or "DHAN").strip().upper(),
        api=broker_raw.get("api"),
        delta=broker_raw.get("delta"),
    )
    if broker.venue not in VALID_VENUES:
        raise ValueError(f"{strategy_id}: invalid broker.venue {broker.venue!r}")

    symbols_raw = raw.get("symbols", "__missing__")
    symbols: Optional[List[str]]
    if symbols_raw is None:
        symbols = None
    elif symbols_raw == "__missing__":
        symbols = []
    else:
        if not isinstance(symbols_raw, list):
            raise ValueError(f"{strategy_id}: symbols must be a list or null")
        symbols = [str(s).strip().upper() for s in symbols_raw if str(s).strip()]

    sched_raw = raw.get("schedule") or {}
    schedule = ScheduleSpec(
        eval_mode=str(sched_raw.get("eval_mode") or "live_feed").strip(),
        times=[str(t).strip() for t in (sched_raw.get("times") or [])],
    )
    if schedule.eval_mode not in VALID_EVAL_MODES:
        raise ValueError(f"{strategy_id}: invalid schedule.eval_mode {schedule.eval_mode!r}")

    exec_raw = raw.get("execution") or {}
    execution = ExecutionSpec(
        mode=str(exec_raw.get("mode") or "LIMIT").strip().upper(),
        gtt_fallback=exec_raw.get("gtt_fallback"),
        bracket_leg_tags=[str(t) for t in (exec_raw.get("bracket_leg_tags") or [])],
    )

    deps_raw = raw.get("dependencies") or {}
    dependencies = DependenciesSpec(
        mixins=[str(m) for m in (deps_raw.get("mixins") or [])],
        required_context=[str(c) for c in (deps_raw.get("required_context") or [])],
        expiry_type=deps_raw.get("expiry_type"),
        meta_key=deps_raw.get("meta_key"),
        meta_aliases=dict(deps_raw.get("meta_aliases") or {}),
    )

    doc_raw = raw.get("documentation") or {}
    documentation = DocumentationSpec(
        title=doc_raw.get("title"),
        overview=doc_raw.get("overview"),
        rules=doc_raw.get("rules"),
        run_command=doc_raw.get("run_command"),
        generate_readme=bool(doc_raw.get("generate_readme", False)),
    )

    timeframe = raw.get("timeframe")
    if timeframe is not None and str(timeframe).strip().lower() in ("null", "none", ""):
        timeframe = None
    elif timeframe is not None:
        timeframe = str(timeframe)

    backtest_tf = raw.get("backtest_timeframe")
    if backtest_tf is not None:
        backtest_tf = str(backtest_tf)

    try:
        subscriptions = resolve_subscriptions(
            raw.get("subscriptions"),
            eval_mode=schedule.eval_mode,
            timeframe=timeframe,
            symbols=symbols,
            execution=execution,
        )
    except ValueError as exc:
        raise ValueError(f"{strategy_id}: {exc}") from exc

    return StrategyManifest(
        id=strategy_id,
        implementation=ImplementationSpec(module=module, class_name=class_name),
        instrument=instrument,
        allowed_modes=allowed_modes,
        broker=broker,
        symbols=symbols,
        exchange=str(raw.get("exchange") or "NSE").strip().upper(),
        timeframe=timeframe,
        backtest_timeframe=backtest_tf,
        schedule=schedule,
        execution=execution,
        data=dict(raw.get("data") or {}),
        profile=dict(raw.get("profile") or {}),
        risk=dict(raw.get("risk") or {}),
        dependencies=dependencies,
        documentation=documentation,
        aliases=[str(a).strip() for a in (raw.get("aliases") or []) if str(a).strip()],
        subscriptions=subscriptions,
        source_path=source_path,
    )
