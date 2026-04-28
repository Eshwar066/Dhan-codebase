# Graph Report - C:\Users\eshwa\Desktop\Algo  (2026-04-29)

## Corpus Check
- 126 files · ~142,163 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 2305 nodes · 5985 edges · 96 communities detected
- Extraction: 47% EXTRACTED · 53% INFERRED · 0% AMBIGUOUS · INFERRED: 3201 edges (avg confidence: 0.62)
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
- [[_COMMUNITY_Community 68|Community 68]]
- [[_COMMUNITY_Community 69|Community 69]]
- [[_COMMUNITY_Community 70|Community 70]]
- [[_COMMUNITY_Community 71|Community 71]]
- [[_COMMUNITY_Community 72|Community 72]]
- [[_COMMUNITY_Community 73|Community 73]]
- [[_COMMUNITY_Community 74|Community 74]]
- [[_COMMUNITY_Community 75|Community 75]]
- [[_COMMUNITY_Community 76|Community 76]]
- [[_COMMUNITY_Community 77|Community 77]]
- [[_COMMUNITY_Community 78|Community 78]]
- [[_COMMUNITY_Community 79|Community 79]]
- [[_COMMUNITY_Community 80|Community 80]]
- [[_COMMUNITY_Community 81|Community 81]]
- [[_COMMUNITY_Community 82|Community 82]]
- [[_COMMUNITY_Community 83|Community 83]]
- [[_COMMUNITY_Community 84|Community 84]]
- [[_COMMUNITY_Community 85|Community 85]]
- [[_COMMUNITY_Community 86|Community 86]]
- [[_COMMUNITY_Community 87|Community 87]]
- [[_COMMUNITY_Community 88|Community 88]]
- [[_COMMUNITY_Community 89|Community 89]]
- [[_COMMUNITY_Community 90|Community 90]]
- [[_COMMUNITY_Community 91|Community 91]]
- [[_COMMUNITY_Community 92|Community 92]]
- [[_COMMUNITY_Community 93|Community 93]]
- [[_COMMUNITY_Community 94|Community 94]]
- [[_COMMUNITY_Community 95|Community 95]]

## God Nodes (most connected - your core abstractions)
1. `RunMode` - 216 edges
2. `IntentStatus` - 105 edges
3. `ExpiryResolver` - 102 edges
4. `LiveEngineHelpersMixin` - 95 edges
5. `IndiaMktMixins` - 93 edges
6. `BaseEngine` - 92 edges
7. `AccountRouter` - 86 edges
8. `SessionManager` - 82 edges
9. `LiveEngine` - 81 edges
10. `ExecutionEngine` - 77 edges

## Surprising Connections (you probably didn't know these)
- `BaseBroker` --uses--> `Order placement via Delta Exchange. Uses DeltaBrokerApi (DeltaSource / delta_res`  [INFERRED]
  C:\Users\eshwa\Desktop\Algo\core\broker\base.py → C:\Users\eshwa\Desktop\Algo\core\broker\internal\delta\broker.py
- `BaseBroker` --uses--> `Find order in live list; if not there, look up in /v2/orders/history and /v2/fil`  [INFERRED]
  C:\Users\eshwa\Desktop\Algo\core\broker\base.py → C:\Users\eshwa\Desktop\Algo\core\broker\internal\delta\broker.py
- `BaseBroker` --uses--> `Resolve order status from order history or fills when not in live list.`  [INFERRED]
  C:\Users\eshwa\Desktop\Algo\core\broker\base.py → C:\Users\eshwa\Desktop\Algo\core\broker\internal\delta\broker.py
- `BaseBroker` --uses--> `Resolve fill price and size from /v2/fills for a given client_order_id (intent_i`  [INFERRED]
  C:\Users\eshwa\Desktop\Algo\core\broker\base.py → C:\Users\eshwa\Desktop\Algo\core\broker\internal\delta\broker.py
- `BaseBroker` --uses--> `Resolve fill by broker order_id when fill API does not return client_order_id.`  [INFERRED]
  C:\Users\eshwa\Desktop\Algo\core\broker\base.py → C:\Users\eshwa\Desktop\Algo\core\broker\internal\delta\broker.py

## Communities

### Community 0 - "Community 0"
Cohesion: 0.01
Nodes (148): Abstract base for real-time market/account feeds (WebSocket).  Implementations:, Interface for a real-time feed (WebSocket) that can supply:     - Ticker / LTP p, Last ticker/LTP for symbol. Keys may include: close, mark_price, symbol, etc., Last closed (or latest) candle for symbol.         resolution: e.g. "1m", "5m",, Open/pending orders for symbol (if private feed supported)., Current positions by symbol (if private feed supported)., Optional: set engine-owned queue for tick streaming. When set, feed pushes, RealtimeFeed (+140 more)

### Community 1 - "Community 1"
Cohesion: 0.01
Nodes (136): _order_intent_to_payload(), Check available balance and required/SPAN margin before placing order., Convert OrderIntent to dict for Dhan payload., Recent fills from order list (TRADED/filled) for trade-led OMS sync., Resolve fill price/size for a given intent_id (tag) from filled orders., Resolve fill by broker order_id when fill/order list does not return tag., Find order in live list; if not there, look up in /v2/orders/history and /v2/fil, Resolve order status from order history or fills when not in live list. (+128 more)

### Community 2 - "Community 2"
Cohesion: 0.02
Nodes (144): BaseAdapter, BaseStrategy, StrategyContext without calling ``on_candle`` (for fill-time hooks)., SimulatedBroker: fire resting MAIN_SL when option LTP crosses trigger (backtest/, Optional: broker-driven close (liquidation, orphan fill, etc.). Override to sync, Uniquely identifies a tradable contract (netting, hedges, rollovers)., Resolve option contract to Instrument for order intent. Returns None if not foun, Resolve futures contract to Instrument. Returns None if not found. (+136 more)

### Community 3 - "Community 3"
Cohesion: 0.02
Nodes (135): BaseBroker, Optional idempotency hook. LIVE brokers may override., Optional: before placing an order, check available balance vs required/SPAN marg, Abstract broker contract for order placement and position/exit.     Engines and, Optional. LIVE brokers may override to reconcile broker truth., Return normalized { symbol: { qty, avg_price, segment, lot_size } } for reconcil, Return list of open (pending/active) orders for order-state consistency check., _delta_required_notional() (+127 more)

### Community 4 - "Community 4"
Cohesion: 0.03
Nodes (101): BacktestEngine, BaseBroker, BaseEngine, DeltaBroker, DhanBroker, Order placement via Dhan. Uses IBrokerApi (DhanBrokerApi)., Order placement via Delta Exchange. Uses DeltaBrokerApi (DeltaSource / delta_res, CandleAggregator (+93 more)

### Community 5 - "Community 5"
Cohesion: 0.03
Nodes (36): BaseStrategy, _is_delta_ticker_message(), Match Delta ``v2/ticker`` updates. Some builds use different ``type`` casing, DeltaMktMixins, delta_option_trading_symbol(), _delta_source_from_ctx(), ltp_from_strike_row_live(), Output:         NIFTY 30 MAR 25000 PUT         NIFTY 30 MAR 25000 CALL (+28 more)

### Community 6 - "Community 6"
Cohesion: 0.03
Nodes (66): DeltaBrokerApi, DhanBrokerApi, _ensure_list_str(), Dhan broker API: order placement and position/order lookup via Dhan., Order history via order_history (v2/orders/history) for resolving fill status wh, Fills via fills() (v2/fills) for order fill status., Resolve symbol to Delta product_id (e.g. BTCUSD -> id)., Edit orders in batch (e.g. update limit_price). Each order: { 'id': order_id, 'l (+58 more)

### Community 7 - "Community 7"
Cohesion: 0.02
Nodes (50): DeltaWebSocketFeed, Delta Exchange WebSocket feed implementing RealtimeFeed.  Subscribes to v2/tic, Set event-driven callback for private user-trade events., Subscribe to ``l2_orderbook`` for ``symbol`` if not already covered., Raw L2 order book for symbol (bids/asks). Used for best bid/ask., Best bid price for symbol from L2 order book. For Delta limit BUY at best bid., Real-time feed using Delta Exchange WebSocket.     Subscribes to ticker and can, Best ask price for symbol from L2 order book. For Delta limit SELL at best ask. (+42 more)

### Community 8 - "Community 8"
Cohesion: 0.07
Nodes (75): AccountRouter, AccountRoutingConfig, all_accounts(), _dedupe_keep_order(), Deterministic, side-effect-free mapping from intent -> account ids., BaseEngine, ExecutionEngine, OMS execution pipeline extracted from LiveEngine:     intent enqueue -> account (+67 more)

### Community 9 - "Community 9"
Cohesion: 0.03
Nodes (71): EquityUniverseService, _parse_nse_equity_l(), Equity universe service: loads NSE equity list from EQUITY_L (daily sync). Sour, Load from EQUITY_L_latest.csv (in cache_dir, e.g. Dependencies/equity_universe);, Return list of all equity symbols., Days since listing for symbol. None if unknown or not in universe.         Pure, Re-download if needed and reload from EQUITY_L_latest.csv (in cache_dir)., Return { symbol: EquityMeta } for symbols that exist in universe. (+63 more)

### Community 10 - "Community 10"
Cohesion: 0.04
Nodes (24): Symbols that have at least some state (for health checks)., Incremental fill payloads (see dhan_order_update_ws)., _bar_close_unix_from_bucket(), _bar_timestamp_to_ist_iso(), _coerce_to_unix_seconds(), EngineLogger, _is_missing(), Structured JSON logging per engine. One file per engine: logs/{engine_id}.log. (+16 more)

### Community 11 - "Community 11"
Cohesion: 0.06
Nodes (42): ABC, BaseInstrumentStore, IBrokerApi, Instrument, Shared instrument model and abstract store interface. Broker-specific logic liv, Contract for order placement and position/order lookup at the exchange.     Imp, Single tradable contract (option/future/equity). Used by order intents and posit, List of orders for idempotency / status lookup. (+34 more)

### Community 12 - "Community 12"
Cohesion: 0.05
Nodes (18): IDataProvider, Contract for market data used by engines and order management.     Implementati, NSE expiry dates for a symbol/year. Optional for non-NSE providers., Live option chain (e.g. Dhan format)., Expired option data for backtest (e.g. Dhan)., Return lot size for symbol when known; None otherwise. Override in broker implem, DeltaDataProvider, Delta Exchange implementation of the data layer. Delegates to DeltaSource for m (+10 more)

### Community 13 - "Community 13"
Cohesion: 0.07
Nodes (36): atm_label_from_spot_strike(), default_expired_option_chain_root(), leg_csv_path(), load_expired_option_chain_from_files(), _normalize_expiry_str(), _option_right_filename(), Load Dhan expired option OHLC from locally downloaded CSVs (same layout as ``da, Map numeric strikes (or precomputed ``ATM`` / ``ATM±n`` folder names) to folder (+28 more)

### Community 14 - "Community 14"
Cohesion: 0.1
Nodes (20): cache_key_delta_intraday(), _drop_flat_candles(), load_df(), File cache for Delta Exchange historical intraday data. Uses data_cache/delta_h, Drop rows where open, high, low, close are all equal (no-trade bars)., Load a DataFrame from Delta cache. Returns None if missing or invalid., Save a DataFrame to Delta cache. Flat candles (o==h==l==c) are not stored., Key for Delta intraday cache: symbol + timeframe. Dates not in key. (+12 more)

### Community 15 - "Community 15"
Cohesion: 0.13
Nodes (11): _bucket_ts(), _candle_to_dict(), Prop-grade Candle Aggregator: tick → 1m only; higher timeframes from closed 1m o, Process one tick. O(1). Updates only 1m current; closes 1m and propagates when b, Aggregate closed 1m into higher TFs; close only when bucket boundary aligns., Return the last CLOSED candle only. Never returns forming candle; no repainting., Return up to max_bars last closed candles for symbol/resolution (newest last)., Integer bucket boundary.      - Default: wall-clock epoch bucketing.     - Se (+3 more)

### Community 16 - "Community 16"
Cohesion: 0.4
Nodes (2): generate_quarterly_expiries(), last_thursday()

### Community 17 - "Community 17"
Cohesion: 0.4
Nodes (4): generate_monthly_expiries(), last_thursday(), Jan 2025 expiry -> 1 Dec 2024; Feb 2025 expiry -> 1 Jan 2025; etc., two_month_window_start_for_expiry()

### Community 18 - "Community 18"
Cohesion: 0.67
Nodes (1): EDIS (e-disclosure) — required for selling delivery (CNC) equity from demat.

### Community 19 - "Community 19"
Cohesion: 1.0
Nodes (0): 

### Community 20 - "Community 20"
Cohesion: 1.0
Nodes (0): 

### Community 21 - "Community 21"
Cohesion: 1.0
Nodes (0): 

### Community 22 - "Community 22"
Cohesion: 1.0
Nodes (1): Place a single order. Returns dict with "status" and on success "order_id".

### Community 23 - "Community 23"
Cohesion: 1.0
Nodes (1): Current positions (broker-specific format).

### Community 24 - "Community 24"
Cohesion: 1.0
Nodes (1): Place order from OrderIntent or dict. Returns order_id or None.

### Community 25 - "Community 25"
Cohesion: 1.0
Nodes (1): Exit a position explicitly. Must internally call place_order().

### Community 26 - "Community 26"
Cohesion: 1.0
Nodes (0): 

### Community 27 - "Community 27"
Cohesion: 1.0
Nodes (1): Historical intraday candles for backtest.

### Community 28 - "Community 28"
Cohesion: 1.0
Nodes (1): Latest OHLC/LTP per symbol (live/tick mode).

### Community 29 - "Community 29"
Cohesion: 1.0
Nodes (1): Live expiry list (broker-specific format, e.g. indices).

### Community 30 - "Community 30"
Cohesion: 1.0
Nodes (1): Connect and start receiving data (e.g. spawn background thread).

### Community 31 - "Community 31"
Cohesion: 1.0
Nodes (1): Disconnect and stop the feed.

### Community 32 - "Community 32"
Cohesion: 1.0
Nodes (1): Return True if the feed is connected and receiving.

### Community 33 - "Community 33"
Cohesion: 1.0
Nodes (0): 

### Community 34 - "Community 34"
Cohesion: 1.0
Nodes (1): Compute full RSI/prev_RSI columns for strategies that explicitly require RSI.

### Community 35 - "Community 35"
Cohesion: 1.0
Nodes (1): Return a stable signature only when strategy explicitly opts into         cross

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
Nodes (1): Bar close instant (UNIX): bucket start + timeframe length.         NSE cash IND

### Community 55 - "Community 55"
Cohesion: 1.0
Nodes (1): Bar instant as ISO in Asia/Kolkata (IST). Used for open/close UNIX conversion.

### Community 56 - "Community 56"
Cohesion: 1.0
Nodes (1): Integer bucket boundary. ts_sec in Unix seconds; tf_seconds e.g. 60, 300.

### Community 57 - "Community 57"
Cohesion: 1.0
Nodes (1): Lock-free candle engine. Ticks update only 1m current; when 1m bucket changes,

### Community 58 - "Community 58"
Cohesion: 1.0
Nodes (1): Process one tick. O(1). Updates only 1m current; closes 1m and propagates when b

### Community 59 - "Community 59"
Cohesion: 1.0
Nodes (1): Aggregate closed 1m into higher TFs; close only when bucket boundary aligns.

### Community 60 - "Community 60"
Cohesion: 1.0
Nodes (1): Return the last CLOSED candle only. Never returns forming candle; no repainting.

### Community 61 - "Community 61"
Cohesion: 1.0
Nodes (1): Return up to max_bars last closed candles for symbol/resolution (newest last).

### Community 62 - "Community 62"
Cohesion: 1.0
Nodes (1): Symbols that have at least some state (for health checks).

### Community 63 - "Community 63"
Cohesion: 1.0
Nodes (1): Return a stable signature only when strategy explicitly opts into         cross

### Community 64 - "Community 64"
Cohesion: 1.0
Nodes (1): Fallback patch only for the last row when RSI is missing/NaN.         Never rew

### Community 65 - "Community 65"
Cohesion: 1.0
Nodes (1): Append one JSON line per closed candle to logs/{engine_id}_candles.log.

### Community 66 - "Community 66"
Cohesion: 1.0
Nodes (1): Log skip reason; pass ``diagnostics=`` or other fields for feed/timestamp debugg

### Community 67 - "Community 67"
Cohesion: 1.0
Nodes (1): Log skip reason; pass ``diagnostics=`` or other fields for feed/timestamp debugg

### Community 68 - "Community 68"
Cohesion: 1.0
Nodes (1): Build step_size size dictionary for all stock option underlyings (OPTSTK)

### Community 69 - "Community 69"
Cohesion: 1.0
Nodes (1): Shared indicator layer for live engine.      Maintains per-(symbol,timeframe)

### Community 70 - "Community 70"
Cohesion: 1.0
Nodes (1): Fallback patch only for the last row when RSI is missing/NaN.         Never rew

### Community 71 - "Community 71"
Cohesion: 1.0
Nodes (1): Shared indicator layer for live engine.      Maintains per-(symbol,timeframe)

### Community 72 - "Community 72"
Cohesion: 1.0
Nodes (1): Fallback patch only for the last row when RSI is missing/NaN.         Never rew

### Community 73 - "Community 73"
Cohesion: 1.0
Nodes (1): Returns nearest OTM strikes relative to spot.         For spot = 17700, step =

### Community 74 - "Community 74"
Cohesion: 1.0
Nodes (1): Output:         NIFTY 30 MAR 25000 PUT         NIFTY 30 MAR 25000 CALL

### Community 75 - "Community 75"
Cohesion: 1.0
Nodes (1): Select last expiry of target month/year.

### Community 76 - "Community 76"
Cohesion: 1.0
Nodes (1): Dhan / Tradehull monthly option chain index for backtest (``expiry_code`` is int

### Community 77 - "Community 77"
Cohesion: 1.0
Nodes (1): Map DHAN ``expiry_code`` (0 = front monthly, 1 = next monthly) to a calendar exp

### Community 78 - "Community 78"
Cohesion: 1.0
Nodes (1): Inverse of ``dhan_expiry_index_to_date``: map a calendar expiry to DHAN ``expiry

### Community 79 - "Community 79"
Cohesion: 1.0
Nodes (1): Normalize values from ``params['expiry_code']`` / ``ctx.selected_expiry``: DHAN

### Community 80 - "Community 80"
Cohesion: 1.0
Nodes (1): Quarterly expiry label (future use).

### Community 81 - "Community 81"
Cohesion: 1.0
Nodes (1): Quarterly month selector (used by NSE & quarterly logic).

### Community 82 - "Community 82"
Cohesion: 1.0
Nodes (1): Build step_size size dictionary for all stock option underlyings (OPTSTK)

### Community 83 - "Community 83"
Cohesion: 1.0
Nodes (1): Per-engine structured logger. Thread-safe. Writes JSON lines to logs/{engine_id}

### Community 84 - "Community 84"
Cohesion: 1.0
Nodes (1): Same bar instant as ``bar_timestamp``, expressed in Asia/Kolkata (IST) for logs.

### Community 85 - "Community 85"
Cohesion: 1.0
Nodes (1): Append one JSON line per closed candle to logs/{engine_id}_candles.log.

### Community 86 - "Community 86"
Cohesion: 1.0
Nodes (1): Log skip reason; pass ``diagnostics=`` or other fields for feed/timestamp debugg

### Community 87 - "Community 87"
Cohesion: 1.0
Nodes (1): On startup, collapse older append-only logs to one row per still-open symbol.

### Community 88 - "Community 88"
Cohesion: 1.0
Nodes (1): One-time migrate older CSVs when new columns are introduced (rewrite in place).

### Community 89 - "Community 89"
Cohesion: 1.0
Nodes (1): Last row wins per symbol; keep only symbols that are still open (net_qty != 0

### Community 90 - "Community 90"
Cohesion: 1.0
Nodes (1): Live: replace file with one row per non-flat position after PM synced to broker.

### Community 91 - "Community 91"
Cohesion: 1.0
Nodes (1): Background thread: if connected but no application traffic for stall_sec, close

### Community 92 - "Community 92"
Cohesion: 1.0
Nodes (1): Optional control-plane helper: hold references to Dhan market / order / depth cl

### Community 93 - "Community 93"
Cohesion: 1.0
Nodes (1): Sleep with jitter to avoid synchronized reconnect storms; return next backoff (c

### Community 94 - "Community 94"
Cohesion: 1.0
Nodes (1): Background thread: if connected but no application traffic for stall_sec, close

### Community 95 - "Community 95"
Cohesion: 1.0
Nodes (1): Optional control-plane helper: hold references to Dhan market / order / depth cl

## Knowledge Gaps
- **337 isolated node(s):** `Trade log and performance analytics.  - Trade log: trade_id, entry_time, exit_`, `Compute PnL for a single trade row.     BUY: (exit_price - entry_price) * qty`, `Load trade log from CSV into a DataFrame.      Args:         csv_path: Path t`, `Sharpe ratio from trade PnL: (mean return - risk_free_rate) / std(return).`, `Full performance summary from a trades DataFrame.      Trades must have column` (+332 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **Thin community `Community 19`** (2 nodes): `slippage.py`, `allowed_slippage()`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 20`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 21`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 22`** (1 nodes): `Place a single order. Returns dict with "status" and on success "order_id".`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 23`** (1 nodes): `Current positions (broker-specific format).`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 24`** (1 nodes): `Place order from OrderIntent or dict. Returns order_id or None.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 25`** (1 nodes): `Exit a position explicitly. Must internally call place_order().`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 26`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 27`** (1 nodes): `Historical intraday candles for backtest.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 28`** (1 nodes): `Latest OHLC/LTP per symbol (live/tick mode).`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 29`** (1 nodes): `Live expiry list (broker-specific format, e.g. indices).`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 30`** (1 nodes): `Connect and start receiving data (e.g. spawn background thread).`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 31`** (1 nodes): `Disconnect and stop the feed.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 32`** (1 nodes): `Return True if the feed is connected and receiving.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 33`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 34`** (1 nodes): `Compute full RSI/prev_RSI columns for strategies that explicitly require RSI.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 35`** (1 nodes): `Return a stable signature only when strategy explicitly opts into         cross`
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
- **Thin community `Community 54`** (1 nodes): `Bar close instant (UNIX): bucket start + timeframe length.         NSE cash IND`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 55`** (1 nodes): `Bar instant as ISO in Asia/Kolkata (IST). Used for open/close UNIX conversion.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 56`** (1 nodes): `Integer bucket boundary. ts_sec in Unix seconds; tf_seconds e.g. 60, 300.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 57`** (1 nodes): `Lock-free candle engine. Ticks update only 1m current; when 1m bucket changes,`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 58`** (1 nodes): `Process one tick. O(1). Updates only 1m current; closes 1m and propagates when b`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 59`** (1 nodes): `Aggregate closed 1m into higher TFs; close only when bucket boundary aligns.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 60`** (1 nodes): `Return the last CLOSED candle only. Never returns forming candle; no repainting.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 61`** (1 nodes): `Return up to max_bars last closed candles for symbol/resolution (newest last).`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 62`** (1 nodes): `Symbols that have at least some state (for health checks).`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 63`** (1 nodes): `Return a stable signature only when strategy explicitly opts into         cross`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 64`** (1 nodes): `Fallback patch only for the last row when RSI is missing/NaN.         Never rew`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 65`** (1 nodes): `Append one JSON line per closed candle to logs/{engine_id}_candles.log.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 66`** (1 nodes): `Log skip reason; pass ``diagnostics=`` or other fields for feed/timestamp debugg`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 67`** (1 nodes): `Log skip reason; pass ``diagnostics=`` or other fields for feed/timestamp debugg`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 68`** (1 nodes): `Build step_size size dictionary for all stock option underlyings (OPTSTK)`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 69`** (1 nodes): `Shared indicator layer for live engine.      Maintains per-(symbol,timeframe)`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 70`** (1 nodes): `Fallback patch only for the last row when RSI is missing/NaN.         Never rew`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 71`** (1 nodes): `Shared indicator layer for live engine.      Maintains per-(symbol,timeframe)`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 72`** (1 nodes): `Fallback patch only for the last row when RSI is missing/NaN.         Never rew`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 73`** (1 nodes): `Returns nearest OTM strikes relative to spot.         For spot = 17700, step =`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 74`** (1 nodes): `Output:         NIFTY 30 MAR 25000 PUT         NIFTY 30 MAR 25000 CALL`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 75`** (1 nodes): `Select last expiry of target month/year.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 76`** (1 nodes): `Dhan / Tradehull monthly option chain index for backtest (``expiry_code`` is int`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 77`** (1 nodes): `Map DHAN ``expiry_code`` (0 = front monthly, 1 = next monthly) to a calendar exp`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 78`** (1 nodes): `Inverse of ``dhan_expiry_index_to_date``: map a calendar expiry to DHAN ``expiry`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 79`** (1 nodes): `Normalize values from ``params['expiry_code']`` / ``ctx.selected_expiry``: DHAN`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 80`** (1 nodes): `Quarterly expiry label (future use).`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 81`** (1 nodes): `Quarterly month selector (used by NSE & quarterly logic).`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 82`** (1 nodes): `Build step_size size dictionary for all stock option underlyings (OPTSTK)`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 83`** (1 nodes): `Per-engine structured logger. Thread-safe. Writes JSON lines to logs/{engine_id}`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 84`** (1 nodes): `Same bar instant as ``bar_timestamp``, expressed in Asia/Kolkata (IST) for logs.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 85`** (1 nodes): `Append one JSON line per closed candle to logs/{engine_id}_candles.log.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 86`** (1 nodes): `Log skip reason; pass ``diagnostics=`` or other fields for feed/timestamp debugg`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 87`** (1 nodes): `On startup, collapse older append-only logs to one row per still-open symbol.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 88`** (1 nodes): `One-time migrate older CSVs when new columns are introduced (rewrite in place).`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 89`** (1 nodes): `Last row wins per symbol; keep only symbols that are still open (net_qty != 0`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 90`** (1 nodes): `Live: replace file with one row per non-flat position after PM synced to broker.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 91`** (1 nodes): `Background thread: if connected but no application traffic for stall_sec, close`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 92`** (1 nodes): `Optional control-plane helper: hold references to Dhan market / order / depth cl`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 93`** (1 nodes): `Sleep with jitter to avoid synchronized reconnect storms; return next backoff (c`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 94`** (1 nodes): `Background thread: if connected but no application traffic for stall_sec, close`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 95`** (1 nodes): `Optional control-plane helper: hold references to Dhan market / order / depth cl`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `RunMode` connect `Community 2` to `Community 0`, `Community 1`, `Community 4`, `Community 5`, `Community 6`, `Community 8`, `Community 11`, `Community 12`?**
  _High betweenness centrality (0.144) - this node is a cross-community bridge._
- **Why does `IntentStatus` connect `Community 3` to `Community 1`, `Community 4`, `Community 6`?**
  _High betweenness centrality (0.048) - this node is a cross-community bridge._
- **Why does `create_live_engine()` connect `Community 4` to `Community 0`, `Community 1`, `Community 3`, `Community 5`, `Community 6`, `Community 7`, `Community 8`, `Community 10`, `Community 11`, `Community 12`?**
  _High betweenness centrality (0.047) - this node is a cross-community bridge._
- **Are the 236 inferred relationships involving `str` (e.g. with `.place_bracket_stop_loss()` and `.set_leverage_for_symbols()`) actually correct?**
  _`str` has 236 INFERRED edges - model-reasoned connections that need verification._
- **Are the 213 inferred relationships involving `RunMode` (e.g. with `OptionChainService` and `api: "NSE" or "DHAN"; ctx: StrategyContext; params: option chain params.`) actually correct?**
  _`RunMode` has 213 INFERRED edges - model-reasoned connections that need verification._
- **Are the 101 inferred relationships involving `IntentStatus` (e.g. with `SimulatedBroker` and `Simulated broker for both PAPER and BACKTEST. No real exchange; instant fill. PA`) actually correct?**
  _`IntentStatus` has 101 INFERRED edges - model-reasoned connections that need verification._
- **Are the 98 inferred relationships involving `ExpiryResolver` (e.g. with `DhanAdapter` and `DhanSource`) actually correct?**
  _`ExpiryResolver` has 98 INFERRED edges - model-reasoned connections that need verification._