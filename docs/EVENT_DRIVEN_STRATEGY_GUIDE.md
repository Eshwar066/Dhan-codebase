# Event-Driven Strategy Guide

How to add strategies on top of the live event bus and strategy manifests.

## Current architecture

```
Market data events          Strategy events              Execution events
──────────────────          ───────────────              ────────────────
WS tick                     BarClosed / ScheduledSlot    IntentCreated
  → tick queue                → exits + rollover           → OMS enqueue
  → CandleAggregator          → should_evaluate            → account router
  → closed bar → BarClosed    → on_candle                  → broker place/fill
scheduled IST → ScheduledSlot → should_exit / rollover     → IntentFilled
QuoteUpdated (feed push)      → on_main_entry_filled       → PositionClosed
  → GttFallbackBook.on_quote
FeedDisconnected / Recovered
```

Live is **hybrid**: an in-process event bus drives strategy/OMS wiring (`docs/EVENT_BUS.md`); the main loop still polls (~1s) for feed health, GTT maintenance, and scheduled slots.

Manifests + generator: `docs/STRATEGY_MANIFEST.md`.

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

### Entry vs exit evaluation (live)

On each **closed bar** (`BarClosed` → services):

1. **Exits + rollover** — for every loaded strategy with open MAIN legs:
   - `should_exit` → `on_position_exit`
   - `on_candle_rollover` (hedge roll)
   - Does **not** call `should_evaluate`
2. **Entry path** — `should_evaluate(candle)` must return true, then `on_candle(candle, ctx)`

Implications:

| Concern | Pattern |
|---------|---------|
| Time-based exit (RSI cross, trail, partial) | Implement in `should_exit` / structure hooks; runs every closed bar |
| Entry window (crossover, slot, divergence age) | Gate in `should_evaluate` |
| Scheduled BTST / OI | `eval_mode: scheduled`, `timeframe = None`, `scheduled_times` |
| LEAPS hourly | Exits on every 60m close; entries only when `should_evaluate` allows |

Do **not** rely on `should_evaluate` for managing open positions — exits will not run if you gate the whole strategy there.

### 2. Registration (manifest)

Add `core/strategies/**/strategy.yaml`, then:

```bash
python -m tools.strategy_manifest generate
```

That refreshes `core/strategies/_generated/` (registry, profiles, runtime spec, aliases, subscriptions). Enable the job in `run/config.py` `ENGINE_JOBS`. See `docs/STRATEGY_MANIFEST.md` and `docs/templates/strategy.yaml`.

Optional event filters in YAML:

```yaml
subscriptions:
  BarClosed:
    enabled: true
    timeframes: ["15"]
  QuoteUpdated: false
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

Handled by `GttFallbackBook` via push `QuoteUpdated` (+ quiet-feed REST fallback) — no strategy-local polling.

### 4. Shared India options — `IndiaMktMixins`

Chain fetch, expiry (`ExpiryResolver`), hedge intents, rollover, strike-in-premium-range.

### 5. Engine eval mode

- **Candle-driven:** set `timeframe = "60"` (or 5, 15), use `live_feed` eval mode.
- **Clock-driven:** `timeframe = None`, `scheduled_times = [time(9, 20), ...]`.

---

## Remaining optimizations (priority order)

### P0 — Quick wins

| Item | Why | Where |
|------|-----|--------|
| **Scheduled engines subscribe underlying** | BTST/OI get index WS for spot + GttFallback base | `_collect_feed_symbols` |

### P1 — Unified quote layer

`QuoteService` wrapping feed + REST + instrument_store:

- Single API for strategies, GttFallbackBook, exit refresh
- Collapse remaining duplicate `get_best_bid` / `get_quote_v2` paths
- (Feed → `QuoteUpdated` for GTT watches is already wired; this is the shared facade)

### P2 — Execution policy registry

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

### P3 — Backtest / live parity tests

Per-strategy golden tests:

- Same candle fixture → same intents in backtest and live `build_context` path
- Expiry resolution unit tests (`LEAPS_ROLL` vs `QUARTERLY`)

### P4 — Observability

- Per-strategy metrics: eval count, intent count, fill latency, GTT fallback rate
- Canvas dashboard for open watches / positions (optional)

Event JSONL tap already exists (`logs/{engine_id}_events.jsonl`; `ALGO_EVENT_TAP=0` to disable).

---

## Anti-patterns to avoid

| Don't | Do instead |
|-------|------------|
| Poll broker in strategy | Return intents; let OrderRouter + fills drive state |
| Put broker API in strategy | Use `ctx.order_router`, `ctx.position_store` |
| Duplicate expiry logic | `ExpiryResolver` + `expiryType` on class |
| Hardcode IST slots in engine | `scheduled_times` on strategy |
| Hand-edit `_generated/` or skip YAML | Edit `strategy.yaml` + regenerate |
| Document Mar/Jun/Sep quarterly for LEAPS | Document `LEAPS_ROLL` or change code |

---

## Checklist: new strategy in 30 minutes

1. [ ] Subclass `BaseStrategy` (+ `IndiaMktMixins` if options)
2. [ ] Implement `should_evaluate` + `on_candle` (+ exit hooks if positional)
3. [ ] Add `strategy.yaml` + run `python -m tools.strategy_manifest generate`
4. [ ] Add `ENGINE_JOBS` entry in `run/config.py` (if new engine)
5. [ ] Choose eval mode: candle TF vs `scheduled_times` (and optional `subscriptions:`)
6. [ ] Choose execution: default LIMIT vs `HYBRID_GTT`
7. [ ] Add `readme.md` next to strategy module (use `docs/templates/STRATEGY_README.md`)
8. [ ] Paper trade → verify logs + intent_store + positions reconcile

---

## Files to read first

| File | Why |
|------|-----|
| `core/strategies/base.py` | Hook contract |
| `docs/STRATEGY_MANIFEST.md` | Plugin YAML + generate |
| `docs/EVENT_BUS.md` | Events, services, subscriptions |
| `core/strategies/registry.py` | Registration + `resolve_registry_key` |
| `core/strategies/meta.py` | Standard `metadata_extras` helpers |
| `docs/STRATEGY_INDEX.md` | Full strategy inventory |
| `core/engine/live_engine.py` | Main loop, scheduled + feed paths |
| `core/orderExecution/order_router.py` | Execution + fills |
| `core/orderExecution/gtt_fallback_book.py` | HYBRID_GTT pattern |
| `core/strategies/IndiaMktMixins.py` | India options shared logic |
| `docs/runtime_flow.md` | End-to-end live flow |

---

## Summary

Add strategies via `BaseStrategy` hooks + `strategy.yaml` + `ENGINE_JOBS` — no engine or handler registration edits for normal cases.

Still worth doing for a cleaner platform: **unified QuoteService**, **execution policy registry**, **parity tests**, and **per-strategy metrics**.
