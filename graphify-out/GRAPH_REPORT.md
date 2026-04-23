# Graph Report - C:\Users\eshwa\Desktop\Algo  (2026-04-23)

## Corpus Check
- 122 files · ~115,963 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 2065 nodes · 5233 edges · 58 communities detected
- Extraction: 50% EXTRACTED · 50% INFERRED · 0% AMBIGUOUS · INFERRED: 2622 edges (avg confidence: 0.63)
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

## God Nodes (most connected - your core abstractions)
1. `RunMode` - 161 edges
2. `IntentStatus` - 101 edges
3. `IndiaMktMixins` - 84 edges
4. `Tradehull` - 75 edges
5. `LiveEngine` - 74 edges
6. `ExpiryResolver` - 74 edges
7. `LiveEngineHelpersMixin` - 72 edges
8. `DeltaSource` - 68 edges
9. `BaseEngine` - 64 edges
10. `AccountRouter` - 58 edges

## Surprising Connections (you probably didn't know these)
- `BaseBroker` --uses--> `Order placement via Delta Exchange. Uses DeltaBrokerApi (DeltaSource / delta_res`  [INFERRED]
  C:\Users\eshwa\Desktop\Algo\core\broker\base.py → C:\Users\eshwa\Desktop\Algo\core\broker\internal\delta\broker.py
- `BaseBroker` --uses--> `Resolve fill by broker order_id when fill API does not return client_order_id.`  [INFERRED]
  C:\Users\eshwa\Desktop\Algo\core\broker\base.py → C:\Users\eshwa\Desktop\Algo\core\broker\internal\delta\broker.py
- `BaseBroker` --uses--> `Return recent fills from /v2/fills for trade-led OMS sync. Positions are updated`  [INFERRED]
  C:\Users\eshwa\Desktop\Algo\core\broker\base.py → C:\Users\eshwa\Desktop\Algo\core\broker\internal\delta\broker.py
- `Thin wrapper around DhanOrderUpdateClient for LiveEngine wiring.` --uses--> `DhanOrderUpdateClient`  [INFERRED]
  C:\Users\eshwa\Desktop\Algo\core\data\feeds\dhan_order_update_feed.py → C:\Users\eshwa\Desktop\Algo\core\library\dhan_order_update_ws.py
- `Mixin for LiveEngine: pricing from depth, tick/lot validation, spread check,` --uses--> `SessionManager`  [INFERRED]
  C:\Users\eshwa\Desktop\Algo\core\engine\live_engine_common.py → C:\Users\eshwa\Desktop\Algo\core\utils\session\session_manager.py

## Communities

### Community 0 - "Community 0"
Cohesion: 0.02
Nodes (109): BaseStrategy, Optional: broker-driven close (liquidation, orphan fill, etc.). Override to sync, BaseStrategy, DeltaMktMixins, _append_live_strike_scan_rows(), delta_option_trading_symbol(), _delta_source_from_ctx(), _delta_underlying_prefix() (+101 more)

### Community 1 - "Community 1"
Cohesion: 0.02
Nodes (78): Abstract base for real-time market/account feeds (WebSocket).  Implementations:, Interface for a real-time feed (WebSocket) that can supply:     - Ticker / LTP p, Last ticker/LTP for symbol. Keys may include: close, mark_price, symbol, etc., Last closed (or latest) candle for symbol.         resolution: e.g. "1m", "5m",, Open/pending orders for symbol (if private feed supported)., Current positions by symbol (if private feed supported)., Optional: set engine-owned queue for tick streaming. When set, feed pushes, RealtimeFeed (+70 more)

### Community 2 - "Community 2"
Cohesion: 0.03
Nodes (92): BacktestEngine, BaseBroker, DeltaBroker, DhanBroker, Order placement via Delta Exchange. Uses DeltaBrokerApi (DeltaSource / delta_res, SimulatedBroker, CandleAggregator, Lock-free candle engine. Ticks update only 1m current; when 1m bucket changes, (+84 more)

### Community 3 - "Community 3"
Cohesion: 0.03
Nodes (52): BaseEngine, Return the last CLOSED candle only. Never returns forming candle; no repainting., Return up to max_bars last closed candles for symbol/resolution (newest last)., Symbols that have at least some state (for health checks)., _resolution_to_seconds(), _bar_timestamp_to_ist_iso(), EngineLogger, Structured JSON logging per engine. One file per engine: logs/{engine_id}.log. (+44 more)

### Community 4 - "Community 4"
Cohesion: 0.02
Nodes (101): Remove resting MAIN_SL when the main position exits via MAIN_EXIT (normal exit)., For short options, SL triggers when option premium (LTP) >= trigger (stop on pre, Paper: no open orders (instant fill). Same interface as live so order-state veri, Paper: fills already applied in place_order via process_fill. Same interface as, Paper: orders are filled immediately, so never in open list. Same interface as l, Paper: fill already applied in place_order. Same interface as live for missing-o, Paper: same as get_fill_for_client_order_id. Same interface as live., Enum (+93 more)

### Community 5 - "Community 5"
Cohesion: 0.03
Nodes (101): ABC, AccountRouter, Deterministic, side-effect-free mapping from intent -> account ids., BaseInstrumentStore, BaseEngine, IBrokerApi, Instrument, Shared instrument model and abstract store interface. Broker-specific logic liv (+93 more)

### Community 6 - "Community 6"
Cohesion: 0.03
Nodes (66): AccountRoutingConfig, all_accounts(), _dedupe_keep_order(), _order_intent_to_payload(), Check available balance and required/SPAN margin before placing order., Convert OrderIntent to dict for Dhan payload., Resolve fill by broker order_id when fill API does not return client_order_id., Return recent fills from /v2/fills for trade-led OMS sync. Positions are updated (+58 more)

### Community 7 - "Community 7"
Cohesion: 0.03
Nodes (62): DeltaBrokerApi, _ensure_list_str(), Order history via order_history (v2/orders/history) for resolving fill status wh, Fills via fills() (v2/fills) for order fill status., Resolve symbol to Delta product_id (e.g. BTCUSD -> id)., Edit orders in batch (e.g. update limit_price). Each order: { 'id': order_id, 'l, Set leverage for a Delta product (by product_id)., Set leverage for each symbol in the list. Resolves symbol -> product_id and call (+54 more)

### Community 8 - "Community 8"
Cohesion: 0.02
Nodes (73): cache_key_delta_intraday(), _drop_flat_candles(), load_df(), File cache for Delta Exchange historical intraday data. Uses data_cache/delta_h, Drop rows where open, high, low, close are all equal (no-trade bars)., Load a DataFrame from Delta cache. Returns None if missing or invalid., Save a DataFrame to Delta cache. Flat candles (o==h==l==c) are not stored., Key for Delta intraday cache: symbol + timeframe. Dates not in key. (+65 more)

### Community 9 - "Community 9"
Cohesion: 0.02
Nodes (47): DeltaWebSocketFeed, Delta Exchange WebSocket feed implementing RealtimeFeed.  Subscribes to v2/tic, Set event-driven callback for private user-trade events., Subscribe to ``l2_orderbook`` for ``symbol`` if not already covered., Raw L2 order book for symbol (bids/asks). Used for best bid/ask., Best bid price for symbol from L2 order book. For Delta limit BUY at best bid., Real-time feed using Delta Exchange WebSocket.     Subscribes to ticker and can, Best ask price for symbol from L2 order book. For Delta limit SELL at best ask. (+39 more)

### Community 10 - "Community 10"
Cohesion: 0.03
Nodes (70): _parse_nse_equity_l(), Equity universe service: loads NSE equity list from EQUITY_L (daily sync). Sour, Load from EQUITY_L_latest.csv (in cache_dir, e.g. Dependencies/equity_universe);, Return list of all equity symbols., Days since listing for symbol. None if unknown or not in universe.         Pure, Re-download if needed and reload from EQUITY_L_latest.csv (in cache_dir)., Return { symbol: EquityMeta } for symbols that exist in universe., Optional: schedule refresh (e.g. hour=20 after market close).         Call from (+62 more)

### Community 11 - "Community 11"
Cohesion: 0.04
Nodes (35): DhanBrokerApi, Dhan broker API: order placement and position/order lookup via Dhan., Fills from order list (filled/TRADED orders) for trade-led OMS., IBrokerApi implementation for Dhan. Order placement + positions + order list., BaseBroker, Optional idempotency hook. LIVE brokers may override., Optional: before placing an order, check available balance vs required/SPAN marg, Abstract broker contract for order placement and position/exit.     Engines and (+27 more)

### Community 12 - "Community 12"
Cohesion: 0.07
Nodes (38): _sl_orders_log_path(), atm_label_from_spot_strike(), default_expired_option_chain_root(), leg_csv_path(), load_expired_option_chain_from_files(), _normalize_expiry_str(), _option_right_filename(), Load Dhan expired option OHLC from locally downloaded CSVs (same layout as ``dh (+30 more)

### Community 13 - "Community 13"
Cohesion: 0.05
Nodes (17): IDataProvider, Contract for market data used by engines and order management.     Implementati, NSE expiry dates for a symbol/year. Optional for non-NSE providers., Live option chain (e.g. Dhan format)., Expired option data for backtest (e.g. Dhan)., DeltaDataProvider, Delta Exchange implementation of the data layer. Delegates to DeltaSource for m, Data layer for Delta Exchange: ticker/LTP, products, expiries. No orders. (+9 more)

### Community 14 - "Community 14"
Cohesion: 0.08
Nodes (11): BaseAdapter, StrategyContext without calling ``on_candle`` (for fill-time hooks)., SimulatedBroker: fire resting MAIN_SL when option LTP crosses trigger (backtest/, BaseAdapter, DataRouter, DhanAdapter, NSEAdapter, OptionChainService (+3 more)

### Community 15 - "Community 15"
Cohesion: 0.08
Nodes (25): _bucket_ts(), _candle_to_dict(), Prop-grade Candle Aggregator: tick → 1m only; higher timeframes from closed 1m o, Aggregate closed 1m into higher TFs; close only when bucket boundary aligns., Integer bucket boundary. ts_sec in Unix seconds; tf_seconds e.g. 60, 300., Process one tick. O(1). Updates only 1m current; closes 1m and propagates when b, _is_delta_ticker_message(), Delta Exchange WebSocket client.  Supports: - Public channels: v2/ticker, l2_ (+17 more)

### Community 16 - "Community 16"
Cohesion: 0.31
Nodes (4): EquityInstrument, FutureInstrument, Instrument, OptionInstrument

### Community 17 - "Community 17"
Cohesion: 0.4
Nodes (2): generate_quarterly_expiries(), last_thursday()

### Community 18 - "Community 18"
Cohesion: 0.4
Nodes (4): generate_monthly_expiries(), last_thursday(), Jan 2025 expiry -> 1 Dec 2024; Feb 2025 expiry -> 1 Jan 2025; etc., two_month_window_start_for_expiry()

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
Nodes (0): 

### Community 24 - "Community 24"
Cohesion: 1.0
Nodes (1): Place a single order. Returns dict with "status" and on success "order_id".

### Community 25 - "Community 25"
Cohesion: 1.0
Nodes (1): Current positions (broker-specific format).

### Community 26 - "Community 26"
Cohesion: 1.0
Nodes (1): Place order from OrderIntent or dict. Returns order_id or None.

### Community 27 - "Community 27"
Cohesion: 1.0
Nodes (1): Exit a position explicitly. Must internally call place_order().

### Community 28 - "Community 28"
Cohesion: 1.0
Nodes (0): 

### Community 29 - "Community 29"
Cohesion: 1.0
Nodes (1): Historical intraday candles for backtest.

### Community 30 - "Community 30"
Cohesion: 1.0
Nodes (1): Latest OHLC/LTP per symbol (live/tick mode).

### Community 31 - "Community 31"
Cohesion: 1.0
Nodes (1): Live expiry list (broker-specific format, e.g. indices).

### Community 32 - "Community 32"
Cohesion: 1.0
Nodes (1): Connect and start receiving data (e.g. spawn background thread).

### Community 33 - "Community 33"
Cohesion: 1.0
Nodes (1): Disconnect and stop the feed.

### Community 34 - "Community 34"
Cohesion: 1.0
Nodes (1): Return True if the feed is connected and receiving.

### Community 35 - "Community 35"
Cohesion: 1.0
Nodes (0): 

### Community 36 - "Community 36"
Cohesion: 1.0
Nodes (0): 

### Community 37 - "Community 37"
Cohesion: 1.0
Nodes (1): Normalize tag/action filter to a list of upper-case strings; None => no filter.

### Community 38 - "Community 38"
Cohesion: 1.0
Nodes (0): 

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
Nodes (1): Single-bar RSI approximation (no pandas). Returns None if insufficient data.

### Community 44 - "Community 44"
Cohesion: 1.0
Nodes (0): 

### Community 45 - "Community 45"
Cohesion: 1.0
Nodes (1): Select last expiry of target month/year.

### Community 46 - "Community 46"
Cohesion: 1.0
Nodes (1): Dhan / Tradehull monthly option chain index for backtest (``expiry_code`` is int

### Community 47 - "Community 47"
Cohesion: 1.0
Nodes (1): Map DHAN ``expiry_code`` (0 = front monthly, 1 = next monthly) to a calendar exp

### Community 48 - "Community 48"
Cohesion: 1.0
Nodes (1): Inverse of ``dhan_expiry_index_to_date``: map a calendar expiry to DHAN ``expiry

### Community 49 - "Community 49"
Cohesion: 1.0
Nodes (1): Normalize values from ``params['expiry_code']`` / ``ctx.selected_expiry``: DHAN

### Community 50 - "Community 50"
Cohesion: 1.0
Nodes (1): Quarterly expiry label (future use).

### Community 51 - "Community 51"
Cohesion: 1.0
Nodes (1): Quarterly month selector (used by NSE & quarterly logic).

### Community 52 - "Community 52"
Cohesion: 1.0
Nodes (0): 

### Community 53 - "Community 53"
Cohesion: 1.0
Nodes (1): Same bar instant as ``bar_timestamp``, expressed in Asia/Kolkata (IST) for logs.

### Community 54 - "Community 54"
Cohesion: 1.0
Nodes (1): Update intent status and optionally broker_order_id and order_state.         or

### Community 55 - "Community 55"
Cohesion: 1.0
Nodes (1): Normalize tag/action filter to a list of upper-case strings; None => no filter.

### Community 56 - "Community 56"
Cohesion: 1.0
Nodes (1): True if any in-flight intent matches strategy + structure (and optional tag/acti

### Community 57 - "Community 57"
Cohesion: 1.0
Nodes (1): Return [(intent_id, order_state_str), ...] for intents that have order_state set

## Knowledge Gaps
- **278 isolated node(s):** `Trade log and performance analytics.  - Trade log: trade_id, entry_time, exit_`, `Compute PnL for a single trade row.     BUY: (exit_price - entry_price) * qty`, `Load trade log from CSV into a DataFrame.      Args:         csv_path: Path t`, `Sharpe ratio from trade PnL: (mean return - risk_free_rate) / std(return).`, `Full performance summary from a trades DataFrame.      Trades must have column` (+273 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **Thin community `Community 20`** (2 nodes): `slippage.py`, `allowed_slippage()`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 21`** (1 nodes): `Dhan_codebase usage.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 22`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 23`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 24`** (1 nodes): `Place a single order. Returns dict with "status" and on success "order_id".`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 25`** (1 nodes): `Current positions (broker-specific format).`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 26`** (1 nodes): `Place order from OrderIntent or dict. Returns order_id or None.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 27`** (1 nodes): `Exit a position explicitly. Must internally call place_order().`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 28`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 29`** (1 nodes): `Historical intraday candles for backtest.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 30`** (1 nodes): `Latest OHLC/LTP per symbol (live/tick mode).`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 31`** (1 nodes): `Live expiry list (broker-specific format, e.g. indices).`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 32`** (1 nodes): `Connect and start receiving data (e.g. spawn background thread).`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 33`** (1 nodes): `Disconnect and stop the feed.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 34`** (1 nodes): `Return True if the feed is connected and receiving.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 35`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 36`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 37`** (1 nodes): `Normalize tag/action filter to a list of upper-case strings; None => no filter.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 38`** (1 nodes): `registry.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 39`** (1 nodes): `runtime_spec.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 40`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 41`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 42`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 43`** (1 nodes): `Single-bar RSI approximation (no pandas). Returns None if insufficient data.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 44`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 45`** (1 nodes): `Select last expiry of target month/year.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 46`** (1 nodes): `Dhan / Tradehull monthly option chain index for backtest (``expiry_code`` is int`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 47`** (1 nodes): `Map DHAN ``expiry_code`` (0 = front monthly, 1 = next monthly) to a calendar exp`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 48`** (1 nodes): `Inverse of ``dhan_expiry_index_to_date``: map a calendar expiry to DHAN ``expiry`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 49`** (1 nodes): `Normalize values from ``params['expiry_code']`` / ``ctx.selected_expiry``: DHAN`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 50`** (1 nodes): `Quarterly expiry label (future use).`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 51`** (1 nodes): `Quarterly month selector (used by NSE & quarterly logic).`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 52`** (1 nodes): `Expired options data.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 53`** (1 nodes): `Same bar instant as ``bar_timestamp``, expressed in Asia/Kolkata (IST) for logs.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 54`** (1 nodes): `Update intent status and optionally broker_order_id and order_state.         or`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 55`** (1 nodes): `Normalize tag/action filter to a list of upper-case strings; None => no filter.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 56`** (1 nodes): `True if any in-flight intent matches strategy + structure (and optional tag/acti`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 57`** (1 nodes): `Return [(intent_id, order_state_str), ...] for intents that have order_state set`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `RunMode` connect `Community 5` to `Community 0`, `Community 2`, `Community 3`, `Community 4`, `Community 6`, `Community 14`?**
  _High betweenness centrality (0.138) - this node is a cross-community bridge._
- **Why does `IntentStatus` connect `Community 4` to `Community 0`, `Community 2`, `Community 3`, `Community 6`, `Community 11`?**
  _High betweenness centrality (0.082) - this node is a cross-community bridge._
- **Why does `create_live_engine()` connect `Community 2` to `Community 1`, `Community 3`, `Community 5`, `Community 6`, `Community 7`, `Community 8`, `Community 9`, `Community 11`, `Community 13`?**
  _High betweenness centrality (0.077) - this node is a cross-community bridge._
- **Are the 209 inferred relationships involving `str` (e.g. with `.place_bracket_stop_loss()` and `.set_leverage_for_symbols()`) actually correct?**
  _`str` has 209 INFERRED edges - model-reasoned connections that need verification._
- **Are the 158 inferred relationships involving `RunMode` (e.g. with `OptionChainService` and `api: "NSE" or "DHAN"; ctx: StrategyContext; params: option chain params.`) actually correct?**
  _`RunMode` has 158 INFERRED edges - model-reasoned connections that need verification._
- **Are the 97 inferred relationships involving `IntentStatus` (e.g. with `SimulatedBroker` and `Simulated broker for both PAPER and BACKTEST. No real exchange; instant fill. PA`) actually correct?**
  _`IntentStatus` has 97 INFERRED edges - model-reasoned connections that need verification._
- **Are the 54 inferred relationships involving `IndiaMktMixins` (e.g. with `RunMode` and `ExpiryResolver`) actually correct?**
  _`IndiaMktMixins` has 54 INFERRED edges - model-reasoned connections that need verification._