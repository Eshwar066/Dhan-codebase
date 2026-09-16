# Tradehull

> 29 nodes

## Key Concepts

- **Tradehull** (70 connections) — `core/library/dhan_tradehull.py`
- **.order_report()** (3 connections) — `core/library/dhan_tradehull.py`
- **.cancel_all_orders()** (2 connections) — `core/library/dhan_tradehull.py`
- **.get_live_pnl()** (2 connections) — `core/library/dhan_tradehull.py`
- **.send_telegram_alert()** (2 connections) — `core/library/dhan_tradehull.py`
- **library/__init__.py** (2 connections) — `core/library/__init__.py`
- **.cancel_order()** (1 connections) — `core/library/dhan_tradehull.py`
- **.correct_step_df_creation()** (1 connections) — `core/library/dhan_tradehull.py`
- **.get_balance()** (1 connections) — `core/library/dhan_tradehull.py`
- **.get_exchange_time()** (1 connections) — `core/library/dhan_tradehull.py`
- **.get_executed_price()** (1 connections) — `core/library/dhan_tradehull.py`
- **.get_holdings()** (1 connections) — `core/library/dhan_tradehull.py`
- **.get_lot_size()** (1 connections) — `core/library/dhan_tradehull.py`
- **.get_order_detail()** (1 connections) — `core/library/dhan_tradehull.py`
- **.get_order_status()** (1 connections) — `core/library/dhan_tradehull.py`
- **.get_orderbook()** (1 connections) — `core/library/dhan_tradehull.py`
- **.get_positions()** (1 connections) — `core/library/dhan_tradehull.py`
- **.get_quote_data()** (1 connections) — `core/library/dhan_tradehull.py`
- **.get_trade_book()** (1 connections) — `core/library/dhan_tradehull.py`
- **.heikin_ashi()** (1 connections) — `core/library/dhan_tradehull.py`
- **.kill_switch()** (1 connections) — `core/library/dhan_tradehull.py`
- **.ltp_call()** (1 connections) — `core/library/dhan_tradehull.py`
- **.modify_order()** (1 connections) — `core/library/dhan_tradehull.py`
- **.place_slice_order()** (1 connections) — `core/library/dhan_tradehull.py`
- **.renko_bricks()** (1 connections) — `core/library/dhan_tradehull.py`
- *... and 4 more nodes in this community*

## Relationships

- [.get_ltp_data](get_ltp_data.md) (8 shared connections)
- [._get_dhan_http](_get_dhan_http.md) (6 shared connections)
- [.get_login](get_login.md) (5 shared connections)
- [DhanContext](DhanContext.md) (5 shared connections)
- [.convert_to_date_time](convert_to_date_time.md) (4 shared connections)
- [._enrich_df_bs_delta](_enrich_df_bs_delta.md) (4 shared connections)
- [logging.py](logging.py.md) (3 shared connections)
- [_dhan_is_rate_limited](_dhan_is_rate_limited.md) (3 shared connections)
- [typing](typing.md) (2 shared connections)
- [DhanMarketFeedClient](DhanMarketFeedClient.md) (1 shared connections)
- [main](main.md) (1 shared connections)
- [._check_eod_exit](_check_eod_exit.md) (1 shared connections)

## Source Files

- `core/library/__init__.py`
- `core/library/dhan_tradehull.py`

## Audit Trail

- EXTRACTED: 71 (95%)
- INFERRED: 4 (5%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*