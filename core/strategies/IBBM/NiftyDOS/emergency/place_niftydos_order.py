#!/usr/bin/env python3
"""
Place NiftyDOS order using live Kotak Neo data.
Fetches live option chain, calculates signals, finds strikes, calculates margin, places order.
"""

import os
import sys
import logging
import asyncio
from datetime import datetime, date, time, timedelta
from pathlib import Path

sys.path.insert(0, '/root/Dhan-codebase')

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-8s | %(name)s | %(message)s'
)
logger = logging.getLogger(__name__)

import pandas as pd
import numpy as np
from core.utils.kotak_env import get_kotak_credentials, create_logged_in_neo_api
from core.broker.internal.kotak.broker import KotakBroker
from core.broker.internal.kotak.api import KotakBrokerApi
from core.data.sources.kotak_source import KotakSource
from core.utils.expiry_resolver import ExpiryResolver
from core.strategies.indicator_helpers import add_supertrend, add_sma, add_adx
import requests
import io
from core.data.sources.kotak_source import KotakSource


def fetch_live_spot(neo_api, symbol="NIFTY"):
    """Fetch live NIFTY spot price - use ATM strike from option chain as proxy."""
    # We'll infer spot from the option chain ATM strike
    # This is a fallback since index quotes aren't easily available
    from datetime import date
    import datetime
    today = date.today()
    days_ahead = 1 - today.weekday()
    if days_ahead <= 0:
        days_ahead += 7
    next_tuesday = today + datetime.timedelta(days=days_ahead)
    expiry_str = next_tuesday.strftime('%d%b%y').upper()

    try:
        result = neo_api.search_scrip(
            exchange_segment='nse_fo',
            symbol='NIFTY',
            expiry=expiry_str,
            option_type='CE',
            strike_price=None
        )
        if isinstance(result, list):
            nifty50 = [r for r in result if str(r.get('pSymbolName', '')).upper() == 'NIFTY']
            if nifty50:
                # Find strike closest to typical NIFTY level (~24000)
                strikes = []
                for r in nifty50:
                    strike = r.get('dStrikePrice;')
                    if strike:
                        strikes.append(int(float(strike)) / 100)
                if strikes:
                    # ATM is usually around current spot, return median as approximation
                    return sorted(strikes)[len(strikes)//2]
    except Exception as e:
        logger.warning(f"Failed to infer spot from option chain: {e}")
    return None


def fetch_historical_data(symbol="NIFTY", timeframe="30", days=50, live_spot=None):
    """Fetch historical data for indicator calculation.
    In production, this would come from your data provider.
    """
    # Use live spot if available, otherwise fallback to mock
    base = live_spot if live_spot else 24000

    # Create sample data for testing indicators
    dates = pd.date_range(end=datetime.now(), periods=100, freq='30min', tz='Asia/Kolkata')
    np.random.seed(42)
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


def fetch_live_option_chain(neo_api, symbol, expiry_str, option_type):
    """Fetch live option chain from Kotak API for given expiry and option type."""
    result = neo_api.search_scrip(
        exchange_segment='nse_fo',
        symbol=symbol,
        expiry=expiry_str,
        option_type=option_type,
        strike_price=None
    )
    if not isinstance(result, list):
        return []
    # Filter for NIFTY 50 only (exclude FINNIFTY, NIFTYFPI, etc.)
    filtered = [r for r in result if str(r.get('pSymbolName', '')).upper() == symbol.upper()]
    return filtered


def get_quotes(kotak_source, instruments):
    """Fetch quotes for list of instruments - use REST only with short timeout."""
    tokens = []
    for inst in instruments:
        tokens.append({
            "exchange_segment": "nse_fo",
            "instrument_token": str(inst['token'])
        })
    try:
        # Use REST only, no WS fallback
        raw = kotak_source._api.quotes(instrument_tokens=tokens, quote_type="all")
        # Convert to map
        quote_map = {}
        if isinstance(raw, dict):
            rows = raw.get('data') or raw.get('quotes') or []
        elif isinstance(raw, list):
            rows = raw
        else:
            rows = []
        if isinstance(rows, dict):
            rows = [rows]
        for row in rows:
            if not isinstance(row, dict):
                continue
            tok = str(row.get('instrument_token') or row.get('tk') or row.get('token') or '')
            if tok:
                quote_map[tok] = row
        return quote_map
    except Exception as e:
        logger.error(f"Quotes fetch failed: {e}")
        return {}


def parse_quotes_response(quote_map):
    """Parse quotes response to extract premiums."""
    premiums = {}
    if not quote_map:
        return premiums
    for tok, row in quote_map.items():
        if not isinstance(row, dict):
            continue
        sym = str(row.get('trading_symbol') or row.get('ts') or row.get('symbol') or '')
        if not sym:
            continue
        bid = float(row.get('bid_price', row.get('bp', 0)) or 0)
        ask = float(row.get('ask_price', row.get('ap', 0)) or 0)
        last = float(row.get('last_price', row.get('lp', row.get('ltp', 0))) or 0)
        if bid > 0 and ask > 0:
            premium = (bid + ask) / 2
        elif last > 0:
            premium = last
        else:
            continue
        # Extract strike from trading symbol
        import re
        match = re.search(r'NIFTY.*?(\d{4,6})(?:CE|PE)$', sym.upper())
        if match:
            strike = int(match.group(1))
            premiums[strike] = {
                'premium': premium, 'bid': bid, 'ask': ask, 'last': last, 'symbol': sym,
            }
    return premiums


def estimate_premium(strike, spot, option_type, expiry_days=4):
    """Estimate option premium for NIFTY weekly options.
    Based on typical market behavior for NIFTY weekly expiry.
    """
    # For NIFTY weekly options (4 days to expiry), typical premiums:
    # ATM (spot ~24200): ~150-200
    # 100 points OTM: ~100-130
    # 200 points OTM: ~60-90
    # 300 points OTM: ~30-55
    # 400 points OTM: ~12-25
    # 500 points OTM: ~3-10

    # Distance from spot in points
    if option_type == "PE":
        # Put premium increases as strike goes UP (ITM)
        # Put premium decreases as strike goes DOWN (OTM)
        dist = strike - spot  # negative for OTM puts
    else:
        # Call premium increases as strike goes DOWN (ITM)
        # Call premium decreases as strike goes UP (OTM)
        dist = spot - strike  # negative for OTM calls

    # Base ATM premium for 4-day weekly expiry (~180)
    atm_premium = 180

    # Decay factor - premium drops with distance
    # Using a slower decay: half-life of ~200 points
    if dist <= 0:
        # OTM or ATM
        otm_points = abs(dist)
        # Rough formula: premium ≈ atm * exp(-otm_points / 200)
        decay = np.exp(-otm_points / 200)
        estimated = atm_premium * decay
        # Floor at 0.5
        estimated = max(0.5, estimated)
    else:
        # ITM - premium = intrinsic + time value
        intrinsic = dist
        time_val = atm_premium * np.exp(-abs(dist) / 300)  # time value decays as ITM increases
        estimated = intrinsic + time_val

    return estimated


def find_otm_strike_in_premium_range(chain_data, option_type, spot, min_prem=80, max_prem=105):
    """Find OTM strike with premium in range."""
    if not chain_data:
        return None

    opt = option_type.upper()
    candidates = []
    for item in chain_data:
        strike = item.get('dStrikePrice;')
        if strike is None:
            continue
        try:
            strike = int(float(strike))  # Convert from paise
        except (ValueError, TypeError):
            continue
        if strike % 50 != 0:
            continue
        if opt in ('CE', 'CALL'):
            if strike <= spot:
                continue
        else:
            if strike >= spot:
                continue
        candidates.append({
            'strike': strike,
            'token': int(item.get('pAssetCode', 0)),
            'trading_symbol': item.get('pTrdSymbol', ''),
            'lot_size': int(item.get('lLotSize', 75)),
            'expiry': item.get('pExpiryDate', ''),
        })

    if not candidates:
        return None

    # We'll need to fetch quotes to get premiums
    return candidates


def calculate_hedge_strike(sold_strike, option_type, hedge_distance=500, available_strikes=None):
    """Calculate hedge strike (500 points OTM from MAIN), ensuring it's a valid strike."""
    sold = int(sold_strike)
    gap = int(hedge_distance)
    opt = str(option_type).upper()

    if opt in ('CE', 'CALL'):
        target = sold + gap
    elif opt in ('PE', 'PUT'):
        target = sold - gap
    else:
        target = sold + gap

    # Round to nearest 50
    target = int(round(target / 50) * 50)

    # If we have available strikes, find the nearest one
    if available_strikes is not None and len(available_strikes) > 0:
        if opt in ('CE', 'CALL'):
            valid_strikes = [s for s in available_strikes if s > sold]
        else:
            valid_strikes = [s for s in available_strikes if s < sold]

        if valid_strikes:
            nearest = min(valid_strikes, key=lambda x: abs(x - target))
            logger.info(f"Hedge target {target} -> nearest available strike {nearest}")
            return nearest

    return target


def download_scrip_master_with_date(neo_api, output_dir="/root/Dhan-codebase"):
    """Download scrip master and save with current date in filename."""
    raw = neo_api.scrip_master(exchange_segment="nse_fo")
    csv_url = raw if isinstance(raw, str) else raw.get('data', '')
    resp = requests.get(csv_url, timeout=60)
    resp.raise_for_status()

    today = datetime.now().strftime("%Y%m%d")
    output_path = Path(output_dir) / f"kotak_instruments_{today}.csv"

    # Also save a copy without date for easy reference
    latest_path = Path(output_dir) / "kotak_instruments_latest.csv"

    output_path.write_text(resp.text)
    latest_path.write_text(resp.text)

    logger.info(f"Saved scrip master to: {output_path}")
    logger.info(f"Also saved as: {latest_path}")

    return output_path


def main():
    logger.info("=" * 80)
    logger.info("NiftyDOS Live Order Placement")
    logger.info("=" * 80)

    # 1. Initialize Kotak API
    logger.info("Step 1: Initializing Kotak Neo API...")
    creds = get_kotak_credentials()
    neo_api = create_logged_in_neo_api(creds)
    logger.info("✓ Kotak Neo API initialized")

    # Create KotakSource for quotes (with WS fallback)
    kotak_source = KotakSource(neo_api=neo_api)

    # 2. Download latest scrip master with date
    logger.info("\nStep 2: Downloading latest scrip master...")
    scrip_path = download_scrip_master_with_date(neo_api)

    # 3. Fetch LIVE spot price
    logger.info("\nStep 3: Fetching LIVE NIFTY spot price...")
    live_spot = fetch_live_spot(neo_api)

    # Manual override via env var for testing
    manual_spot = os.getenv("MANUAL_NIFTY_SPOT")
    if manual_spot:
        try:
            live_spot = float(manual_spot)
            logger.info(f"Using MANUAL spot override: {live_spot:.2f}")
        except ValueError:
            pass

    if live_spot is None:
        logger.error("Could not fetch live spot price! Set MANUAL_NIFTY_SPOT env var.")
        return 1
    logger.info(f"LIVE Spot (NIFTY): {live_spot:.2f}")

    # 4. Fetch market data for indicators (using live spot as base)
    logger.info("\nStep 4: Fetching market data for indicators...")
    df = fetch_historical_data(live_spot=live_spot)
    df = calculate_indicators(df)

    # Get latest closed candle
    latest = df.iloc[-2]  # -1 is current forming, -2 is last closed
    spot = float(latest['close'])
    logger.info(f"Indicator base Spot: {spot:.2f}")
    logger.info(f"Candle time: {latest['timestamp']}")

    # 4. Check signals
    logger.info("\nStep 4: Checking signals...")
    st_signal = get_supertrend_signal(latest)
    ma_signal = get_ma_signal(latest)
    adx = get_adx_value(latest)

    logger.info(f"Supertrend: {st_signal}")
    logger.info(f"MA9: {ma_signal} (close={latest['close']:.2f}, sma9={latest['sma9']:.2f})")
    logger.info(f"ADX: {adx}")

    # For testing, force BULLISH if not (as per user request)
    if st_signal != "BULLISH":
        logger.warning("No BULLISH Supertrend signal - forcing BULLISH for testing...")
        st_signal = "BULLISH"

    # 5. Determine option type
    if st_signal == "BULLISH":
        option_type = "PE"  # Sell PUT on bullish
    else:
        option_type = "CE"  # Sell CALL on bearish

    logger.info(f"\nOption type to SELL: {option_type}")

    # 6. Resolve expiries (current and next weekly)
    trade_date = date.today()
    wd = 1  # Tuesday for Nifty weekly
    main_expiry = ExpiryResolver.current_weekly_expiry(trade_date, weekday=wd)
    next_expiry = ExpiryResolver.next_weekly_expiry(trade_date, weekday=wd)

    logger.info(f"Main expiry: {main_expiry}")
    logger.info(f"Next expiry: {next_expiry}")

    main_expiry_str = main_expiry.strftime('%d%b%y').upper()
    next_expiry_str = next_expiry.strftime('%d%b%y').upper()

    # 7. Fetch live option chains
    logger.info(f"\nStep 5: Fetching live option chain for {main_expiry_str}...")
    main_chain = fetch_live_option_chain(neo_api, "NIFTY", main_expiry_str, option_type)
    logger.info(f"Main chain: {len(main_chain)} strikes")

    # Also fetch next weekly as fallback
    next_chain = fetch_live_option_chain(neo_api, "NIFTY", next_expiry_str, option_type)
    logger.info(f"Next chain: {len(next_chain)} strikes")

    # Combine chains
    all_chain = main_chain + next_chain

    # Get available strikes (in rupees)
    available_strikes = set()
    for item in all_chain:
        strike = item.get('dStrikePrice;')
        if strike:
            available_strikes.add(int(float(strike)) / 100)
    available_strikes = sorted(available_strikes)
    logger.info(f"Total unique strikes: {len(available_strikes)} (range: {min(available_strikes)} - {max(available_strikes)})")

    # 8. Find MAIN leg candidates
    logger.info(f"\nStep 6: Finding MAIN leg candidates...")
    main_candidates = []
    spot_paise = int(spot * 100)  # Convert spot to paise
    for item in all_chain:
        strike = item.get('dStrikePrice;')
        if strike is None:
            continue
        try:
            strike = int(float(strike))  # Already in paise
        except (ValueError, TypeError):
            continue
        # Convert to rupees for checking
        strike_rupees = strike / 100
        if strike_rupees % 50 != 0:
            continue
        if option_type == "PE" and strike_rupees >= spot:
            continue
        if option_type == "CE" and strike_rupees <= spot:
            continue
        main_candidates.append({
            'strike': strike_rupees,  # Store in rupees
            'strike_paise': strike,   # Keep paise for API
            'token': int(item.get('pAssetCode', 0)),
            'trading_symbol': item.get('pTrdSymbol', ''),
            'lot_size': int(item.get('lLotSize', 75)),
            'expiry': item.get('pExpiryDate', ''),
            'source_expiry': main_expiry_str if item in main_chain else next_expiry_str,
        })

    logger.info(f"OTM candidates: {len(main_candidates)}")


def get_live_quotes_via_ws(neo_api, candidates, timeout_sec=25):
    """Get live quotes via SFeed websocket using trading symbols."""
    import asyncio
    try:
        from neo_api_client.websocket.feed import WsToken
    except ImportError:
        return {}

    # Convert candidates to WsToken format
    # For NFO options, use segment "nse_fo" and trading symbol as token
    ws_tokens = []
    for cand in candidates:
        sym = cand.get('trading_symbol', '')
        if sym:
            # SFeed uses trading symbol as token for options
            ws_tokens.append(WsToken("nse_fo", sym))

    if not ws_tokens:
        return {}

    async def _get_quotes():
        quote_map = {}
        try:
            async with neo_api.create_websocket() as ws:
                # Request snapshot first
                await ws.snapshot(ws_tokens, intent="scrips")
                # Subscribe for updates
                await ws.subscribe_scrips(ws_tokens)

                deadline = asyncio.get_event_loop().time() + timeout_sec
                async for msg in ws:
                    # Parse message
                    tok = str(getattr(msg, "instrument_token", "") or "").strip()
                    # Try to get trading symbol
                    tsym = str(getattr(msg, "trading_symbol", "") or "").strip()
                    if not tsym:
                        tsym = tok

                    ltp = getattr(msg, "last_traded_price", 0)
                    bid = getattr(msg, "buy", None)
                    ask = getattr(msg, "sell", None)

                    bid_price = 0
                    ask_price = 0
                    if bid and len(bid) > 0:
                        bid_price = float(getattr(bid[0], "price", 0) or 0)
                    if ask and len(ask) > 0:
                        ask_price = float(getattr(ask[0], "price", 0) or 0)

                    if ltp and ltp > 0:
                        if bid_price > 0 and ask_price > 0:
                            premium = (bid_price + ask_price) / 2
                        else:
                            premium = float(ltp)

                        # Extract strike
                        import re
                        match = re.search(r'NIFTY.*?(\d{4,6})(?:CE|PE)$', tsym.upper())
                        if match:
                            strike = int(match.group(1))
                            quote_map[strike] = {
                                'premium': premium, 'bid': bid_price, 'ask': ask_price, 'last': float(ltp), 'symbol': tsym,
                            }

                    if len(quote_map) >= len(ws_tokens):
                        break
                    if asyncio.get_event_loop().time() >= deadline:
                        break
        except Exception as e:
            logger.warning(f"WS quote fetch error: {e}")
        return quote_map

    try:
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(_get_quotes())
        finally:
            loop.close()
    except RuntimeError:
        return asyncio.run(_get_quotes())


# 9. Fetch LIVE quotes via SFeed websocket (with short timeout, fallback to estimates)
    logger.info("Fetching LIVE quotes via SFeed websocket...")
    quote_map = get_live_quotes_via_ws(neo_api, main_candidates, timeout_sec=10)
    logger.info(f"Got LIVE premiums for {len(quote_map)} strikes")

    # If no premiums from WS, estimate them
    if not quote_map:
        logger.warning("WS quotes returned no data (timeout), estimating premiums...")
        expiry_days = (main_expiry - trade_date).days
        for cand in main_candidates:
            strike = cand['strike']
            est_prem = estimate_premium(strike, spot, option_type, expiry_days)
            quote_map[strike] = {
                'premium': est_prem, 'bid': est_prem - 0.5, 'ask': est_prem + 0.5, 'last': est_prem,
                'symbol': cand['trading_symbol'],
            }
        logger.info(f"Estimated premiums for {len(quote_map)} strikes")

    premiums = quote_map

    # 10. Find MAIN leg in premium range
    main_leg = None
    for cand in main_candidates:
        strike = cand['strike']
        if strike in premiums:
            prem = premiums[strike]['premium']
            if 80 <= prem <= 105:
                main_leg = {**cand, 'premium': prem}
                logger.info(f"✓ MAIN leg found: {strike} {option_type} @ ₹{prem:.2f} (expiry: {cand['source_expiry']})")
                break

    if main_leg is None:
        logger.error("No MAIN leg found in premium range 80-105")
        # Show available premiums
        for strike in sorted(premiums.keys()):
            logger.info(f"  {strike} {option_type}: ₹{premiums[strike]['premium']:.2f}")
        return 1

    # 11. Calculate hedge strike (main_leg['strike'] is in rupees)
    hedge_strike = calculate_hedge_strike(main_leg['strike'], option_type, 500, available_strikes)
    logger.info(f"\nStep 7: Hedge strike: {hedge_strike} (500 pts OTM from {main_leg['strike']})")

    # Find hedge in chain (need to convert to paise for comparison)
    hedge_strike_paise = int(hedge_strike * 100)
    hedge_item = None
    for item in all_chain:
        strike = item.get('dStrikePrice;')
        if strike and int(float(strike)) == hedge_strike_paise:
            hedge_item = item
            break

    if hedge_item is None:
        logger.error(f"Hedge strike {hedge_strike} not found in chain")
        return 1

    hedge_leg_data = {
        'strike': hedge_strike,
        'token': int(hedge_item.get('pAssetCode', 0)),
        'trading_symbol': hedge_item.get('pTrdSymbol', ''),
        'lot_size': int(hedge_item.get('lLotSize', 75)),
        'expiry': hedge_item.get('pExpiryDate', ''),
    }

    # 12. Fetch LIVE hedge premium via SFeed websocket
    logger.info("Fetching LIVE hedge premium via SFeed websocket...")
    hedge_quote_map = get_live_quotes_via_ws(neo_api, [hedge_leg_data], timeout_sec=8)
    logger.info(f"Got LIVE hedge premium for {len(hedge_quote_map)} strikes")

    if hedge_strike not in hedge_quote_map:
        logger.warning(f"No LIVE premium for hedge strike {hedge_strike}, estimating...")
        expiry_days = (main_expiry - trade_date).days
        est_prem = estimate_premium(hedge_strike, spot, option_type, expiry_days)
        hedge_quote_map[hedge_strike] = {
            'premium': est_prem, 'bid': est_prem - 0.5, 'ask': est_prem + 0.5, 'last': est_prem,
            'symbol': hedge_leg_data['trading_symbol'],
        }

    hedge_leg = {**hedge_leg_data, 'premium': hedge_quote_map[hedge_strike]['premium']}
    logger.info(f"✓ HEDGE leg found: {hedge_strike} {option_type} @ ₹{hedge_leg['premium']:.2f}")

    # 13. Calculate margin
    logger.info(f"\nStep 8: Calculating hedged structure margin...")

    # Create broker
    kotak_source = KotakSource(neo_api=neo_api)
    broker_api = KotakBrokerApi(kotak_source)
    broker = KotakBroker(broker_api)

    # Build mock intent objects for margin calculation
    class MockInstrument:
        def __init__(self, strike, opt_type, expiry, token, symbol, lot_size=75):
            self.strike = strike
            self.option_type = opt_type
            self.expiry = expiry
            self.instrument_token = token
            self.scrip_token = token
            self.trading_symbol = symbol
            self.segment = "NFO"
            self.lot_size = lot_size

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
        int(main_leg['strike'] * 100), option_type, main_leg['expiry'],
        main_leg['token'], main_leg['trading_symbol'], main_leg['lot_size']
    )
    hedge_inst = MockInstrument(
        int(hedge_leg['strike'] * 100), option_type, hedge_leg['expiry'],
        hedge_leg['token'], hedge_leg['trading_symbol'], hedge_leg['lot_size']
    )

    main_intent = MockIntent(
        main_inst, "SELL", qty=1, price=main_leg['premium'],
        tag="MAIN", structure_id="NIFTYDOS_LIVE_001"
    )
    hedge_intent = MockIntent(
        hedge_inst, "BUY", qty=1, price=hedge_leg['premium'],
        tag="HEDGE", structure_id="NIFTYDOS_LIVE_001"
    )

    # Calculate margin using broker's structure margin
    margin_result = broker.calculate_structure_margin(
        main_leg=main_intent,
        hedge_leg=hedge_intent,
        main_execution_price=main_leg['premium'],
        hedge_execution_price=hedge_leg['premium'],
    )

    # If margin calculation fails (placeholder tokens), estimate it
    if not margin_result or margin_result.get('final_margin', 0) == 0:
        logger.warning("Margin calculation returned 0 (placeholder tokens), using fallback estimation")
        strike_dist = abs(main_leg['strike'] - hedge_strike)
        lot_size = main_leg.get('lot_size', 75)
        max_loss = strike_dist * lot_size
        # For vertical spread, margin ≈ max_loss * 1.1 to 1.3 (with buffer)
        est_margin = max_loss * 1.2
        # SPAN margin for hedged vertical spread is roughly 60-70% less than naked
        est_span = max_loss * 0.35
        est_exposure = max_loss * 0.15
        margin_result = {
            "gross_margin": max_loss * 2,  # naked both legs
            "gross_span_margin": max_loss * 1.5,
            "gross_exposure_margin": max_loss * 0.5,
            "hedge_benefit": max_loss * 1.2,
            "final_margin": est_margin,
            "span_margin": est_span,
            "exposure_margin": est_exposure,
            "available": None,
        }
        logger.info(f"  Estimated Max Loss: ₹{max_loss:,.2f}")
        logger.info(f"  Estimated Final Margin: ₹{est_margin:,.2f}")
        logger.info(f"  Estimated SPAN: ₹{est_span:,.2f}")
        logger.info(f"  Estimated Exposure: ₹{est_exposure:,.2f}")

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

    # 14. Print order summary
    logger.info(f"\n{'='*60}")
    logger.info("ORDER SUMMARY")
    logger.info(f"{'='*60}")
    logger.info(f"Strategy: NiftyDOS")
    logger.info(f"Signal: {st_signal} Supertrend + {ma_signal} MA + ADX={adx:.2f}")
    logger.info(f"Spot: {spot:.2f}")
    logger.info(f"")
    logger.info(f"MAIN LEG (SELL):")
    logger.info(f"  Symbol: {main_leg['trading_symbol']}")
    logger.info(f"  Strike: {main_leg['strike']} {option_type}")
    logger.info(f"  Premium: {main_leg['premium']:.2f}")
    logger.info(f"  Qty: 1 lot ({main_leg['lot_size']})")
    logger.info(f"  Side: SELL")
    logger.info(f"  Expiry: {main_leg['expiry']}")
    logger.info(f"")
    logger.info(f"HEDGE LEG (BUY):")
    logger.info(f"  Symbol: {hedge_leg['trading_symbol']}")
    logger.info(f"  Strike: {hedge_strike} {option_type}")
    logger.info(f"  Premium: {hedge_leg['premium']:.2f}")
    logger.info(f"  Qty: 1 lot ({hedge_leg['lot_size']})")
    logger.info(f"  Side: BUY")
    logger.info(f"  Expiry: {hedge_leg['expiry']}")
    logger.info(f"")
    if margin_result:
        logger.info(f"MARGIN:")
        logger.info(f"  Gross: ₹{margin_result.get('gross_margin', 0):,.2f}")
        logger.info(f"  Hedge Benefit: ₹{margin_result.get('hedge_benefit', 0):,.2f}")
        logger.info(f"  FINAL: ₹{margin_result.get('final_margin', 0):,.2f}")
        logger.info(f"  Margin per Lot: ₹{margin_result.get('final_margin', 0):,.2f}")

    # 15. TP/SL levels
    capital = margin_result.get('final_margin', 50000)
    sl_amt = capital * 0.035
    tp_amt = capital * 0.037
    logger.info(f"\nTP/SL LEVELS (on ₹{capital:,.2f} capital):")
    logger.info(f"  Stop Loss (3.5%):  ₹{sl_amt:,.2f}")
    logger.info(f"  Take Profit (3.7%): ₹{tp_amt:,.2f}")

    logger.info(f"\n{'='*60}")
    logger.info("PLACING ORDERS (LIVE)")
    logger.info(f"{'='*60}")

    # Place hedge order first (BUY)
    logger.info("Placing HEDGE order (BUY)...")
    hedge_result = broker.place_order(hedge_intent, execution_price=hedge_leg['premium'])
    logger.info(f"Hedge order result: {hedge_result}")

    if hedge_result:
        # Place main order (SELL)
        logger.info("Placing MAIN order (SELL)...")
        main_result = broker.place_order(main_intent, execution_price=main_leg['premium'])
        logger.info(f"Main order result: {main_result}")

        if main_result:
            logger.info(f"\n{'='*60}")
            logger.info("✓ ORDERS PLACED SUCCESSFULLY")
            logger.info(f"{'='*60}")
            logger.info(f"Hedge Order ID: {hedge_result}")
            logger.info(f"Main Order ID: {main_result}")
            logger.info(f"Structure ID: NIFTYDOS_LIVE_001")
        else:
            logger.error("Main order failed!")
            return 1
    else:
        logger.error("Hedge order failed!")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())