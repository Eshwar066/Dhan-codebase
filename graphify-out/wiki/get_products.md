# .get_products

> 13 nodes

## Key Concepts

- **.get_products()** (7 connections) — `core/data/sources/delta_source.py`
- **.place_order()** (6 connections) — `core/data/sources/delta_source.py`
- **._get_tick_size_for_product()** (4 connections) — `core/data/sources/delta_source.py`
- **round_by_tick_size()** (4 connections) — `core/library/delta_rest_client.py`
- **.get_live_option_chain()** (3 connections) — `core/data/sources/delta_source.py`
- **.product_id_for_symbol()** (3 connections) — `core/data/sources/delta_source.py`
- **create_order_format()** (3 connections) — `core/library/delta_rest_client.py`
- **List all tradable products. Cached by default.** (1 connections) — `core/data/sources/delta_source.py`
- **Resolve symbol (e.g. BTCUSD) or product symbol to product_id.** (1 connections) — `core/data/sources/delta_source.py`
- **Return tick_size for product_id from products cache; None if not found.** (1 connections) — `core/data/sources/delta_source.py`
- **Minimal option chain from products (Delta options).** (1 connections) — `core/data/sources/delta_source.py`
- **Place order via Delta. Returns { status, order_id }. side: buy | sell…** (1 connections) — `core/data/sources/delta_source.py`
- **Round price to exchange tick size. Uses Decimal to avoid float precision errors.** (1 connections) — `core/library/delta_rest_client.py`

## Relationships

- [DeltaSource](DeltaSource.md) (8 shared connections)
- [factory.py](factory.py.md) (2 shared connections)
- [delta_rest_client.py](delta_rest_client.py.md) (2 shared connections)

## Source Files

- `core/data/sources/delta_source.py`
- `core/library/delta_rest_client.py`

## Audit Trail

- EXTRACTED: 24 (100%)
- INFERRED: 0 (0%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*