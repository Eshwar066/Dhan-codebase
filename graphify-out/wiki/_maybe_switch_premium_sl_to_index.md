# ._maybe_switch_premium_sl_to_index

> 14 nodes

## Key Concepts

- **._maybe_switch_premium_sl_to_index()** (12 connections) — `core/strategies/crypto/DirectionalOptionSelling/DirectionalOptionSelling.py`
- **._cancel_resting_main_sl()** (8 connections) — `core/strategies/crypto/DirectionalOptionSelling/DirectionalOptionSelling.py`
- **._live_option_limit_price()** (7 connections) — `core/strategies/crypto/DirectionalOptionSelling/DirectionalOptionSelling.py`
- **._live_exit_limit_price()** (5 connections) — `core/strategies/crypto/DirectionalOptionSelling/DirectionalOptionSelling.py`
- **._live_option_mark_price()** (5 connections) — `core/strategies/crypto/DirectionalOptionSelling/DirectionalOptionSelling.py`
- **._short_premium_pnl_positive()** (3 connections) — `core/strategies/crypto/DirectionalOptionSelling/DirectionalOptionSelling.py`
- **._st_moved_favorably()** (3 connections) — `core/strategies/crypto/DirectionalOptionSelling/DirectionalOptionSelling.py`
- **Best ask (BUY cover) or best bid (SELL) when available.** (1 connections) — `core/strategies/crypto/DirectionalOptionSelling/DirectionalOptionSelling.py`
- **Best ask for BUY / best bid for SELL on an option symbol.** (1 connections) — `core/strategies/crypto/DirectionalOptionSelling/DirectionalOptionSelling.py`
- **Option mark / mid for short unrealized P&L (premium decay = green).** (1 connections) — `core/strategies/crypto/DirectionalOptionSelling/DirectionalOptionSelling.py`
- **Short option is green when mark has decayed below entry premium.** (1 connections) — `core/strategies/crypto/DirectionalOptionSelling/DirectionalOptionSelling.py`
- **PE short (dir>0): ST rising; CE short (dir<0): ST falling.** (1 connections) — `core/strategies/crypto/DirectionalOptionSelling/DirectionalOptionSelling.py`
- **Cancel resting broker MAIN_SL (FORCE_EXIT) so MAIN_EXIT can be placed. Without…** (1 connections) — `core/strategies/crypto/DirectionalOptionSelling/DirectionalOptionSelling.py`
- **While on premium SL: if short is green and ST moved favorably, cancel the mark…** (1 connections) — `core/strategies/crypto/DirectionalOptionSelling/DirectionalOptionSelling.py`

## Relationships

- [Any](Any.md) (8 shared connections)
- [DirectionalOptionSelling](DirectionalOptionSelling.md) (7 shared connections)
- [normalize_underlying](normalize_underlying.md) (3 shared connections)
- [SimulatedBroker](SimulatedBroker.md) (2 shared connections)
- [typing](typing.md) (2 shared connections)
- [DeltaBroker](DeltaBroker.md) (1 shared connections)
- [DirectionalOptionSellingTests](DirectionalOptionSellingTests.md) (1 shared connections)

## Source Files

- `core/strategies/crypto/DirectionalOptionSelling/DirectionalOptionSelling.py`

## Audit Trail

- EXTRACTED: 34 (92%)
- INFERRED: 3 (8%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*