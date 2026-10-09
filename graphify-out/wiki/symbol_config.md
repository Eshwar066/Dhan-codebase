# symbol_config

> 13 nodes

## Key Concepts

- **symbol_config()** (14 connections) — `core/strategies/crypto/DirectionalOptionSelling/constants.py`
- **._sleeve_entries_enabled()** (11 connections) — `core/strategies/crypto/DirectionalOptionSelling/DirectionalOptionSelling.py`
- **._symbol_entries_enabled()** (7 connections) — `core/strategies/crypto/DirectionalOptionSelling/DirectionalOptionSelling.py`
- **option_root_for()** (5 connections) — `core/strategies/crypto/DirectionalOptionSelling/constants.py`
- **Any** (4 connections)
- **.test_sleeve_entry_enable_flags()** (3 connections) — `core/strategies/crypto/DirectionalOptionSelling/tests/test_directional_option_selling.py`
- **.test_symbol_config_btc_vs_eth_and_runtime_isolation()** (3 connections) — `core/strategies/crypto/DirectionalOptionSelling/tests/test_directional_option_selling.py`
- **.test_symbol_entry_enable_flags()** (3 connections) — `core/strategies/crypto/DirectionalOptionSelling/tests/test_directional_option_selling.py`
- **._force_exit_level()** (3 connections) — `core/strategies/crypto/DirectionalOptionSelling/trail_sl.py`
- **Return knobs for ``symbol``; falls back to BTCUSD when unknown.** (1 connections) — `core/strategies/crypto/DirectionalOptionSelling/constants.py`
- **Master per-underlying gate for new entries / SL re-entries.** (1 connections) — `core/strategies/crypto/DirectionalOptionSelling/DirectionalOptionSelling.py`
- **Whether new entries / SL re-entries are allowed for this sleeve.** (1 connections) — `core/strategies/crypto/DirectionalOptionSelling/DirectionalOptionSelling.py`
- **Strategy emergency exit level. Bullish: ST − pts. Bearish: ST + pts.** (1 connections) — `core/strategies/crypto/DirectionalOptionSelling/trail_sl.py`

## Relationships

- [Any](Any.md) (6 shared connections)
- [typing](typing.md) (5 shared connections)
- [normalize_underlying](normalize_underlying.md) (5 shared connections)
- [DirectionalOptionSelling](DirectionalOptionSelling.md) (4 shared connections)
- [DirectionalOptionSellingTests](DirectionalOptionSellingTests.md) (3 shared connections)
- [DosTrailSlMixin](DosTrailSlMixin.md) (2 shared connections)
- [RunMode](RunMode.md) (2 shared connections)

## Source Files

- `core/strategies/crypto/DirectionalOptionSelling/DirectionalOptionSelling.py`
- `core/strategies/crypto/DirectionalOptionSelling/constants.py`
- `core/strategies/crypto/DirectionalOptionSelling/tests/test_directional_option_selling.py`
- `core/strategies/crypto/DirectionalOptionSelling/trail_sl.py`

## Audit Trail

- EXTRACTED: 42 (100%)
- INFERRED: 0 (0%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*