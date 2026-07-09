# Event-Driven Strategy Guide

How to add strategies and evolve this codebase toward a cleaner **event-driven** architecture.

## Current architecture (as implemented)

```
Market data events          Strategy events              Execution events
──────────────────          ───────────────              ────────────────
WS tick                     closed 60m bar               OrderIntent created
  → CandleAggregator          → should_evaluate          → intent queue
  → closed bar                → on_candle                → account router
scheduled IST slot            → should_exit              → OMS worker
  → synthetic candle          → on_candle_rollover       → broker place/fill
quote update (GttFallback)    → on_main_entry_filled     → process_trade
                                                         → position_manager
```

The system is **already multi-strategy** and **mostly event-driven** at the edges (ticks, fills, scheduled slots). The main gap is **uniform internal events** — today the live loop polls (`sleep(1)`) and calls strategy hooks directly.

---

## Extension points (use these for new strategies)

### 1. Strategy contract — `BaseStrategy`

| Hook | Purpose |
|------|---------|
| `should_evaluate(candle)` | Gate entry evaluation (crossover, slot, window) |
| `on_candle(candle, ctx)` | Produce ENTRY intents or None |
| `should_exit(pos, candle, ctx)` | Gate exit per open MAIN leg |
| `on_position_exit(pos, candle, ctx)` | EXIT intents |
| `on_candle_rollover(open_positions, candle, ctx)` | Hedge roll (IndiaMktMixins) |
| `on_main_entry_filled(...)` | Arm SL / TARGET after fill |
| `on_main_exit_filled(...)` | Re-entry / cleanup |
| `scheduled_times` | Wall-clock eval (BTST) — set `timeframe = None` |

Class attrs: `name`, `underlying_symbols`, `timeframe`, `api`, `expiryType`, `required_context`.

### 2. Registration

```python
# core/strategies/registry.py
STRATEGY_MAP["MyStrategy"] = {"strategy": MyStrategy, "allowed_modes": [...]}

# core/strategies/runtime_spec.py
STRATEGY_RUNTIME_SPEC["MyStrategy"] = {"live": {...}, "backtest": {...}}

# run/config.py — STRATEGY_JOBS entry
```

### 3. Execution opt-in

```python
metadata_extras = {
    "execution_mode": "HYBRID_GTT",  # or GTT, or omit for LIMIT
    "gtt_fallback": {
        "trigger_field": "ask",
        "trigger_op": "<=",
        "active_until": "15:20",
    },
}
```

Handled by `GttFallbackBook` — no strategy-local polling.

### 4. Shared India options — `IndiaMktMixins`

Chain fetch, expiry (`ExpiryResolver`), hedge intents, rollover, strike-in-premium-range.

### 5. Engine eval mode

- **Candle-driven:** set `timeframe = "60"` (or 5, 15), use `live_feed` eval mode.
- **Clock-driven:** `timeframe = None`, `scheduled_times = [time(9, 20), ...]`.

---

## Recommended optimizations (priority order)

### P0 — Quick wins (low risk)

| Item | Why | Where |
|------|-----|--------|
| **Strategy readme template** | Every new strategy documents hooks + eval mode | `docs/templates/STRATEGY_README.md` |
| **Registry name = `strategy.name`** | Fix IPOBreakout / IPOAnchorVWAP mismatch | registry or class `name` |
| **LEAPS eval on every closed bar for exits** | Already in `_run_exits_and_rollover`; document | done in live_engine |
| **Scheduled engines subscribe underlying** | BTST/OI get index WS for spot + GttFallback base | `_collect_feed_symbols` |

### P1 — Event bus (medium effort, high leverage)

Introduce a lightweight **in-process event bus** so components subscribe instead of `LiveEngine` calling everything:

```python
# Proposed: core/events/bus.py
@dataclass
class Event:
    type: str
    payload: dict
    ts: float

# Publishers: feed, aggregator, scheduler, order_router (fills)
# Subscribers: strategies (filtered), GttFallbackBook, risk, logger
```

| Event type | Publisher | Subscribers |
|------------|-----------|-------------|
| `BarClosed` | CandleAggregator | LiveEngine → strategy workers |
| `ScheduledSlot` | LiveEngine clock | Scheduled strategies |
| `QuoteUpdated` | Dhan feed | GttFallbackBook (push vs poll) |
| `IntentFilled` | OrderRouter | Strategy hooks, bracket registry |
| `PositionChanged` | PositionManager | Risk, reconcile |

**Benefit:** Add strategies without editing `live_engine.py` main loop.

### P2 — Strategy plugin manifest

Single YAML/JSON per strategy:

```yaml
name: MyStrategy
eval_mode: live_feed | scheduled
timeframe: "60"
symbols: [NIFTY]
execution:
  mode: HYBRID_GTT
  gtt_fallback: { trigger_field: ask, trigger_op: "<=", active_until: "15:20" }
hooks:
  mixins: [IndiaMktMixins]
```

Loader builds registry + runtime_spec — reduces boilerplate across 10+ strategies.

### P3 — Unified quote layer

`QuoteService` wrapping feed + REST + instrument_store:

- Single API for strategies, GttFallbackBook, exit refresh
- Push-driven: feed callback → `QuoteUpdated` event
- Removes duplicate `get_best_bid` / `get_quote_v2` paths

### P4 — Execution policy registry

Move fill-gate, HYBRID_GTT, bracket placement into pluggable policies:

```python
EXECUTION_POLICIES = {
    "LIMIT": LimitPolicy(),
    "GTT": GttPolicy(),
    "HYBRID_GTT": HybridGttPolicy(book),
    "HEDGE_GATED_BUNDLE": HedgeGatedBundlePolicy(),
}
```

OrderRouter delegates to policy by `execution_mode` — easier to add `ICEBERG`, `TWAP`, etc.

### P5 — Backtest / live parity tests

Per-strategy golden tests:

- Same candle fixture → same intents in backtest and live `build_context` path
- Expiry resolution unit tests (`LEAPS_ROLL` vs `QUARTERLY`)

### P6 — Observability

- Structured event log (`logs/{engine_id}_events.jsonl`)
- Per-strategy metrics: eval count, intent count, fill latency, GTT fallback rate
- Canvas dashboard for open watches / positions (optional)

---

## Anti-patterns to avoid

| Don't | Do instead |
|-------|------------|
| Poll broker in strategy | Return intents; let OrderRouter + fills drive state |
| Put broker API in strategy | Use `ctx.order_router`, `ctx.position_store` |
| Duplicate expiry logic | `ExpiryResolver` + `expiryType` on class |
| Hardcode IST slots in engine | `scheduled_times` on strategy |
| Document Mar/Jun/Sep quarterly for LEAPS | Document `LEAPS_ROLL` or change code |

---

## Checklist: new strategy in 30 minutes

1. [ ] Subclass `BaseStrategy` (+ `IndiaMktMixins` if options)
2. [ ] Implement `should_evaluate` + `on_candle` (+ exit hooks if positional)
3. [ ] Register in `STRATEGY_MAP` + `STRATEGY_RUNTIME_SPEC`
4. [ ] Add `STRATEGY_JOBS` entry in `run/config.py`
5. [ ] Choose eval mode: candle TF vs `scheduled_times`
6. [ ] Choose execution: default LIMIT vs `HYBRID_GTT`
7. [ ] Add `readme.md` next to strategy module (use BTST or LEAPS as template)
8. [ ] Paper trade → verify logs + intent_store + positions reconcile

---

## Files to read first

| File | Why |
|------|-----|
| `core/strategies/base.py` | Hook contract |
| `core/strategies/registry.py` | Registration |
| `core/engine/live_engine.py` | Main loop, scheduled + feed paths |
| `core/orderExecution/order_router.py` | Execution + fills |
| `core/orderExecution/gtt_fallback_book.py` | HYBRID_GTT pattern |
| `core/strategies/IndiaMktMixins.py` | India options shared logic |
| `docs/runtime_flow.md` | End-to-end live flow |

---

## Summary

You can **build many more strategies today** by composing `BaseStrategy` hooks + registry + optional mixins + execution modes — without rewriting the engine.

The highest-value evolution toward **fully event-driven** operation is:

1. **Event bus** (decouple live loop from strategy wiring)
2. **Push quotes** into `GttFallbackBook` (lower latency than 1s poll)
3. **Execution policy registry** (composable broker behaviors)
4. **Strategy manifest** (less copy-paste per new algo)

Implement P1–P2 when you have 5+ active live strategies or multiple engines sharing feeds.
