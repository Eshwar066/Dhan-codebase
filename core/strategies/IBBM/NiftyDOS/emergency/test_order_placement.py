#!/usr/bin/env python3
"""
Emergency test script to place an order for NiftyDOS strategy.
Connects to Kotak Neo, finds bullish Supertrend signal, logs strikes/premium/margin.
"""

import os
import sys
import logging
import asyncio
from datetime import datetime, date, time, timedelta

sys.path.insert(0, '/root/Dhan-codebase')

# Setup logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s | %(levelname)-8s | %(name)s | %(message)s'
)
logger = logging.getLogger(__name__)

# Import required modules
from core.utils.kotak_env import KotakCredentials, create_logged_in_neo_api
from core.broker.internal.kotak import mappings as kotak_map
from core.broker.internal.kotak.broker import KotakBroker
from core.broker.internal.kotak.api import KotakBrokerApi
from core.data.sources.kotak_source import KotakSource
from core.utils.expiry_resolver import ExpiryResolver
from core.strategies.indicator_helpers import add_supertrend, add_sma, add_adx
import pandas as pd
import numpy as np


# Use the proper get_kotak_credentials from kotak_env
from core.utils.kotak_env import get_kotak_credentials as get_kotak_creds


def fetch_historical_data(symbol="NIFTY", timeframe="30", days=50):
    """Fetch historical data for indicator calculation.
    In production, this would come from your data provider.
    """
    # This is a placeholder - you'd fetch from your data source
    # For testing, we'll create mock data structure
    logger.warning("Using mock data - replace with actual data feed")

    # Create sample data for testing indicators
    dates = pd.date_range(end=datetime.now(), periods=100, freq='30min', tz='Asia/Kolkata')
    np.random.seed(42)
    base = 24000
    closes = base + np.cumsum(np.random.randn(100) * 20)

    df = pd.DataFrame({
        'timestamp': dates,
        'open': closes + np.random.randn(100) * 5,
        'high': closes + np.abs(np.random.randn(100) * 10),
        'low': closes - np.abs(np.random.randn(100) * 10),
        'close': closes,
        'volume': np.random.randint(1000, 10000, 100),
    })
    df['symbol'] = symbol
    return df


def calculate_indicators(df):
    """Calculate Supertrend, SMA9, ADX."""
    df = add_supertrend(df, length=16, factor=2.0)
    df = add_sma(df, period=9, column='sma9')
    df['prev_sma9'] = df['sma9'].shift(1)
    df = add_adx(df, period=14)
    if 'close' in df.columns:
        df['prev_close'] = df['close'].shift(1)
    return df


def get_supertrend_signal(candle):
    """Get Supertrend direction: BULLISH or BEARISH."""
    # Columns from add_supertrend: supertrend, supertrend_direction
    dir_key = 'supertrend_direction'
    dir_val = candle.get(dir_key)
    if pd.isna(dir_val):
        return None
    return "BULLISH" if dir_val == 1 else "BEARISH"


def get_ma_signal(candle):
    """Get MA9 direction."""
    close = candle.get('close')
    ma = candle.get('sma9')
    if pd.isna(close) or pd.isna(ma):
        return None
    return "BULLISH" if close > ma else "BEARISH"


def get_adx_value(candle):
    """Get ADX value."""
    val = candle.get('adx_14')
    if pd.isna(val):
        return None
    return float(val)

def get_sma_value(candle):
    """Get SMA9 value."""
    return candle.get('sma9')


def find_otm_strike_in_premium_range(chain, option_type, spot, min_prem=80, max_prem=105, step=50):
    """Find OTM strike with premium in range (strikes are multiples of 50)."""
    if chain is None or not hasattr(chain, 'empty') or chain.empty:
        return None

    opt = option_type.upper()
    if opt in ('CE', 'CALL'):
        # OTM calls: strike > spot
        candidates = chain[(chain['strike'] > spot) & (chain['option_type'] == opt)].copy()
    else:
        # OTM puts: strike < spot
        candidates = chain[(chain['strike'] < spot) & (chain['option_type'] == opt)].copy()

    if candidates.empty:
        return None

    # Calculate premium (use mid of bid/ask or last price)
    candidates['premium'] = candidates.apply(
        lambda r: (r.get('bid_price', 0) + r.get('ask_price', 0)) / 2
        if r.get('bid_price', 0) > 0 and r.get('ask_price', 0) > 0
        else r.get('last_price', r.get('ltp', 0)), axis=1
    )

    # Filter by premium range
    in_range = candidates[
        (candidates['premium'] >= min_prem) &
        (candidates['premium'] <= max_prem)
    ].copy()

    if in_range.empty:
        logger.debug(f"No strikes in premium range {min_prem}-{max_prem}. Available premiums: {sorted(candidates['premium'].unique())[:20]}")
        return None

    # Return the one closest to ATM (smallest strike distance)
    in_range['distance'] = (in_range['strike'] - spot).abs()
    best = in_range.nsmallest(1, 'distance').iloc[0]

    return {
        'strike': int(best['strike']),
        'premium': float(best['premium']),
        'instrument_token': int(best.get('instrument_token', best.get('tk', 0))),
        'trading_symbol': best.get('trading_symbol', best.get('ts', '')),
    }


def calculate_hedge_strike(sold_strike, option_type, hedge_distance=500, step=50, available_strikes=None):
    """Calculate hedge strike (500 points OTM from MAIN), ensuring it's a valid strike in chain."""
    sold = int(sold_strike)
    gap = int(hedge_distance)
    opt = str(option_type).upper()

    if opt in ('CE', 'CALL'):
        target = sold + gap
    elif opt in ('PE', 'PUT'):
        target = sold - gap
    else:
        target = sold + gap

    # Round to nearest step
    target = int(round(target / step) * step)

    # If we have available strikes, find the nearest one
    if available_strikes is not None and len(available_strikes) > 0:
        # Filter to same direction (OTM from sold strike)
        if opt in ('CE', 'CALL'):
            valid_strikes = [s for s in available_strikes if s > sold]
        else:
            valid_strikes = [s for s in available_strikes if s < sold]

        if valid_strikes:
            # Find closest to target
            nearest = min(valid_strikes, key=lambda x: abs(x - target))
            logger.info(f"Hedge target {target} -> nearest available strike {nearest}")
            return nearest

    return target


def get_hedge_premium(chain, hedge_strike, option_type):
    """Get premium for hedge strike."""
    if chain is None or not hasattr(chain, 'empty') or chain.empty:
        return None

    opt = option_type.upper()
    # Ensure hedge_strike is int for comparison
    hs = int(hedge_strike)
    # Find matching row - use pandas query for robustness
    mask = (chain['strike'].astype(int) == hs) & (chain['option_type'].str.upper() == opt)
    row = chain[mask]

    if row.empty:
        # Debug: show available strikes
        available = sorted(chain[chain['option_type'].str.upper() == opt]['strike'].unique())
        logger.debug(f"Hedge strike {hs} not found. Available {opt} strikes: {available[:20]}...")
        # Try nearest strike
        if len(available) > 0:
            nearest = min(available, key=lambda x: abs(x - hs))
            logger.warning(f"Using nearest strike {nearest} instead of {hs}")
            hs = nearest
            mask = (chain['strike'].astype(int) == hs) & (chain['option_type'].str.upper() == opt)
            row = chain[mask]

    if row.empty:
        return None

    r = row.iloc[0]
    premium = (r.get('bid_price', 0) + r.get('ask_price', 0)) / 2 \
        if r.get('bid_price', 0) > 0 and r.get('ask_price', 0) > 0 \
        else r.get('last_price', r.get('ltp', 0))

    return {
        'premium': float(premium),
        'instrument_token': int(r.get('instrument_token', r.get('tk', 0))),
        'trading_symbol': r.get('trading_symbol', r.get('ts', '')),
    }


def main():
    """Main test function."""
    logger.info("=" * 80)
    logger.info("NiftyDOS Emergency Order Test")
    logger.info("=" * 80)

    # 1. Initialize Kotak API
    logger.info("Step 1: Initializing Kotak Neo API...")
    creds = get_kotak_creds()

    try:
        neo_api = create_logged_in_neo_api(creds)
        logger.info("✓ Kotak Neo API initialized")
    except Exception as e:
        logger.exception(f"Failed to initialize Kotak API: {e}")
        return 1

    # 2. Create broker
    kotak_source = KotakSource(neo_api=neo_api)
    broker_api = KotakBrokerApi(kotak_source)
    broker = KotakBroker(broker_api)

    # 3. Fetch market data (mock for now)
    logger.info("\nStep 2: Fetching market data...")
    df = fetch_historical_data()
    df = calculate_indicators(df)

    # Get latest closed candle
    latest = df.iloc[-2]  # -1 is current forming, -2 is last closed
    spot = float(latest['close'])
    logger.info(f"Spot (NIFTY): {spot:.2f}")
    logger.info(f"Candle time: {latest['timestamp']}")

    # 4. Check signals
    logger.info("\nStep 3: Checking signals...")
    st_signal = get_supertrend_signal(latest)
    ma_signal = get_ma_signal(latest)
    adx = get_adx_value(latest)

    logger.info(f"Supertrend: {st_signal}")
    logger.info(f"MA9: {ma_signal} (close={latest['close']:.2f}, sma9={latest['sma9']:.2f})")
    logger.info(f"ADX: {adx}")

    if st_signal != "BULLISH":
        logger.warning("No BULLISH Supertrend signal - strategy would SELL PUT on bullish")
        logger.info("Forcing BULLISH for testing...")
        st_signal = "BULLISH"

    if adx is None or adx < 25:
        logger.warning(f"ADX ({adx}) < 25, but continuing for test")

    # 5. Determine option type
    if st_signal == "BULLISH":
        option_type = "PE"  # Sell PUT on bullish
    else:
        option_type = "CE"  # Sell CALL on bearish

    logger.info(f"\nOption type to SELL: {option_type}")

    # 6. Resolve expiry
    trade_date = date.today()
    wd = 1  # Tuesday for Nifty weekly
    main_expiry = ExpiryResolver.current_weekly_expiry(trade_date, weekday=wd)
    logger.info(f"Main expiry: {main_expiry}")

    # 7. Fetch option chain from Kotak scrip master
    logger.info(f"\nStep 4: Fetching option chain for {main_expiry}...")
    try:
        # Get raw response - it's a CSV URL
        raw = kotak_source._api.scrip_master(exchange_segment="NFO")
        logger.info(f"Raw scrip master type: {type(raw)}")

        csv_url = None
        if isinstance(raw, str):
            logger.info(f"Raw string length: {len(raw)}")
            logger.info(f"Raw string preview: {raw[:500]}")
            csv_url = raw.strip()
        elif isinstance(raw, dict):
            logger.info(f"Raw dict keys: {raw.keys()}")
            if 'data' in raw and isinstance(raw['data'], str):
                csv_url = raw['data'].strip()
            elif 'scripMaster' in raw and isinstance(raw['scripMaster'], str):
                csv_url = raw['scripMaster'].strip()

        if not csv_url:
            logger.error("Could not extract CSV URL from scrip master response")
            return 1

        logger.info(f"Downloading scrip master CSV from: {csv_url}")

        # Download and parse CSV
        import requests
        import io
        response = requests.get(csv_url, timeout=30)
        response.raise_for_status()

        # Parse CSV
        df = pd.read_csv(io.StringIO(response.text))
        logger.info(f"CSV loaded: {len(df)} rows, columns: {list(df.columns)}")

        # Convert to list of dicts
        master = df.to_dict('records')
        logger.info(f"Scrip master loaded: {len(master)} instruments")
        if master:
            logger.info(f"Sample instrument: {master[0]}")
            logger.info(f"Sample keys: {list(master[0].keys())}")

        # Filter for NIFTY options with correct expiry and type
        # Kotak CSV columns: pSymbol, pTrdSymbol, pOptionType, dStrikePrice;, lExpiryDate, pExchSeg, lLotSize, pInstType
        # Expiry is a timestamp (lExpiryDate - note trailing space in CSV header!)
        target_expiry_ts = int(pd.Timestamp(main_expiry).timestamp())
        logger.info(f"Target expiry timestamp: {target_expiry_ts} ({main_expiry})")

        # Debug: check what symbols are in the CSV
        symbols = set()
        for s in master:
            sym = s.get('pSymbol', '') or s.get('Symbol', '')
            if sym:
                symbols.add(str(sym).upper())
        logger.info(f"Unique symbols in CSV: {sorted(symbols)}")

        # Debug: check a few sample expiries for NIFTY specifically
        sample_expiries = set()
        nifty_expiries = set()
        nifty_count = 0
        nifty_fo_count = 0
        for s in master:
            exp = s.get('lExpiryDate ') or s.get('lExpiryDate') or s.get('ExpiryDate')
            sym = s.get('pSymbol', '') or s.get('Symbol', '')
            exch = s.get('pExchSeg', '') or s.get('ExchSeg', '')
            inst = s.get('pInstType', '') or s.get('InstType', '')
            if str(sym).upper().startswith('NIFTY'):
                nifty_count += 1
                if str(exch).upper() == 'NFO':
                    nifty_fo_count += 1
                if exp:
                    try:
                        nifty_expiries.add(int(float(exp)))
                    except:
                        pass
            elif exp:
                try:
                    sample_expiries.add(int(float(exp)))
                except:
                    pass
        logger.info(f"Sample expiry timestamps from CSV (all): {sorted(sample_expiries)[:10]}")
        logger.info(f"NIFTY entries total: {nifty_count}, NIFTY NFO: {nifty_fo_count}")
        logger.info(f"NIFTY expiry timestamps from CSV: {sorted(nifty_expiries)[:20]}")

        # Convert target to see if it's milliseconds
        target_ms = target_expiry_ts * 1000
        logger.info(f"Target expiry timestamp (ms): {target_ms}")

        # Also print first few NIFTY entries to see their structure
        logger.info("First 3 NIFTY entries:")
        nifty_shown = 0
        for s in master:
            if str(s.get('pSymbol', '')).upper().startswith('NIFTY'):
                logger.info(f"  {s}")
                nifty_shown += 1
                if nifty_shown >= 3:
                    break

        chain = []
        for s in master:
            if not isinstance(s, dict):
                continue

            # Filter by symbol (pSymbol for NIFTY)
            sym = s.get('pSymbol', '') or s.get('Symbol', '')
            if not str(sym).upper().startswith('NIFTY'):
                continue

            # Filter by exchange segment (pExchSeg should be NFO for options)
            exch_seg = s.get('pExchSeg', '') or s.get('ExchSeg', '')
            if str(exch_seg).upper() != 'NFO':
                continue

            # Filter by instrument type (pInstType should be OPTIDX for index options)
            inst_type = s.get('pInstType', '') or s.get('InstType', '')
            if str(inst_type).upper() != 'OPTIDX':
                continue

            # Check option type (pOptionType)
            opt_type = s.get('pOptionType', '') or s.get('OptionType', '')
            if str(opt_type).upper() != option_type:
                continue

            # Check expiry (lExpiryDate is timestamp - note trailing space in key!)
            expiry_ts = s.get('lExpiryDate ') or s.get('lExpiryDate') or s.get('ExpiryDate')
            if expiry_ts is None:
                continue
            try:
                expiry_ts = int(float(expiry_ts))
            except (ValueError, TypeError):
                continue

            if expiry_ts != target_expiry_ts:
                continue

            # Get strike (dStrikePrice;)
            strike = s.get('dStrikePrice;') or s.get('StrikePrice') or s.get('dStrikePrice')
            if strike is None:
                continue
            try:
                strike = int(float(strike))
            except (ValueError, TypeError):
                continue

            if strike % 50 != 0:
                continue

            # Get trading symbol
            trading_symbol = s.get('pTrdSymbol', '') or s.get('TradingSymbol', '') or s.get('pSymbolName', '')

            # Get lot size (lLotSize)
            lot_size = s.get('lLotSize') or s.get('LotSize') or 75
            try:
                lot_size = int(lot_size)
            except (ValueError, TypeError):
                lot_size = 75

            # Get instrument token (pScripRefKey or similar)
            token = s.get('pScripRefKey', '') or s.get('ScripRefKey', '') or s.get('Token', 0)
            try:
                token = int(token) if token else 0
            except (ValueError, TypeError):
                token = 0

            chain.append({
                'strike': strike,
                'option_type': option_type,
                'expiry': main_expiry.strftime('%d%b%y').upper(),
                'bid_price': 0,  # Not available in scrip master
                'ask_price': 0,
                'last_price': 0,
                'instrument_token': token,
                'trading_symbol': trading_symbol,
                'lot_size': lot_size,
            })

        logger.info(f"Filtered chain from master: {len(chain)} strikes")
        if chain:
            strikes = sorted([c['strike'] for c in chain])
            logger.info(f"Available strikes: {strikes[:20]}...")
        else:
            # No NIFTY options found - raise to trigger mock fallback
            raise ValueError("NIFTY options not found in scrip master for current expiry")

    except Exception as e:
        logger.warning(f"Could not fetch scrip master or NIFTY not found: {e}")
        logger.info("Using MOCK option chain data for testing")
        # Create mock chain around spot with 50-point strikes
        strikes = list(range(int(spot) - 1000, int(spot) + 1000, 50))
        chain = []
        for k in strikes:
            dist = abs(k - spot)
            prem = max(5, 100 - dist * 0.15)
            if option_type == "PE" and k < spot:
                prem = max(5, 100 - (spot - k) * 0.15)
            elif option_type == "CE" and k > spot:
                prem = max(5, 100 - (k - spot) * 0.15)

            chain.append({
                'strike': k,
                'option_type': option_type,
                'expiry': main_expiry.strftime('%d%b%y').upper(),
                'bid_price': prem - 0.5,
                'ask_price': prem + 0.5,
                'last_price': prem,
                'instrument_token': 1000000 + k,
                'trading_symbol': f"NIFTY{main_expiry.strftime('%y%b').upper()}{k}{option_type}",
                'lot_size': 75,
            })
        chain = pd.DataFrame(chain)
        logger.info(f"Mock chain loaded: {len(chain)} rows")

    # 8. Ensure we have valid chain data
    if chain is None or (hasattr(chain, 'empty') and chain.empty):
        logger.error("No valid option chain data")
        return 1

    if not isinstance(chain, pd.DataFrame):
        chain = pd.DataFrame(chain)
    logger.info(f"Chain loaded: {len(chain)} rows")

    # 9. Find MAIN leg strike
    logger.info(f"\nStep 5: Finding MAIN leg strike (premium 80-105)...")
    main_leg = find_otm_strike_in_premium_range(chain, option_type, spot, 80, 105)

    if main_leg is None:
        logger.error("No MAIN leg found in premium range 80-105")
        return 1

    logger.info(f"✓ MAIN leg found:")
    logger.info(f"  Strike: {main_leg['strike']}")
    logger.info(f"  Premium: {main_leg['premium']:.2f}")
    logger.info(f"  Trading Symbol: {main_leg['trading_symbol']}")
    logger.info(f"  Instrument Token: {main_leg['instrument_token']}")

    # 10. Calculate hedge strike
    available_strikes = sorted(chain['strike'].unique())
    hedge_strike = calculate_hedge_strike(main_leg['strike'], option_type, 500, available_strikes=available_strikes)
    logger.info(f"\nStep 6: Calculating HEDGE leg...")
    logger.info(f"  Hedge strike: {hedge_strike} (500 pts OTM from {main_leg['strike']})")

    hedge_leg = get_hedge_premium(chain, hedge_strike, option_type)

    if hedge_leg is None:
        logger.error(f"No hedge found at strike {hedge_strike}")
        return 1

    logger.info(f"✓ HEDGE leg found:")
    logger.info(f"  Strike: {hedge_strike}")
    logger.info(f"  Premium: {hedge_leg['premium']:.2f}")
    logger.info(f"  Trading Symbol: {hedge_leg['trading_symbol']}")
    logger.info(f"  Instrument Token: {hedge_leg['instrument_token']}")

    # 11. Calculate structure margin
    logger.info(f"\nStep 7: Calculating hedged structure margin...")

    # Build mock intent objects for margin calculation
    class MockInstrument:
        def __init__(self, strike, opt_type, expiry, token, symbol):
            self.strike = strike
            self.option_type = opt_type
            self.expiry = expiry
            self.instrument_token = token
            self.scrip_token = token
            self.trading_symbol = symbol
            self.segment = "NFO"
            self.lot_size = 75

        def place_order_symbol(self):
            return self.trading_symbol

    class MockIntent:
        def __init__(self, instrument, side, qty=1, price=0, trigger_price=0,
                     order_type="LIMIT", trade_type="MARGIN", tag="MAIN",
                     structure_id="TEST_STRUCT", action="ENTRY"):
            self.instrument = instrument
            self.side = side
            self.qty = qty
            self.price = price
            self.trigger_price = trigger_price
            self.order_type = order_type
            self.trade_type = trade_type
            self.tag = tag
            self.structure_id = structure_id
            self.action = action
            self.intent_id = f"intent_{id(self)}"

    main_inst = MockInstrument(
        main_leg['strike'], option_type, main_expiry,
        main_leg['instrument_token'], main_leg['trading_symbol']
    )
    hedge_inst = MockInstrument(
        hedge_strike, option_type, main_expiry,
        hedge_leg['instrument_token'], hedge_leg['trading_symbol']
    )

    main_intent = MockIntent(
        main_inst, "SELL", qty=1, price=main_leg['premium'],
        tag="MAIN", structure_id="TEST_STRUCT_001"
    )
    hedge_intent = MockIntent(
        hedge_inst, "BUY", qty=1, price=hedge_leg['premium'],
        tag="HEDGE", structure_id="TEST_STRUCT_001"
    )

    # Calculate margin
    margin_result = broker.calculate_structure_margin(
        main_leg=main_intent,
        hedge_leg=hedge_intent,
        main_execution_price=main_leg['premium'],
        hedge_execution_price=hedge_leg['premium'],
    )

    if margin_result:
        logger.info(f"\n{'='*60}")
        logger.info("MARGIN CALCULATION RESULT")
        logger.info(f"{'='*60}")
        logger.info(f"Gross Margin (no hedge):     ₹{margin_result.get('gross_margin', 0):,.2f}")
        logger.info(f"  - SPAN:                     ₹{margin_result.get('gross_span_margin', 0):,.2f}")
        logger.info(f"  - Exposure:                 ₹{margin_result.get('gross_exposure_margin', 0):,.2f}")
        logger.info(f"Hedge Benefit:                ₹{margin_result.get('hedge_benefit', 0):,.2f}")
        logger.info(f"Final Margin (with hedge):    ₹{margin_result.get('final_margin', 0):,.2f}")
        logger.info(f"  - SPAN:                     ₹{margin_result.get('span_margin', 0):,.2f}")
        logger.info(f"  - Exposure:                 ₹{margin_result.get('exposure_margin', 0):,.2f}")
        avail = margin_result.get('available')
        logger.info(f"Available Balance:            ₹{avail:,.2f}" if avail else "Available Balance:            N/A")
        logger.info(f"Margin per Lot:               ₹{margin_result.get('final_margin', 0):,.2f}")

        # Check funds
        funds_check = broker.check_funds_before_orders([
            (main_intent, main_leg['premium']),
            (hedge_intent, hedge_leg['premium']),
        ], include_position=True, include_orders=True)

        if funds_check:
            logger.info(f"\nFunds Check:")
            logger.info(f"  OK: {funds_check.get('ok', False)}")
            logger.info(f"  Required: ₹{funds_check.get('required_margin', 0):,.2f}")
            avail_f = funds_check.get('available')
            logger.info(f"  Available: ₹{avail_f:,.2f}" if avail_f else "  Available: N/A")
            logger.info(f"  Shortfall: ₹{funds_check.get('shortfall', 0):,.2f}")
            logger.info(f"  Hedge Benefit: ₹{funds_check.get('hedge_benefit', 0):,.2f}")
            logger.info(f"  Message: {funds_check.get('message', '')}")
    else:
        logger.warning("Margin calculation returned None - instrument tokens may not be valid for Kotak API")
        logger.info("Using fallback margin estimation...")
        # Fallback estimation for display
        strike_dist = abs(main_leg['strike'] - hedge_strike)
        max_loss = strike_dist * 75  # lot_size
        est_margin = max_loss * 1.2  # rough estimate with buffer
        logger.info(f"  Estimated Max Loss: ₹{max_loss:,.2f}")
        logger.info(f"  Estimated Margin (with buffer): ₹{est_margin:,.2f}")
        logger.info(f"  Margin per Lot: ₹{est_margin:,.2f}")
        margin_result = {"final_margin": est_margin}

    # 12. Print order summary
    logger.info(f"\n{'='*60}")
    logger.info("ORDER SUMMARY (DRY RUN)")
    logger.info(f"{'='*60}")
    logger.info(f"Strategy: NiftyDOS")
    logger.info(f"Signal: {st_signal} Supertrend + {ma_signal} MA + ADX={adx:.2f}")
    logger.info(f"Spot: {spot:.2f}")
    logger.info(f"")
    logger.info(f"MAIN LEG (SELL):")
    logger.info(f"  Symbol: {main_leg['trading_symbol']}")
    logger.info(f"  Strike: {main_leg['strike']} {option_type}")
    logger.info(f"  Premium: {main_leg['premium']:.2f}")
    logger.info(f"  Qty: 1 lot (75)")
    logger.info(f"  Side: SELL")
    logger.info(f"")
    logger.info(f"HEDGE LEG (BUY):")
    logger.info(f"  Symbol: {hedge_leg['trading_symbol']}")
    logger.info(f"  Strike: {hedge_strike} {option_type}")
    logger.info(f"  Premium: {hedge_leg['premium']:.2f}")
    logger.info(f"  Qty: 1 lot (75)")
    logger.info(f"  Side: BUY")
    logger.info(f"")
    if margin_result:
        logger.info(f"MARGIN:")
        logger.info(f"  Gross: ₹{margin_result.get('gross_margin', 0):,.2f}")
        logger.info(f"  Hedge Benefit: ₹{margin_result.get('hedge_benefit', 0):,.2f}")
        logger.info(f"  FINAL: ₹{margin_result.get('final_margin', 0):,.2f}")
        logger.info(f"  Margin per Lot: ₹{margin_result.get('final_margin', 0):,.2f}")

    logger.info(f"\n{'='*60}")
    logger.info("DRY RUN COMPLETE - No orders placed")
    logger.info(f"{'='*60}")
    logger.info("To place actual orders, uncomment the order placement code below")
    logger.info("and ensure you have sufficient margin in your Kotak account")

    # UNCOMMENT BELOW TO PLACE ACTUAL ORDERS (USE WITH CAUTION!)
    # Place hedge order first
    # logger.info("Placing HEDGE order (BUY)...")
    # hedge_result = broker.place_order(hedge_intent, execution_price=hedge_leg['premium'])
    # logger.info(f"Hedge order result: {hedge_result}")
    #
    # if hedge_result:
    #     # Place main order
    #     logger.info("Placing MAIN order (SELL)...")
    #     main_result = broker.place_order(main_intent, execution_price=main_leg['premium'])
    #     logger.info(f"Main order result: {main_result}")

    return 0


if __name__ == "__main__":
    sys.exit(main())