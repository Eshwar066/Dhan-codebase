# Legacy keys (read-only compatibility)

> 15 nodes

## Key Concepts

- **Legacy keys (read-only compatibility)** (9 connections) — `docs/templates/META_SCHEMA.md`
- **._restore_oi_meta_from_position()** (8 connections) — `core/strategies/OpenIntrest/OIPostionalBuy/OIPosBuy.py`
- **._ensure_oi_meta_for_main_fill()** (6 connections) — `core/strategies/OpenIntrest/OIPostionalBuy/OIPosBuy.py`
- **._meta_from_position_fallback()** (6 connections) — `core/strategies/OpenIntrest/OIPostionalBuy/OIPosBuy.py`
- **entry_price()** (5 connections) — `core/strategies/IBBM/Leaps/emergency/retry_leaps_main.py`
- **._parse_structure_id()** (5 connections) — `core/strategies/OpenIntrest/OIPostionalBuy/OIPosBuy.py`
- **.restore_state_on_startup()** (5 connections) — `core/strategies/OpenIntrest/OIPostionalBuy/OIPosBuy.py`
- **Strategy metadata schema** (5 connections) — `docs/templates/META_SCHEMA.md`
- **._try_merge_oi_meta_from_raw()** (4 connections) — `core/strategies/OpenIntrest/OIPostionalBuy/OIPosBuy.py`
- **Required fields** (2 connections) — `docs/templates/META_SCHEMA.md`
- **META_SCHEMA.md** (1 connections) — `docs/templates/META_SCHEMA.md`
- **Canonical shape** (1 connections) — `docs/templates/META_SCHEMA.md`
- **Read path** (1 connections) — `docs/templates/META_SCHEMA.md`
- **OIPositionalBuy:NIFTY:2026-05-22:L1:CE:24600 -> symbol, date, opt, strike.** (1 connections) — `core/strategies/OpenIntrest/OIPostionalBuy/OIPosBuy.py`
- **Reload in-memory PositionMeta for open MAIN legs after engine restart.** (1 connections) — `core/strategies/OpenIntrest/OIPostionalBuy/OIPosBuy.py`

## Relationships

- [OIPositionalBuy](OIPositionalBuy.md) (16 shared connections)
- [.create_live_engine](create_live_engine.md) (1 shared connections)
- [.reconcile_with_broker](reconcile_with_broker.md) (1 shared connections)
- [.sync_tracking_from_broker](sync_tracking_from_broker.md) (1 shared connections)
- [.option_identity_key](option_identity_key.md) (1 shared connections)
- [NeoAPI](NeoAPI.md) (1 shared connections)
- [BankNiftyBTST](BankNiftyBTST.md) (1 shared connections)
- [LiquiditySweepStrategy](LiquiditySweepStrategy.md) (1 shared connections)
- [Any](Any.md) (1 shared connections)
- [NiftyIntradayMagicalLine](NiftyIntradayMagicalLine.md) (1 shared connections)
- [OneDayMagicalLine](OneDayMagicalLine.md) (1 shared connections)
- [RSIBreadAndButter](RSIBreadAndButter.md) (1 shared connections)

## Source Files

- `core/strategies/IBBM/Leaps/emergency/retry_leaps_main.py`
- `core/strategies/OpenIntrest/OIPostionalBuy/OIPosBuy.py`
- `docs/templates/META_SCHEMA.md`

## Audit Trail

- EXTRACTED: 30 (68%)
- INFERRED: 14 (32%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*