# ._get_dhan_http

> 11 nodes

## Key Concepts

- **._get_dhan_http()** (9 connections) — `core/library/dhan_tradehull.py`
- **.forever_order_placement()** (4 connections) — `core/library/dhan_tradehull.py`
- **.margin_calculator_multi()** (4 connections) — `core/library/dhan_tradehull.py`
- **.order_placement()** (4 connections) — `core/library/dhan_tradehull.py`
- **.get_forever_orders()** (3 connections) — `core/library/dhan_tradehull.py`
- **.cancel_forever_order()** (2 connections) — `core/library/dhan_tradehull.py`
- **Place a Dhan Forever (GTT) order via ``POST /forever/orders``. SINGLE: when LTP…** (1 connections) — `core/library/dhan_tradehull.py`
- **List all Forever (GTT) orders via ``GET /forever/orders``.** (1 connections) — `core/library/dhan_tradehull.py`
- **Multi-leg margin (hedge benefit). Each scrip dict: tradingsymbol, exchange,…** (1 connections) — `core/library/dhan_tradehull.py`
- **Resolve Dhan REST client for v2 endpoints (/orders, /margincalculator/multi,…** (1 connections) — `core/library/dhan_tradehull.py`
- **correlation_id: same value sent as REST ``correlationId`` (dhanhq maps ``tag``…** (1 connections) — `core/library/dhan_tradehull.py`

## Relationships

- [Tradehull](Tradehull.md) (6 shared connections)
- [DhanBroker](DhanBroker.md) (3 shared connections)
- [_DhanRestHttp](_DhanRestHttp.md) (1 shared connections)
- [._enrich_df_bs_delta](_enrich_df_bs_delta.md) (1 shared connections)

## Source Files

- `core/library/dhan_tradehull.py`

## Audit Trail

- EXTRACTED: 20 (95%)
- INFERRED: 1 (5%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*