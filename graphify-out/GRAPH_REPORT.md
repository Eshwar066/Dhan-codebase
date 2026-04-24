# Graph Report - C:\Users\eshwa\Desktop\Algo  (2026-04-24)

## Corpus Check
- 124 files · ~138,680 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 2044 nodes · 5100 edges · 61 communities detected
- Extraction: 52% EXTRACTED · 48% INFERRED · 0% AMBIGUOUS · INFERRED: 2432 edges (avg confidence: 0.64)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- [[_COMMUNITY_Community 0|Community 0]]
- [[_COMMUNITY_Community 1|Community 1]]
- [[_COMMUNITY_Community 2|Community 2]]
- [[_COMMUNITY_Community 3|Community 3]]
- [[_COMMUNITY_Community 4|Community 4]]
- [[_COMMUNITY_Community 5|Community 5]]
- [[_COMMUNITY_Community 6|Community 6]]
- [[_COMMUNITY_Community 7|Community 7]]
- [[_COMMUNITY_Community 8|Community 8]]
- [[_COMMUNITY_Community 9|Community 9]]
- [[_COMMUNITY_Community 10|Community 10]]
- [[_COMMUNITY_Community 11|Community 11]]
- [[_COMMUNITY_Community 12|Community 12]]
- [[_COMMUNITY_Community 13|Community 13]]
- [[_COMMUNITY_Community 14|Community 14]]
- [[_COMMUNITY_Community 15|Community 15]]
- [[_COMMUNITY_Community 16|Community 16]]
- [[_COMMUNITY_Community 17|Community 17]]
- [[_COMMUNITY_Community 18|Community 18]]
- [[_COMMUNITY_Community 19|Community 19]]
- [[_COMMUNITY_Community 20|Community 20]]
- [[_COMMUNITY_Community 21|Community 21]]
- [[_COMMUNITY_Community 22|Community 22]]
- [[_COMMUNITY_Community 23|Community 23]]
- [[_COMMUNITY_Community 24|Community 24]]
- [[_COMMUNITY_Community 25|Community 25]]
- [[_COMMUNITY_Community 26|Community 26]]
- [[_COMMUNITY_Community 27|Community 27]]
- [[_COMMUNITY_Community 28|Community 28]]
- [[_COMMUNITY_Community 29|Community 29]]
- [[_COMMUNITY_Community 30|Community 30]]
- [[_COMMUNITY_Community 31|Community 31]]
- [[_COMMUNITY_Community 32|Community 32]]
- [[_COMMUNITY_Community 33|Community 33]]
- [[_COMMUNITY_Community 34|Community 34]]
- [[_COMMUNITY_Community 35|Community 35]]
- [[_COMMUNITY_Community 36|Community 36]]
- [[_COMMUNITY_Community 37|Community 37]]
- [[_COMMUNITY_Community 38|Community 38]]
- [[_COMMUNITY_Community 39|Community 39]]
- [[_COMMUNITY_Community 40|Community 40]]
- [[_COMMUNITY_Community 41|Community 41]]
- [[_COMMUNITY_Community 42|Community 42]]
- [[_COMMUNITY_Community 43|Community 43]]
- [[_COMMUNITY_Community 44|Community 44]]
- [[_COMMUNITY_Community 45|Community 45]]
- [[_COMMUNITY_Community 46|Community 46]]
- [[_COMMUNITY_Community 47|Community 47]]
- [[_COMMUNITY_Community 48|Community 48]]
- [[_COMMUNITY_Community 49|Community 49]]
- [[_COMMUNITY_Community 50|Community 50]]
- [[_COMMUNITY_Community 51|Community 51]]
- [[_COMMUNITY_Community 52|Community 52]]
- [[_COMMUNITY_Community 53|Community 53]]
- [[_COMMUNITY_Community 54|Community 54]]
- [[_COMMUNITY_Community 55|Community 55]]
- [[_COMMUNITY_Community 56|Community 56]]
- [[_COMMUNITY_Community 57|Community 57]]
- [[_COMMUNITY_Community 58|Community 58]]
- [[_COMMUNITY_Community 59|Community 59]]
- [[_COMMUNITY_Community 60|Community 60]]

## God Nodes (most connected - your core abstractions)
1. `RunMode` - 123 edges
2. `IndiaMktMixins` - 84 edges
3. `Tradehull` - 75 edges
4. `ExpiryResolver` - 74 edges
5. `LiveEngine` - 69 edges
6. `SessionManager` - 68 edges
7. `DeltaSource` - 62 edges
8. `StallWatchdog` - 58 edges
9. `BaseStrategy` - 58 edges
10. `DeltaRestClient` - 57 edges

## Surprising Connections (you probably didn't know these)
- `BaseBroker` --uses--> `Find order in live list; if not there, look up in /v2/orders/history and /v2/fil`  [INFERRED]
  C:\Users\eshwa\Desktop\Algo\core\broker\base.py → C:\Users\eshwa\Desktop\Algo\core\broker\internal\delta\broker.py
- `BaseBroker` --uses--> `Resolve order status from order history or fills when not in live list.`  [INFERRED]
  C:\Users\eshwa\Desktop\Algo\core\broker\base.py → C:\Users\eshwa\Desktop\Algo\core\broker\internal\delta\broker.py
- `BaseBroker` --uses--> `Resolve fill price and size from /v2/fills for a given client_order_id (intent_i`  [INFERRED]
  C:\Users\eshwa\Desktop\Algo\core\broker\base.py → C:\Users\eshwa\Desktop\Algo\core\broker\internal\delta\broker.py
- `BaseBroker` --uses--> `Resolve fill by broker order_id when fill API does not return client_order_id.`  [INFERRED]
  C:\Users\eshwa\Desktop\Algo\core\broker\base.py → C:\Users\eshwa\Desktop\Algo\core\broker\internal\delta\broker.py
- `Thin wrapper around DhanOrderUpdateClient for LiveEngine wiring.` --uses--> `DhanOrderUpdateClient`  [INFERRED]
  C:\Users\eshwa\Desktop\Algo\core\data\feeds\dhan_order_update_feed.py → C:\Users\eshwa\Desktop\Algo\core\library\dhan_order_update_ws.py

## Communities

### Community 0 - "Community 0"
Cohesion: 0.02
Nodes (129): AccountRouter, AccountRoutingConfig, all_accounts(), _dedupe_keep_order(), Deterministic, side-effect-free mapping from intent -> account ids., BacktestEngine, BaseBroker, BaseEngine (+121 more)

### Community 1 - "Community 1"
Cohesion: 0.02
Nodes (119): Find order in live list; if not there, look up in /v2/orders/history and /v2/fil, Resolve order status from order history or fills when not in live list., Resolve fill price and size from /v2/fills for a given client_order_id (intent_i, Resolve fill by broker order_id when fill API does not return client_order_id., INR available margin/cash from Dhan fund limits — same keys as DeltaBroker, raise_for_status(), Raises :class:`HTTPError`, if one occurred., atm_label_from_spot_strike() (+111 more)

### Community 2 - "Community 2"
Cohesion: 0.02
Nodes (95): BaseAdapter, BaseStrategy, StrategyContext without calling ``on_candle`` (for fill-time hooks)., SimulatedBroker: fire resting MAIN_SL when option LTP crosses trigger (backtest/, Optional: broker-driven close (liquidation, orphan fill, etc.). Override to sync, Uniquely identifies a tradable contract (netting, hedges, rollovers)., Resolve option contract to Instrument for order intent. Returns None if not foun, Resolve futures contract to Instrument. Returns None if not found. (+87 more)

### Community 3 - "Community 3"
Cohesion: 0.02
Nodes (100): Return up to max_bars last closed candles for symbol/resolution (newest last)., _resolution_to_seconds(), Subscribe to ``l2_orderbook`` for ``symbol`` if not already covered., Raw L2 order book for symbol (bids/asks). Used for best bid/ask., Best bid price for symbol from L2 order book. For Delta limit BUY at best bid., Best ask price for symbol from L2 order book. For Delta limit SELL at best ask., Thread-safe: update instruments; applied on next reconnect., Return latest depth for symbol: {bids: [{price, quantity, num_orders}, ...], ask (+92 more)

### Community 4 - "Community 4"
Cohesion: 0.02
Nodes (48): Abstract base for real-time market/account feeds (WebSocket).  Implementations:, Interface for a real-time feed (WebSocket) that can supply:     - Ticker / LTP p, Last ticker/LTP for symbol. Keys may include: close, mark_price, symbol, etc., Last closed (or latest) candle for symbol.         resolution: e.g. "1m", "5m",, Open/pending orders for symbol (if private feed supported)., Current positions by symbol (if private feed supported)., Optional: set engine-owned queue for tick streaming. When set, feed pushes, RealtimeFeed (+40 more)

### Community 5 - "Community 5"
Cohesion: 0.03
Nodes (59): DeltaBrokerApi, _ensure_list_str(), Order history via order_history (v2/orders/history) for resolving fill status wh, Fills via fills() (v2/fills) for order fill status., Resolve symbol to Delta product_id (e.g. BTCUSD -> id)., Edit orders in batch (e.g. update limit_price). Each order: { 'id': order_id, 'l, Set leverage for a Delta product (by product_id)., Set leverage for each symbol in the list. Resolves symbol -> product_id and call (+51 more)

### Community 6 - "Community 6"
Cohesion: 0.03
Nodes (58): _order_intent_to_payload(), Check available balance and required/SPAN margin before placing order., Convert OrderIntent to dict for Dhan payload., _is_delta_ticker_message(), Match Delta ``v2/ticker`` updates. Some builds use different ``type`` casing, DeltaMktMixins, _append_live_strike_scan_rows(), delta_option_trading_symbol() (+50 more)

### Community 7 - "Community 7"
Cohesion: 0.03
Nodes (59): Remove resting MAIN_SL when the main position exits via MAIN_EXIT (normal exit)., For short options, SL triggers when option premium (LTP) >= trigger (stop on pre, Paper: no open orders (instant fill). Same interface as live so order-state veri, Paper: fills already applied in place_order via process_fill. Same interface as, Paper: orders are filled immediately, so never in open list. Same interface as l, Paper: fill already applied in place_order. Same interface as live for missing-o, Paper: same as get_fill_for_client_order_id. Same interface as live., Enum (+51 more)

### Community 8 - "Community 8"
Cohesion: 0.02
Nodes (46): DeltaWebSocketFeed, Delta Exchange WebSocket feed implementing RealtimeFeed.  Subscribes to v2/tic, Set event-driven callback for private user-trade events., Real-time feed using Delta Exchange WebSocket.     Subscribes to ticker and can, Drain recent private user-trade events from WebSocket buffer., Push normalized ticks to queue for CandleAggregator. Set before start()., generate_signature(), DeltaWebSocket (+38 more)

### Community 9 - "Community 9"
Cohesion: 0.05
Nodes (42): ABC, BaseInstrumentStore, IBrokerApi, Instrument, Shared instrument model and abstract store interface. Broker-specific logic liv, Contract for order placement and position/order lookup at the exchange.     Imp, Single tradable contract (option/future/equity). Used by order intents and posit, List of orders for idempotency / status lookup. (+34 more)

### Community 10 - "Community 10"
Cohesion: 0.04
Nodes (53): load_position_metadata_from_csv(), OpenPositionsLogger, _parse_net_qty(), CSV snapshot of currently open positions only (fills + live broker reconcile)., - Fills (paper + live): updates that symbol's row when qty changes; removes the, On startup, collapse older append-only logs to one row per still-open symbol., One-time migrate older CSVs when new columns are introduced (rewrite in place)., Last row wins per symbol; keep only symbols that are still open (net_qty != 0 (+45 more)

### Community 11 - "Community 11"
Cohesion: 0.05
Nodes (18): IDataProvider, Contract for market data used by engines and order management.     Implementati, NSE expiry dates for a symbol/year. Optional for non-NSE providers., Live option chain (e.g. Dhan format)., Expired option data for backtest (e.g. Dhan)., Return lot size for symbol when known; None otherwise. Override in broker implem, DeltaDataProvider, Delta Exchange implementation of the data layer. Delegates to DeltaSource for m (+10 more)

### Community 12 - "Community 12"
Cohesion: 0.08
Nodes (28): EquityUniverseService, _parse_nse_equity_l(), Equity universe service: loads NSE equity list from EQUITY_L (daily sync). Sour, Load from EQUITY_L_latest.csv (in cache_dir, e.g. Dependencies/equity_universe);, Return list of all equity symbols., Days since listing for symbol. None if unknown or not in universe.         Pure, Re-download if needed and reload from EQUITY_L_latest.csv (in cache_dir)., Return { symbol: EquityMeta } for symbols that exist in universe. (+20 more)

### Community 13 - "Community 13"
Cohesion: 0.07
Nodes (25): DhanBrokerApi, Dhan broker API: order placement and position/order lookup via Dhan., Fills from order list (filled/TRADED orders) for trade-led OMS., IBrokerApi implementation for Dhan. Order placement + positions + order list., Simulated broker for both PAPER and BACKTEST. No real exchange; instant fill. PA, _sl_orders_log_path(), diff_against_previous(), download_scrip_master() (+17 more)

### Community 14 - "Community 14"
Cohesion: 0.1
Nodes (7): Dhan private order-update WebSocket feed (incremental fills → synthetic trades)., Incremental fill payloads (see dhan_order_update_ws)., DhanOrderUpdateClient, _is_429_signal(), Dhan Live Order Update WebSocket (private stream).  Docs: https://dhanhq.co/do, Background WebSocket to Dhan order-update stream.     Calls on_synthetic_trade, _txn_to_side()

### Community 15 - "Community 15"
Cohesion: 0.1
Nodes (20): cache_key_delta_intraday(), _drop_flat_candles(), load_df(), File cache for Delta Exchange historical intraday data. Uses data_cache/delta_h, Drop rows where open, high, low, close are all equal (no-trade bars)., Load a DataFrame from Delta cache. Returns None if missing or invalid., Save a DataFrame to Delta cache. Flat candles (o==h==l==c) are not stored., Key for Delta intraday cache: symbol + timeframe. Dates not in key. (+12 more)

### Community 16 - "Community 16"
Cohesion: 0.23
Nodes (9): Calculates start_date and end_date for intraday candles,         ensuring we fe, get_last_candle_close(), is_holiday(), is_market_open(), next_candle_close(), normalize_exchange(), _now(), _tf_to_minutes() (+1 more)

### Community 17 - "Community 17"
Cohesion: 0.29
Nodes (6): _bucket_ts(), _candle_to_dict(), Prop-grade Candle Aggregator: tick → 1m only; higher timeframes from closed 1m o, Aggregate closed 1m into higher TFs; close only when bucket boundary aligns., Integer bucket boundary. ts_sec in Unix seconds; tf_seconds e.g. 60, 300., Process one tick. O(1). Updates only 1m current; closes 1m and propagates when b

### Community 18 - "Community 18"
Cohesion: 0.31
Nodes (4): EquityInstrument, FutureInstrument, Instrument, OptionInstrument

### Community 19 - "Community 19"
Cohesion: 0.33
Nodes (5): postback_body_to_trade_hint(), Dhan Postback (webhook) — optional third path for order lifecycle events.  Doc, Best-effort map of a postback JSON body to fields useful for OMS.     Actual sc, Placeholder: implement HMAC/signature verification per Dhan postback documentati, verify_postback_signature()

### Community 20 - "Community 20"
Cohesion: 0.4
Nodes (2): generate_quarterly_expiries(), last_thursday()

### Community 21 - "Community 21"
Cohesion: 0.4
Nodes (4): generate_monthly_expiries(), last_thursday(), Jan 2025 expiry -> 1 Dec 2024; Feb 2025 expiry -> 1 Jan 2025; etc., two_month_window_start_for_expiry()

### Community 22 - "Community 22"
Cohesion: 0.67
Nodes (1): EDIS (e-disclosure) — required for selling delivery (CNC) equity from demat.

### Community 23 - "Community 23"
Cohesion: 1.0
Nodes (0): 

### Community 24 - "Community 24"
Cohesion: 1.0
Nodes (0): 

### Community 25 - "Community 25"
Cohesion: 1.0
Nodes (0): 

### Community 26 - "Community 26"
Cohesion: 1.0
Nodes (1): Place a single order. Returns dict with "status" and on success "order_id".

### Community 27 - "Community 27"
Cohesion: 1.0
Nodes (1): Current positions (broker-specific format).

### Community 28 - "Community 28"
Cohesion: 1.0
Nodes (1): Place order from OrderIntent or dict. Returns order_id or None.

### Community 29 - "Community 29"
Cohesion: 1.0
Nodes (1): Exit a position explicitly. Must internally call place_order().

### Community 30 - "Community 30"
Cohesion: 1.0
Nodes (0): 

### Community 31 - "Community 31"
Cohesion: 1.0
Nodes (1): Historical intraday candles for backtest.

### Community 32 - "Community 32"
Cohesion: 1.0
Nodes (1): Latest OHLC/LTP per symbol (live/tick mode).

### Community 33 - "Community 33"
Cohesion: 1.0
Nodes (1): Live expiry list (broker-specific format, e.g. indices).

### Community 34 - "Community 34"
Cohesion: 1.0
Nodes (1): Connect and start receiving data (e.g. spawn background thread).

### Community 35 - "Community 35"
Cohesion: 1.0
Nodes (1): Disconnect and stop the feed.

### Community 36 - "Community 36"
Cohesion: 1.0
Nodes (1): Return True if the feed is connected and receiving.

### Community 37 - "Community 37"
Cohesion: 1.0
Nodes (0): 

### Community 38 - "Community 38"
Cohesion: 1.0
Nodes (0): 

### Community 39 - "Community 39"
Cohesion: 1.0
Nodes (1): Normalize tag/action filter to a list of upper-case strings; None => no filter.

### Community 40 - "Community 40"
Cohesion: 1.0
Nodes (0): 

### Community 41 - "Community 41"
Cohesion: 1.0
Nodes (0): 

### Community 42 - "Community 42"
Cohesion: 1.0
Nodes (0): 

### Community 43 - "Community 43"
Cohesion: 1.0
Nodes (0): 

### Community 44 - "Community 44"
Cohesion: 1.0
Nodes (0): 

### Community 45 - "Community 45"
Cohesion: 1.0
Nodes (1): Single-bar RSI approximation (no pandas). Returns None if insufficient data.

### Community 46 - "Community 46"
Cohesion: 1.0
Nodes (0): 

### Community 47 - "Community 47"
Cohesion: 1.0
Nodes (1): Select last expiry of target month/year.

### Community 48 - "Community 48"
Cohesion: 1.0
Nodes (1): Dhan / Tradehull monthly option chain index for backtest (``expiry_code`` is int

### Community 49 - "Community 49"
Cohesion: 1.0
Nodes (1): Map DHAN ``expiry_code`` (0 = front monthly, 1 = next monthly) to a calendar exp

### Community 50 - "Community 50"
Cohesion: 1.0
Nodes (1): Inverse of ``dhan_expiry_index_to_date``: map a calendar expiry to DHAN ``expiry

### Community 51 - "Community 51"
Cohesion: 1.0
Nodes (1): Normalize values from ``params['expiry_code']`` / ``ctx.selected_expiry``: DHAN

### Community 52 - "Community 52"
Cohesion: 1.0
Nodes (1): Quarterly expiry label (future use).

### Community 53 - "Community 53"
Cohesion: 1.0
Nodes (1): Quarterly month selector (used by NSE & quarterly logic).

### Community 54 - "Community 54"
Cohesion: 1.0
Nodes (0): 

### Community 55 - "Community 55"
Cohesion: 1.0
Nodes (1): Same bar instant as ``bar_timestamp``, expressed in Asia/Kolkata (IST) for logs.

### Community 56 - "Community 56"
Cohesion: 1.0
Nodes (1): Background thread: if connected but no application traffic for stall_sec, close

### Community 57 - "Community 57"
Cohesion: 1.0
Nodes (1): Optional control-plane helper: hold references to Dhan market / order / depth cl

### Community 58 - "Community 58"
Cohesion: 1.0
Nodes (1): Sleep with jitter to avoid synchronized reconnect storms; return next backoff (c

### Community 59 - "Community 59"
Cohesion: 1.0
Nodes (1): Background thread: if connected but no application traffic for stall_sec, close

### Community 60 - "Community 60"
Cohesion: 1.0
Nodes (1): Optional control-plane helper: hold references to Dhan market / order / depth cl

## Knowledge Gaps
- **228 isolated node(s):** `Trade log and performance analytics.  - Trade log: trade_id, entry_time, exit_`, `Compute PnL for a single trade row.     BUY: (exit_price - entry_price) * qty`, `Load trade log from CSV into a DataFrame.      Args:         csv_path: Path t`, `Sharpe ratio from trade PnL: (mean return - risk_free_rate) / std(return).`, `Full performance summary from a trades DataFrame.      Trades must have column` (+223 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **Thin community `Community 23`** (2 nodes): `slippage.py`, `allowed_slippage()`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 24`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 25`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 26`** (1 nodes): `Place a single order. Returns dict with "status" and on success "order_id".`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 27`** (1 nodes): `Current positions (broker-specific format).`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 28`** (1 nodes): `Place order from OrderIntent or dict. Returns order_id or None.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 29`** (1 nodes): `Exit a position explicitly. Must internally call place_order().`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 30`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 31`** (1 nodes): `Historical intraday candles for backtest.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 32`** (1 nodes): `Latest OHLC/LTP per symbol (live/tick mode).`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 33`** (1 nodes): `Live expiry list (broker-specific format, e.g. indices).`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 34`** (1 nodes): `Connect and start receiving data (e.g. spawn background thread).`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 35`** (1 nodes): `Disconnect and stop the feed.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 36`** (1 nodes): `Return True if the feed is connected and receiving.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 37`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 38`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 39`** (1 nodes): `Normalize tag/action filter to a list of upper-case strings; None => no filter.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 40`** (1 nodes): `registry.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 41`** (1 nodes): `runtime_spec.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 42`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 43`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 44`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 45`** (1 nodes): `Single-bar RSI approximation (no pandas). Returns None if insufficient data.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 46`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 47`** (1 nodes): `Select last expiry of target month/year.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 48`** (1 nodes): `Dhan / Tradehull monthly option chain index for backtest (``expiry_code`` is int`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 49`** (1 nodes): `Map DHAN ``expiry_code`` (0 = front monthly, 1 = next monthly) to a calendar exp`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 50`** (1 nodes): `Inverse of ``dhan_expiry_index_to_date``: map a calendar expiry to DHAN ``expiry`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 51`** (1 nodes): `Normalize values from ``params['expiry_code']`` / ``ctx.selected_expiry``: DHAN`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 52`** (1 nodes): `Quarterly expiry label (future use).`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 53`** (1 nodes): `Quarterly month selector (used by NSE & quarterly logic).`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 54`** (1 nodes): `Expired options data.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 55`** (1 nodes): `Same bar instant as ``bar_timestamp``, expressed in Asia/Kolkata (IST) for logs.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 56`** (1 nodes): `Background thread: if connected but no application traffic for stall_sec, close`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 57`** (1 nodes): `Optional control-plane helper: hold references to Dhan market / order / depth cl`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 58`** (1 nodes): `Sleep with jitter to avoid synchronized reconnect storms; return next backoff (c`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 59`** (1 nodes): `Background thread: if connected but no application traffic for stall_sec, close`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 60`** (1 nodes): `Optional control-plane helper: hold references to Dhan market / order / depth cl`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `RunMode` connect `Community 2` to `Community 0`, `Community 1`, `Community 6`, `Community 7`, `Community 9`, `Community 11`?**
  _High betweenness centrality (0.095) - this node is a cross-community bridge._
- **Why does `create_live_engine()` connect `Community 0` to `Community 1`, `Community 3`, `Community 4`, `Community 5`, `Community 6`, `Community 7`, `Community 8`, `Community 9`, `Community 10`, `Community 11`, `Community 13`?**
  _High betweenness centrality (0.061) - this node is a cross-community bridge._
- **Why does `IndiaMktMixins` connect `Community 2` to `Community 1`, `Community 13`, `Community 6`?**
  _High betweenness centrality (0.042) - this node is a cross-community bridge._
- **Are the 218 inferred relationships involving `str` (e.g. with `.place_bracket_stop_loss()` and `.set_leverage_for_symbols()`) actually correct?**
  _`str` has 218 INFERRED edges - model-reasoned connections that need verification._
- **Are the 120 inferred relationships involving `RunMode` (e.g. with `OptionChainService` and `api: "NSE" or "DHAN"; ctx: StrategyContext; params: option chain params.`) actually correct?**
  _`RunMode` has 120 INFERRED edges - model-reasoned connections that need verification._
- **Are the 54 inferred relationships involving `IndiaMktMixins` (e.g. with `RunMode` and `ExpiryResolver`) actually correct?**
  _`IndiaMktMixins` has 54 INFERRED edges - model-reasoned connections that need verification._
- **Are the 24 inferred relationships involving `Tradehull` (e.g. with `DhanSource` and `Dhan data and order execution via in-project Tradehull library. All data feedin`) actually correct?**
  _`Tradehull` has 24 INFERRED edges - model-reasoned connections that need verification._