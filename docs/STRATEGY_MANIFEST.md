# Strategy plugin manifest

One `strategy.yaml` per strategy is the **source of truth** for declarative wiring. Python classes keep trading logic; manifests drive registry, profiles, runtime data spec, and metadata keys.

## Quick start

```bash
pip install PyYAML

# 1. Copy template for a new strategy
cp docs/templates/strategy.yaml core/strategies/MyPkg/MyStrategy/strategy.yaml

# 2. Edit manifest + implement MyStrategy.py (name must match manifest id)

# 3. Regenerate wiring
python -m tools.strategy_manifest generate

# 4. Optional: validate only
python -m tools.strategy_manifest validate

# 5. CI / pre-commit: fail if generated files are stale
python -m tools.strategy_manifest check
```

## Manifest location

Place `strategy.yaml` next to the strategy module:

```
core/strategies/BTST/BankNiftyBTST/
  BankNiftyBTST.py      # logic
  strategy.yaml         # wiring
  readme.md             # rules (hand-written or --readme generate)
```

## What gets generated

| Output | Path |
|--------|------|
| Registry map | `core/strategies/_generated/registry_entries.py` |
| Profiles | `core/strategies/_generated/profiles.py` |
| Runtime spec | `core/strategies/_generated/runtime_spec.py` |
| Meta keys | `core/strategies/_generated/meta_keys.py` |
| Aliases | `core/strategies/_generated/aliases.py` |
| Event subscriptions | `core/strategies/_generated/subscriptions.py` |
| Index table | `docs/STRATEGY_INDEX.generated.md` |

Thin wrappers re-export generated data:

- `core/strategies/registry.py`
- `run/strategy_profiles.py`
- `core/strategies/runtime_spec.py`
- `core/strategies/meta.py`

## Schema overview

| Field | Maps to |
|-------|---------|
| `id` | `STRATEGY_MAP` key, `strategy.name`, runtime spec key |
| `implementation` | Python import path |
| `instrument` | OPTION / FUTURE / EQUITY |
| `allowed_modes` | BACKTEST, PAPER, LIVE |
| `broker` | venue, api, delta block → profile |
| `symbols` | profile + engine symbol union |
| `timeframe` | class/doc reference (live eval TF) |
| `schedule` | `eval_mode`, IST `times` for scheduled |
| `execution` | GTT / HYBRID_GTT defaults (documentation + future policy registry) |
| `data` | `STRATEGY_RUNTIME_SPEC` per mode |
| `profile` | live/backtest blocks → `STRATEGY_PROFILES` |
| `dependencies` | mixins, `meta_key`, `meta_aliases` |
| `documentation` | readme generation (`--readme`) |
| `aliases` | `STRATEGY_ALIASES` (e.g. IPOAnchorVWAP) |
| `subscriptions` | Event bus interest → `_generated/subscriptions.py` (optional; inferred from `schedule` / `execution`) |

Template: `docs/templates/strategy.yaml`

## Event subscriptions

`wire_event_bus()` registers handlers from the **union** of loaded strategies' subscriptions (plus always-on OMS/feed events). Defaults when `subscriptions:` is omitted:

| `schedule.eval_mode` / `execution` | Enabled events |
|------------------------------------|----------------|
| `live_feed` | `BarClosed` (+ infra) |
| `scheduled` | `ScheduledSlot` (+ infra) |
| `GTT` / `HYBRID_GTT` or `gtt_fallback` set | `QuoteUpdated` |

Override in YAML:

```yaml
subscriptions:
  BarClosed:
    enabled: true
    timeframes: ["15"]
    symbols: [NIFTY]
  ScheduledSlot: false
  QuoteUpdated: false
```

Adding strategy #14+: implement class + `strategy.yaml` + `generate` — no `core/events/wiring.py` edits.

## What stays manual

- **Strategy class** — hooks, signals, risk constants
- **`run/config.py` ENGINE_JOBS** — secrets, capital, telegram, multi-strategy engines
- **Entry/exit rules** in readme (unless using `documentation.rules` + `--readme`)

## Bootstrap existing strategies

To recreate all manifests from embedded defaults:

```bash
python -m tools.strategy_manifest bootstrap --force
python -m tools.strategy_manifest generate
```

## Adding strategy #14+

1. Implement `BaseStrategy` subclass with `name = "MyStrategy"`.
2. Add `strategy.yaml` from template.
3. `python -m tools.strategy_manifest generate`
4. Add engine job in `run/config.py` if needed.
5. `graphify update .`

## Validation

`validate` checks:

- Class imports and `class.name == manifest.id`
- Symbol ⊆ `underlying_symbols` when class defines symbols
- Scheduled strategies have `schedule.times`
- Each `allowed_mode` has `data.<mode>` or `data.default`
