# Strategy index

Canonical inventory of registered strategies. **Registry key**, **`strategy.name`**, and **`STRATEGY_RUNTIME_SPEC`** key must match (aliases live in `core/strategies/registry.py`).

## Naming contract

| Layer | File | Key |
|-------|------|-----|
| Registry / config / profiles | `STRATEGY_MAP`, `ENGINE_JOBS`, `STRATEGY_PROFILES` | PascalCase registry key (e.g. `IPOBreakout`) |
| Class attribute | `BaseStrategy.name` | Same as registry key |
| Runtime data spec | `STRATEGY_RUNTIME_SPEC` | Same as `strategy.name` |
| Metadata (legacy) | `metadata_extras["<snake_case>"]` | See `core/strategies/meta.py` |
| Metadata (canonical) | `metadata_extras["strategy_meta"]` | `{"strategy": "<RegistryKey>", ...}` |

Resolve unknown names: `resolve_registry_key(name)` in `core/strategies/registry.py`.

## Registered strategies

| Registry key | Class | Instrument | Venue | Profile | Runtime spec | Readme |
|--------------|-------|------------|-------|---------|--------------|--------|
| `LEAPS_RSI` | `LeapsQuarterly` | OPTION | DHAN | yes | yes | `Leaps/readme.txt` |
| `BankNiftyBTST` | `BankNiftyBTST` | OPTION | DHAN | yes | yes | `BTST/BankNiftyBTST/readme.md` |
| `MagicalLines` | `MagicalLines` | OPTION | DHAN | yes | yes | `MagicalLines/readme.md` |
| `NiftyIntradayMagicalLine` | `NiftyIntradayMagicalLine` | OPTION | DHAN | yes | yes | `MagicalLines/NiftyIntradayMagicalLine/readme.md` |
| `OneDayMagicalLine` | `OneDayMagicalLine` | OPTION | DELTA | yes | yes | `crypto/oneDayMagicalLine/readme.md` |
| `OIPositionalBuy` | `OIPositionalBuy` | OPTION | DHAN | yes | yes | `OpenIntrest/OIPostionalBuy/readme.md` |
| `OptionBuildup` | `OptionBuildup` | OPTION | DHAN | yes | yes | `OpenIntrest/optionbuildup/readme.md` |
| `FuturesEMAHighLow` | `FuturesEMAHighLow` | FUTURE | DHAN | yes | yes | `Futures/Futures_EMA/readme.md` |
| `Futures_EMA_Momentum` | `FuturesEMAMomentum` | FUTURE | DELTA | yes | yes | `Futures/Futures_EMA_Momentum/readme.md` |
| `IPOBreakout` | `IPOBreakout` | EQUITY | DHAN | yes | yes | `Equity/IPOBreakout/README.md` |
| `RSIBreadAndButter` | `RSIBreadAndButter` | FUTURE | DELTA | yes | yes | `crypto/RSIBreadAndButter/readme.md` |
| `LiquiditySweepStrategy` | `LiquiditySweepStrategy` | FUTURE | DELTA | yes | yes | `crypto/LiquiditySweepStrategy/readme.md` |
| `SignalFloodTest` | `SignalFloodTestStrategy` | FUTURE | DHAN/DELTA | yes | yes | `PipelineTest/readme.md` |

## Eval modes

| Mode | Set in | Engine behavior |
|------|--------|-----------------|
| `live_feed` (default) | `timeframe` on class + profile | Exits on every closed bar; entries gated by `should_evaluate` |
| `scheduled` | `eval_mode: "scheduled"` + `scheduled_times` | Synthetic candle at IST slots; BTST / OI snapshots |

See `docs/EVENT_DRIVEN_STRATEGY_GUIDE.md` → **Entry vs exit evaluation**.

## Adding a strategy (checklist)

1. Implement class; set `name` = registry key.
2. Add `strategy.yaml` from `docs/templates/strategy.yaml`.
3. Run `python -m tools.strategy_manifest generate`.
4. Optional `ENGINE_JOBS` entry in `run/config.py`.
5. `readme.md` for rules (or `generate --readme MyStrategy`).
6. Run `graphify update .` after code changes.

See `docs/STRATEGY_MANIFEST.md` for the full workflow.

## Registered strategies

Auto-generated table: `docs/STRATEGY_INDEX.generated.md`
