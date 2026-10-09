# roll_leaps_hedge.py

> 28 nodes

## Key Concepts

- **roll_leaps_hedge.py** (42 connections) — `core/strategies/IBBM/Leaps/emergency/roll_leaps_hedge.py`
- **round_by_tick_size()** (14 connections) — `core/utils/price_tick.py`
- **Any** (14 connections)
- **main()** (12 connections) — `core/strategies/IBBM/Leaps/emergency/roll_leaps_hedge.py`
- **_roll_one()** (11 connections) — `core/strategies/IBBM/Leaps/emergency/roll_leaps_hedge.py`
- **price_tick.py** (10 connections) — `core/utils/price_tick.py`
- **_create_new_hedge_intent()** (6 connections) — `core/strategies/IBBM/Leaps/emergency/roll_leaps_hedge.py`
- **_next_month_hedge_expiry()** (6 connections) — `core/strategies/IBBM/Leaps/emergency/roll_leaps_hedge.py`
- **_inst_expiry_date()** (5 connections) — `core/strategies/IBBM/Leaps/emergency/roll_leaps_hedge.py`
- **_recover_orphan_leaps_pairs()** (5 connections) — `core/strategies/IBBM/Leaps/emergency/roll_leaps_hedge.py`
- **_resolve_entry_price()** (5 connections) — `core/strategies/IBBM/Leaps/emergency/roll_leaps_hedge.py`
- **_wait_fills()** (5 connections) — `core/strategies/IBBM/Leaps/emergency/roll_leaps_hedge.py`
- **_place()** (4 connections) — `core/strategies/IBBM/Leaps/emergency/roll_leaps_hedge.py`
- **_resolve_exit_price()** (4 connections) — `core/strategies/IBBM/Leaps/emergency/roll_leaps_hedge.py`
- **_structures_to_roll()** (4 connections) — `core/strategies/IBBM/Leaps/emergency/roll_leaps_hedge.py`
- **_describe_leg()** (3 connections) — `core/strategies/IBBM/Leaps/emergency/roll_leaps_hedge.py`
- **_price_map_for_intent()** (3 connections) — `core/strategies/IBBM/Leaps/emergency/roll_leaps_hedge.py`
- **_synthetic_candle()** (3 connections) — `core/strategies/IBBM/Leaps/emergency/roll_leaps_hedge.py`
- **_write_open_positions_csv()** (3 connections) — `core/strategies/IBBM/Leaps/emergency/roll_leaps_hedge.py`
- **date** (3 connections)
- **decimal** (2 connections)
- **_forced_expiry()** (1 connections) — `core/strategies/IBBM/Leaps/emergency/roll_leaps_hedge.py`
- **One-shot: roll LEAPS monthly hedge — BUY next-month hedge first, then EXIT old.…** (1 connections) — `core/strategies/IBBM/Leaps/emergency/roll_leaps_hedge.py`
- **Return (main, hedge) pairs that have both legs open.** (1 connections) — `core/strategies/IBBM/Leaps/emergency/roll_leaps_hedge.py`
- **Broker reconcile often drops strategy/structure_id and tags both legs MAIN.…** (1 connections) — `core/strategies/IBBM/Leaps/emergency/roll_leaps_hedge.py`
- *... and 3 more nodes in this community*

## Relationships

- [RunMode](RunMode.md) (11 shared connections)
- [typing](typing.md) (8 shared connections)
- [BankNiftyBTST](BankNiftyBTST.md) (5 shared connections)
- [force_leaps_cycle.py](force_leaps_cycle.py.md) (4 shared connections)
- [main.py](main.py.md) (3 shared connections)
- [dummy_live.py](dummy_live.py.md) (3 shared connections)
- [.create_live_engine](create_live_engine.md) (3 shared connections)
- [logging.py](logging.py.md) (3 shared connections)
- [EngineConfig](EngineConfig.md) (2 shared connections)
- [normalize_dhan_tick_size](normalize_dhan_tick_size.md) (2 shared connections)
- [dhan/broker.py](dhan-broker.py.md) (2 shared connections)
- [factory.py](factory.py.md) (2 shared connections)

## Source Files

- `core/strategies/IBBM/Leaps/emergency/roll_leaps_hedge.py`
- `core/utils/price_tick.py`

## Audit Trail

- EXTRACTED: 105 (95%)
- INFERRED: 6 (5%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*