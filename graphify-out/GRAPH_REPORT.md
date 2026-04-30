# Graph Report - C:\Users\eshwa\Desktop\Algo clone-2  (2026-04-30)

## Corpus Check
- 121 files · ~137,364 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 2064 nodes · 5422 edges · 68 communities detected
- Extraction: 50% EXTRACTED · 50% INFERRED · 0% AMBIGUOUS · INFERRED: 2722 edges (avg confidence: 0.64)
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
- [[_COMMUNITY_Community 61|Community 61]]
- [[_COMMUNITY_Community 62|Community 62]]
- [[_COMMUNITY_Community 63|Community 63]]
- [[_COMMUNITY_Community 64|Community 64]]
- [[_COMMUNITY_Community 65|Community 65]]
- [[_COMMUNITY_Community 66|Community 66]]
- [[_COMMUNITY_Community 67|Community 67]]

## God Nodes (most connected - your core abstractions)
1. `RunMode` - 140 edges
2. `IndiaMktMixins` - 84 edges
3. `LiveEngine` - 81 edges
4. `Tradehull` - 75 edges
5. `ExpiryResolver` - 74 edges
6. `DeltaSource` - 70 edges
7. `BaseStrategy` - 58 edges
8. `DhanSource` - 57 edges
9. `DeltaRestClient` - 57 edges
10. `SessionManager` - 56 edges

## Surprising Connections (you probably didn't know these)
- `BaseBroker` --uses--> `Order placement via Delta Exchange. Uses DeltaBrokerApi (DeltaSource / delta_res`  [INFERRED]
  C:\Users\eshwa\Desktop\Algo clone-2\core\broker\base.py → C:\Users\eshwa\Desktop\Algo clone-2\core\broker\internal\delta\broker.py
- `Thin wrapper around DhanOrderUpdateClient for LiveEngine wiring.` --uses--> `DhanOrderUpdateClient`  [INFERRED]
  C:\Users\eshwa\Desktop\Algo clone-2\core\data\feeds\dhan_order_update_feed.py → C:\Users\eshwa\Desktop\Algo clone-2\core\library\dhan_order_update_ws.py
- `Shared helpers and mixin for LiveEngine: pricing, depth, validation, candle chec` --uses--> `SessionManager`  [INFERRED]
  C:\Users\eshwa\Desktop\Algo clone-2\core\engine\live_engine_common.py → C:\Users\eshwa\Desktop\Algo clone-2\core\utils\session\session_manager.py
- `Parse 'HH:MM' to (hour, minute).` --uses--> `SessionManager`  [INFERRED]
  C:\Users\eshwa\Desktop\Algo clone-2\core\engine\live_engine_common.py → C:\Users\eshwa\Desktop\Algo clone-2\core\utils\session\session_manager.py
- `True if now (UTC) falls within any (start, end) window. Times in 'HH:MM' UTC.` --uses--> `SessionManager`  [INFERRED]
  C:\Users\eshwa\Desktop\Algo clone-2\core\engine\live_engine_common.py → C:\Users\eshwa\Desktop\Algo clone-2\core\utils\session\session_manager.py

## Communities

### Community 0 - "Community 0"
Cohesion: 0.02
Nodes (115): BaseStrategy, StrategyContext without calling ``on_candle`` (for fill-time hooks)., SimulatedBroker: fire resting MAIN_SL when option LTP crosses trigger (backtest/, Optional: broker-driven close (liquidation, orphan fill, etc.). Override to sync, BaseStrategy, DeltaMktMixins, _append_live_strike_scan_rows(), delta_option_trading_symbol() (+107 more)

### Community 1 - "Community 1"
Cohesion: 0.02
Nodes (113): AccountRoutingConfig, all_accounts(), _dedupe_keep_order(), _order_intent_to_payload(), Convert OrderIntent to dict for Dhan payload., _sl_orders_log_path(), _bucket_ts(), _candle_to_dict() (+105 more)

### Community 2 - "Community 2"
Cohesion: 0.01
Nodes (121): Abstract base for real-time market/account feeds (WebSocket).  Implementations, Interface for a real-time feed (WebSocket) that can supply:     - Ticker / LTP, Last ticker/LTP for symbol. Keys may include: close, mark_price, symbol, etc., Last closed (or latest) candle for symbol.         resolution: e.g. "1m", "5m",, Open/pending orders for symbol (if private feed supported)., Current positions by symbol (if private feed supported)., Optional: set engine-owned queue for tick streaming. When set, feed pushes, RealtimeFeed (+113 more)

### Community 3 - "Community 3"
Cohesion: 0.03
Nodes (103): AccountRouter, Deterministic, side-effect-free mapping from intent -> account ids., BacktestEngine, BaseEngine, BaseBroker, BaseEngine, DeltaBroker, DhanBroker (+95 more)

### Community 4 - "Community 4"
Cohesion: 0.02
Nodes (86): cache_key_delta_intraday(), Key for Delta intraday cache: symbol + timeframe. Dates not in key., raise_for_status(), Raises :class:`HTTPError`, if one occurred., cache_key_futures(), cache_key_intraday(), load_df(), File cache for Dhan historical intraday and futures data. Uses data_cache/dhan_ (+78 more)

### Community 5 - "Community 5"
Cohesion: 0.03
Nodes (56): DeltaBrokerApi, _ensure_list_str(), Order history via order_history (v2/orders/history) for resolving fill status wh, Fills via fills() (v2/fills) for order fill status., Resolve symbol to Delta product_id (e.g. BTCUSD -> id)., Edit orders in batch (e.g. update limit_price). Each order: { 'id': order_id, 'l, Set leverage for a Delta product (by product_id)., Set leverage for each symbol in the list. Resolves symbol -> product_id and call (+48 more)

### Community 6 - "Community 6"
Cohesion: 0.03
Nodes (47): DeltaWebSocketFeed, Delta Exchange WebSocket feed implementing RealtimeFeed.  Subscribes to v2/tic, Set event-driven callback for private user-trade events., Subscribe to ``l2_orderbook`` for ``symbol`` if not already covered., Raw L2 order book for symbol (bids/asks). Used for best bid/ask., Best bid price for symbol from L2 order book. For Delta limit BUY at best bid., Real-time feed using Delta Exchange WebSocket.     Subscribes to ticker and can, Best ask price for symbol from L2 order book. For Delta limit SELL at best ask. (+39 more)

### Community 7 - "Community 7"
Cohesion: 0.04
Nodes (64): ABC, BaseInstrumentStore, IBrokerApi, Instrument, Shared instrument model and abstract store interface. Broker-specific logic liv, Contract for order placement and position/order lookup at the exchange.     Imp, Single tradable contract (option/future/equity). Used by order intents and posit, List of orders for idempotency / status lookup. (+56 more)

### Community 8 - "Community 8"
Cohesion: 0.03
Nodes (52): DhanBrokerApi, Dhan broker API: order placement and position/order lookup via Dhan., Fills from order list (filled/TRADED orders) for trade-led OMS., IBrokerApi implementation for Dhan. Order placement + positions + order list., BaseBroker, Optional idempotency hook. LIVE brokers may override., Optional: before placing an order, check available balance vs required/SPAN marg, Abstract broker contract for order placement and position/exit.     Engines and (+44 more)

### Community 9 - "Community 9"
Cohesion: 0.05
Nodes (51): EquityUniverseService, _parse_nse_equity_l(), Equity universe service: loads NSE equity list from EQUITY_L (daily sync). Sour, Load from EQUITY_L_latest.csv (in cache_dir, e.g. Dependencies/equity_universe);, Return list of all equity symbols., Days since listing for symbol. None if unknown or not in universe.         Pure, Re-download if needed and reload from EQUITY_L_latest.csv (in cache_dir)., Return { symbol: EquityMeta } for symbols that exist in universe. (+43 more)

### Community 10 - "Community 10"
Cohesion: 0.05
Nodes (25): _bar_close_unix_from_bucket(), _bar_timestamp_to_ist_iso(), _coerce_to_unix_seconds(), EngineLogger, _is_missing(), Structured JSON logging per engine. One file per engine: logs/{engine_id}.log., Structured error event wrapper., Append one JSON line per closed candle to logs/{engine_id}_candles.log. (+17 more)

### Community 11 - "Community 11"
Cohesion: 0.04
Nodes (23): NeoAPI, Retrieves quotes for the given instrument tokens.          Args:, Cancels an order with the given `order_id` using the NEO API.          Args: o, Cancels a cover order with the given `order_id` using the NEO API.          Ar, Cancels a bracket order with the given `order_id` using the NEO API., Retrieves a list of orders in the order book using the NEO API.          Raise, Retrieves the order history for a given order ID using the NEO API.          A, Retrieves a filtered list of trades using the NEO API.          Args: (+15 more)

### Community 12 - "Community 12"
Cohesion: 0.07
Nodes (40): atm_label_from_spot_strike(), default_expired_option_chain_root(), leg_csv_path(), load_expired_option_chain_from_files(), _normalize_expiry_str(), _option_right_filename(), Load Dhan expired option OHLC from locally downloaded CSVs (same layout as ``da, Map numeric strikes (or precomputed ``ATM`` / ``ATM±n`` folder names) to folder (+32 more)

### Community 13 - "Community 13"
Cohesion: 0.05
Nodes (17): IDataProvider, Contract for market data used by engines and order management.     Implementati, NSE expiry dates for a symbol/year. Optional for non-NSE providers., Live option chain (e.g. Dhan format)., Expired option data for backtest (e.g. Dhan)., DeltaDataProvider, Delta Exchange implementation of the data layer. Delegates to DeltaSource for m, Data layer for Delta Exchange: ticker/LTP, products, expiries. No orders. (+9 more)

### Community 14 - "Community 14"
Cohesion: 0.14
Nodes (6): BaseAdapter, BaseAdapter, DataRouter, DhanAdapter, NSEAdapter, Safe access for selected_expiry.

### Community 15 - "Community 15"
Cohesion: 0.31
Nodes (4): EquityInstrument, FutureInstrument, Instrument, OptionInstrument

### Community 16 - "Community 16"
Cohesion: 0.29
Nodes (7): _drop_flat_candles(), load_df(), File cache for Delta Exchange historical intraday data. Uses data_cache/delta_h, Drop rows where open, high, low, close are all equal (no-trade bars)., Load a DataFrame from Delta cache. Returns None if missing or invalid., Save a DataFrame to Delta cache. Flat candles (o==h==l==c) are not stored., save_df()

### Community 17 - "Community 17"
Cohesion: 0.29
Nodes (3): _fill_clock_for_trade_log(), Position, Normalize bar/fill time for trade_log CSV (backtest = candle close instant, not

### Community 18 - "Community 18"
Cohesion: 0.5
Nodes (3): Dhan Postback (webhook) — optional third path for order lifecycle events.  Doc, Placeholder: implement HMAC/signature verification per Dhan postback documentati, verify_postback_signature()

### Community 19 - "Community 19"
Cohesion: 0.67
Nodes (1): EDIS (e-disclosure) — required for selling delivery (CNC) equity from demat.

### Community 20 - "Community 20"
Cohesion: 1.0
Nodes (0): 

### Community 21 - "Community 21"
Cohesion: 1.0
Nodes (0): 

### Community 22 - "Community 22"
Cohesion: 1.0
Nodes (0): 

### Community 23 - "Community 23"
Cohesion: 1.0
Nodes (1): Place a single order. Returns dict with "status" and on success "order_id".

### Community 24 - "Community 24"
Cohesion: 1.0
Nodes (1): Current positions (broker-specific format).

### Community 25 - "Community 25"
Cohesion: 1.0
Nodes (1): Place order from OrderIntent or dict. Returns order_id or None.

### Community 26 - "Community 26"
Cohesion: 1.0
Nodes (1): Exit a position explicitly. Must internally call place_order().

### Community 27 - "Community 27"
Cohesion: 1.0
Nodes (0): 

### Community 28 - "Community 28"
Cohesion: 1.0
Nodes (1): Historical intraday candles for backtest.

### Community 29 - "Community 29"
Cohesion: 1.0
Nodes (1): Latest OHLC/LTP per symbol (live/tick mode).

### Community 30 - "Community 30"
Cohesion: 1.0
Nodes (1): Live expiry list (broker-specific format, e.g. indices).

### Community 31 - "Community 31"
Cohesion: 1.0
Nodes (1): Connect and start receiving data (e.g. spawn background thread).

### Community 32 - "Community 32"
Cohesion: 1.0
Nodes (1): Disconnect and stop the feed.

### Community 33 - "Community 33"
Cohesion: 1.0
Nodes (1): Return True if the feed is connected and receiving.

### Community 34 - "Community 34"
Cohesion: 1.0
Nodes (0): 

### Community 35 - "Community 35"
Cohesion: 1.0
Nodes (1): Compute full RSI/prev_RSI columns for strategies that explicitly require RSI.

### Community 36 - "Community 36"
Cohesion: 1.0
Nodes (1): Return a stable signature only when strategy explicitly opts into         cross

### Community 37 - "Community 37"
Cohesion: 1.0
Nodes (0): 

### Community 38 - "Community 38"
Cohesion: 1.0
Nodes (1): Normalize tag/action filter to a list of upper-case strings; None => no filter.

### Community 39 - "Community 39"
Cohesion: 1.0
Nodes (0): 

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
Nodes (1): Single-bar RSI approximation (no pandas). Returns None if insufficient data.

### Community 45 - "Community 45"
Cohesion: 1.0
Nodes (0): 

### Community 46 - "Community 46"
Cohesion: 1.0
Nodes (1): Select last expiry of target month/year.

### Community 47 - "Community 47"
Cohesion: 1.0
Nodes (1): Dhan / Tradehull monthly option chain index for backtest (``expiry_code`` is int

### Community 48 - "Community 48"
Cohesion: 1.0
Nodes (1): Map DHAN ``expiry_code`` (0 = front monthly, 1 = next monthly) to a calendar exp

### Community 49 - "Community 49"
Cohesion: 1.0
Nodes (1): Inverse of ``dhan_expiry_index_to_date``: map a calendar expiry to DHAN ``expiry

### Community 50 - "Community 50"
Cohesion: 1.0
Nodes (1): Normalize values from ``params['expiry_code']`` / ``ctx.selected_expiry``: DHAN

### Community 51 - "Community 51"
Cohesion: 1.0
Nodes (1): Quarterly expiry label (future use).

### Community 52 - "Community 52"
Cohesion: 1.0
Nodes (1): Quarterly month selector (used by NSE & quarterly logic).

### Community 53 - "Community 53"
Cohesion: 1.0
Nodes (1): Normalize candle timestamp to UNIX seconds for arithmetic.

### Community 54 - "Community 54"
Cohesion: 1.0
Nodes (1): Bar close instant (UNIX): bucket start + timeframe length.         NSE cash IND

### Community 55 - "Community 55"
Cohesion: 1.0
Nodes (1): Bar instant as ISO in Asia/Kolkata (IST). Used for open/close UNIX conversion.

### Community 56 - "Community 56"
Cohesion: 1.0
Nodes (1): Process one tick. O(1). Updates only 1m current; closes 1m and propagates when b

### Community 57 - "Community 57"
Cohesion: 1.0
Nodes (1): Aggregate closed 1m into higher TFs; close only when bucket boundary aligns.

### Community 58 - "Community 58"
Cohesion: 1.0
Nodes (1): Return the last CLOSED candle only. Never returns forming candle; no repainting.

### Community 59 - "Community 59"
Cohesion: 1.0
Nodes (1): Return up to max_bars last closed candles for symbol/resolution (newest last).

### Community 60 - "Community 60"
Cohesion: 1.0
Nodes (1): Symbols that have at least some state (for health checks).

### Community 61 - "Community 61"
Cohesion: 1.0
Nodes (1): Compute full RSI/prev_RSI columns for strategies that explicitly require RSI.

### Community 62 - "Community 62"
Cohesion: 1.0
Nodes (1): Return a stable signature only when strategy explicitly opts into         cross

### Community 63 - "Community 63"
Cohesion: 1.0
Nodes (1): Compute full RSI/prev_RSI columns for strategies that explicitly require RSI.

### Community 64 - "Community 64"
Cohesion: 1.0
Nodes (1): Return a stable signature only when strategy explicitly opts into         cross

### Community 65 - "Community 65"
Cohesion: 1.0
Nodes (1): Shared indicator layer for live engine.      Maintains per-(symbol,timeframe)

### Community 66 - "Community 66"
Cohesion: 1.0
Nodes (1): Compute full RSI/prev_RSI columns for strategies that explicitly require RSI.

### Community 67 - "Community 67"
Cohesion: 1.0
Nodes (1): Return a stable signature only when strategy explicitly opts into         cross

## Knowledge Gaps
- **241 isolated node(s):** `Trade log and performance analytics.  - Trade log: trade_id, entry_time, exit_`, `Compute PnL for a single trade row.     BUY: (exit_price - entry_price) * qty`, `Load trade log from CSV into a DataFrame.      Args:         csv_path: Path t`, `Sharpe ratio from trade PnL: (mean return - risk_free_rate) / std(return).`, `Full performance summary from a trades DataFrame.      Trades must have column` (+236 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **Thin community `Community 20`** (2 nodes): `slippage.py`, `allowed_slippage()`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 21`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 22`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 23`** (1 nodes): `Place a single order. Returns dict with "status" and on success "order_id".`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 24`** (1 nodes): `Current positions (broker-specific format).`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 25`** (1 nodes): `Place order from OrderIntent or dict. Returns order_id or None.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 26`** (1 nodes): `Exit a position explicitly. Must internally call place_order().`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 27`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 28`** (1 nodes): `Historical intraday candles for backtest.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 29`** (1 nodes): `Latest OHLC/LTP per symbol (live/tick mode).`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 30`** (1 nodes): `Live expiry list (broker-specific format, e.g. indices).`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 31`** (1 nodes): `Connect and start receiving data (e.g. spawn background thread).`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 32`** (1 nodes): `Disconnect and stop the feed.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 33`** (1 nodes): `Return True if the feed is connected and receiving.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 34`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 35`** (1 nodes): `Compute full RSI/prev_RSI columns for strategies that explicitly require RSI.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 36`** (1 nodes): `Return a stable signature only when strategy explicitly opts into         cross`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 37`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 38`** (1 nodes): `Normalize tag/action filter to a list of upper-case strings; None => no filter.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 39`** (1 nodes): `registry.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 40`** (1 nodes): `runtime_spec.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 41`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 42`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 43`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 44`** (1 nodes): `Single-bar RSI approximation (no pandas). Returns None if insufficient data.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 45`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 46`** (1 nodes): `Select last expiry of target month/year.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 47`** (1 nodes): `Dhan / Tradehull monthly option chain index for backtest (``expiry_code`` is int`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 48`** (1 nodes): `Map DHAN ``expiry_code`` (0 = front monthly, 1 = next monthly) to a calendar exp`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 49`** (1 nodes): `Inverse of ``dhan_expiry_index_to_date``: map a calendar expiry to DHAN ``expiry`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 50`** (1 nodes): `Normalize values from ``params['expiry_code']`` / ``ctx.selected_expiry``: DHAN`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 51`** (1 nodes): `Quarterly expiry label (future use).`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 52`** (1 nodes): `Quarterly month selector (used by NSE & quarterly logic).`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 53`** (1 nodes): `Normalize candle timestamp to UNIX seconds for arithmetic.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 54`** (1 nodes): `Bar close instant (UNIX): bucket start + timeframe length.         NSE cash IND`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 55`** (1 nodes): `Bar instant as ISO in Asia/Kolkata (IST). Used for open/close UNIX conversion.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 56`** (1 nodes): `Process one tick. O(1). Updates only 1m current; closes 1m and propagates when b`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 57`** (1 nodes): `Aggregate closed 1m into higher TFs; close only when bucket boundary aligns.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 58`** (1 nodes): `Return the last CLOSED candle only. Never returns forming candle; no repainting.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 59`** (1 nodes): `Return up to max_bars last closed candles for symbol/resolution (newest last).`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 60`** (1 nodes): `Symbols that have at least some state (for health checks).`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 61`** (1 nodes): `Compute full RSI/prev_RSI columns for strategies that explicitly require RSI.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 62`** (1 nodes): `Return a stable signature only when strategy explicitly opts into         cross`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 63`** (1 nodes): `Compute full RSI/prev_RSI columns for strategies that explicitly require RSI.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 64`** (1 nodes): `Return a stable signature only when strategy explicitly opts into         cross`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 65`** (1 nodes): `Shared indicator layer for live engine.      Maintains per-(symbol,timeframe)`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 66`** (1 nodes): `Compute full RSI/prev_RSI columns for strategies that explicitly require RSI.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 67`** (1 nodes): `Return a stable signature only when strategy explicitly opts into         cross`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `RunMode` connect `Community 7` to `Community 0`, `Community 1`, `Community 2`, `Community 3`?**
  _High betweenness centrality (0.111) - this node is a cross-community bridge._
- **Why does `create_live_engine()` connect `Community 3` to `Community 1`, `Community 2`, `Community 4`, `Community 5`, `Community 6`, `Community 7`, `Community 8`, `Community 10`, `Community 13`?**
  _High betweenness centrality (0.062) - this node is a cross-community bridge._
- **Why does `DhanSource` connect `Community 4` to `Community 0`, `Community 1`, `Community 2`, `Community 3`, `Community 12`?**
  _High betweenness centrality (0.059) - this node is a cross-community bridge._
- **Are the 237 inferred relationships involving `str` (e.g. with `.place_bracket_stop_loss()` and `.set_leverage_for_symbols()`) actually correct?**
  _`str` has 237 INFERRED edges - model-reasoned connections that need verification._
- **Are the 137 inferred relationships involving `RunMode` (e.g. with `OptionChainService` and `api: "NSE" or "DHAN"; ctx: StrategyContext; params: option chain params.`) actually correct?**
  _`RunMode` has 137 INFERRED edges - model-reasoned connections that need verification._
- **Are the 54 inferred relationships involving `IndiaMktMixins` (e.g. with `RunMode` and `ExpiryResolver`) actually correct?**
  _`IndiaMktMixins` has 54 INFERRED edges - model-reasoned connections that need verification._
- **Are the 35 inferred relationships involving `LiveEngine` (e.g. with `EngineFactory` and `EngineFactory: build fully isolated single-venue engines.  One engine = one br`) actually correct?**
  _`LiveEngine` has 35 INFERRED edges - model-reasoned connections that need verification._