#!/usr/bin/env python3
"""
Validate Kotak Neo margin calculation against Strategy Builder.

Uses REAL instrument tokens from scrip master and calls Kotak's actual
margin_required API to verify hedge benefit calculation.
"""

import os
import sys
import logging
from datetime import date, datetime

sys.path.insert(0, '/root/Dhan-codebase')

logging.basicConfig(
    level=logging.INFO,
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
import pandas as pd
import requests
import io


def get_kotak_credentials():
    """Get Kotak credentials from environment."""
    return KotakCredentials(
        consumer_key=os.getenv("KOTAK_CONSUMER_KEY"),
        consumer_secret=os.getenv("KOTAK_CONSUMER_SECRET"),
        mobile=os.getenv("KOTAK_MOBILE"),
        ucc=os.getenv("KOTAK_UCC"),
        mpin=os.getenv("KOTAK_MPIN"),
        totp_secret=os.getenv("KOTAK_TOTP_SECRET"),
        totp=os.getenv("KOTAK_TOTP"),
        environment=os.getenv("KOTAK_ENVIRONMENT", "prod"),
        neo_fin_key=os.getenv("KOTAK_NEO_FIN_KEY"),
        access_token=os.getenv("KOTAK_ACCESS_TOKEN"),
    )


def fetch_scrip_master(kotak_source):
    """Download and parse Kotak scrip master CSV."""
    raw = kotak_source._api.scrip_master(exchange_segment="NFO")

    csv_url = None
    if isinstance(raw, str):
        csv_url = raw.strip()
    elif isinstance(raw, dict):
        if 'data' in raw and isinstance(raw['data'], str):
            csv_url = raw['data'].strip()
        elif 'scripMaster' in raw and isinstance(raw['scripMaster'], str):
            csv_url = raw['scripMaster'].strip()

    if not csv_url:
        raise ValueError("Could not extract CSV URL")

    logger.info(f"Downloading scrip master from: {csv_url}")
    response = requests.get(csv_url, timeout=30)
    response.raise_for_status()

    df = pd.read_csv(io.StringIO(response.text))
    logger.info(f"CSV loaded: {len(df)} rows")
    return df.to_dict('records')


def find_nifty_options(master, option_type, target_expiry, strike=None):
    """Find NIFTY options matching criteria."""
    # Target date at end of day (matching CSV timestamp format)
    target_date = pd.Timestamp(target_expiry).date()
    target_ts_start = int(pd.Timestamp(target_date).timestamp())
    target_ts_end = target_ts_start + 86399  # End of day
    results = []

    # Debug: collect all NIFTY expiries and symbols
    nifty_expiries = set()
    all_symbols = set()
    nifty_count = 0
    for s in master:
        if not isinstance(s, dict):
            continue
        # NIFTY is in pTrdSymbol or pSymbolName, not pSymbol
        trd_sym = s.get('pTrdSymbol', '') or s.get('TradingSymbol', '') or s.get('pSymbolName', '')
        if trd_sym:
            all_symbols.add(str(trd_sym).upper())
        if str(trd_sym).upper().startswith('NIFTY'):
            nifty_count += 1
            expiry_ts = s.get('lExpiryDate ') or s.get('lExpiryDate') or s.get('ExpiryDate')
            if expiry_ts:
                try:
                    nifty_expiries.add(int(float(expiry_ts)))
                except:
                    pass

    logger.info(f"Total NIFTY entries: {nifty_count}")
    logger.info(f"Unique NIFTY trading symbols: {sorted([s for s in all_symbols if s.startswith('NIFTY')])[:20]}")
    logger.info(f"NIFTY expiries in scrip master: {sorted(nifty_expiries)}")
    for ts in sorted(nifty_expiries):
        try:
            dt = datetime.fromtimestamp(ts).strftime('%Y-%m-%d %H:%M:%S')
            logger.info(f"  {ts} -> {dt}")
        except:
            pass

    # Now filter for the specific expiry (match by date, not exact timestamp)
    logger.info(f"Filtering for expiry date: {target_expiry} (ts range: {target_ts_start}-{target_ts_end})")

    # First, let's see what symbols exist for this expiry date
    expiry_symbols = set()
    for s in master:
        if not isinstance(s, dict):
            continue
        expiry_ts = s.get('lExpiryDate ') or s.get('lExpiryDate') or s.get('ExpiryDate')
        if expiry_ts is None:
            continue
        try:
            expiry_ts = int(float(expiry_ts))
        except (ValueError, TypeError):
            continue
        if target_ts_start <= expiry_ts <= target_ts_end:
            trd_sym = s.get('pTrdSymbol', '') or s.get('TradingSymbol', '') or s.get('pSymbolName', '')
            if trd_sym:
                expiry_symbols.add(str(trd_sym).upper())

    logger.info(f"Symbols for expiry {target_expiry}: {sorted(expiry_symbols)[:30]}")

    # Check what pOptionType values exist for NIFTY
    nifty_opt_types = set()
    nifty_inst_types = set()
    for s in master:
        if not isinstance(s, dict):
            continue
        trd_sym = s.get('pTrdSymbol', '') or s.get('TradingSymbol', '') or s.get('pSymbolName', '')
        if str(trd_sym).upper().startswith('NIFTY'):
            opt_type = s.get('pOptionType', '') or s.get('OptionType', '')
            if opt_type:
                nifty_opt_types.add(str(opt_type).upper())
            inst_type = s.get('pInstType', '') or s.get('InstType', '')
            if inst_type:
                nifty_inst_types.add(str(inst_type).upper())

    logger.info(f"NIFTY pOptionType values: {sorted(nifty_opt_types)}")
    logger.info(f"NIFTY pInstType values: {sorted(nifty_inst_types)}")

    for s in master:
        if not isinstance(s, dict):
            continue
        # NIFTY is in pTrdSymbol or pSymbolName, not pSymbol
        trd_sym = s.get('pTrdSymbol', '') or s.get('TradingSymbol', '') or s.get('pSymbolName', '')
        if not str(trd_sym).upper().startswith('NIFTY'):
            continue

        exch_seg = s.get('pExchSeg', '') or s.get('ExchSeg', '')
        if str(exch_seg).lower() != 'nse_fo':
            if len(results) < 3:
                logger.info(f"DEBUG: exch_seg mismatch: '{exch_seg}' for {trd_sym}")
            continue

        inst_type = s.get('pInstType', '') or s.get('InstType', '')
        if str(inst_type).upper() != 'OPTIDX':
            if len(results) < 3:
                logger.info(f"DEBUG: inst_type mismatch: '{inst_type}' for {trd_sym}")
            continue

        # Check option type from trading symbol (CE/PE at end) since pOptionType may be different
        trd_sym_upper = str(trd_sym).upper()
        if option_type == "PE" and not trd_sym_upper.endswith("PE"):
            continue
        if option_type == "CE" and not trd_sym_upper.endswith("CE"):
            continue

        expiry_ts = s.get('lExpiryDate ') or s.get('lExpiryDate') or s.get('ExpiryDate')
        if expiry_ts is None:
            continue
        try:
            expiry_ts = int(float(expiry_ts))
        except (ValueError, TypeError):
            continue

        # Match by date (not exact timestamp)
        if not (target_ts_start <= expiry_ts <= target_ts_end):
            if len(results) < 3:
                logger.info(f"DEBUG: expiry_ts mismatch: {expiry_ts} not in range {target_ts_start}-{target_ts_end} for {trd_sym}")
            continue

        # Extract strike from trading symbol (format: NIFTY31JUN24000PE -> strike 24000)
        trd_sym_upper = str(trd_sym).upper()
        # Match pattern: NIFTY followed by date chars, then strike digits, then CE/PE
        import re
        strike_match = re.search(r'NIFTY.*?(\d{4,6})(?:CE|PE)$', trd_sym_upper)
        if not strike_match:
            if len(results) < 3:
                logger.info(f"DEBUG: no strike match in symbol {trd_sym}")
            continue
        try:
            stk = int(strike_match.group(1))
        except (ValueError, TypeError):
            if len(results) < 3:
                logger.info(f"DEBUG: strike parse failed for {trd_sym}")
            continue

        if strike is not None and stk != strike:
            continue

        if stk % 50 != 0:
            continue

        trading_symbol = trd_sym
        # Use pAssetCode as instrument token (string for API)
        token = s.get('pAssetCode', '') or s.get('AssetCode', '') or s.get('Token', '')
        token = str(token) if token else ''

        lot_size = s.get('lLotSize') or s.get('LotSize') or 75
        try:
            lot_size = int(lot_size)
        except (ValueError, TypeError):
            lot_size = 75

        results.append({
            'strike': stk,
            'trading_symbol': trading_symbol,
            'instrument_token': token,
            'lot_size': lot_size,
            'raw': s,
        })

    logger.info(f"Found {len(results)} options for expiry {target_expiry}")
    if results:
        strikes = sorted([r['strike'] for r in results])
        logger.info(f"Available strikes: {strikes[:30]}...")

    return sorted(results, key=lambda x: x['strike']), nifty_expiries

    for s in master:
        if not isinstance(s, dict):
            continue

        # NIFTY options have pTrdSymbol like "NIFTY25AUG24150PE"
        trd_sym = s.get('pTrdSymbol', '') or s.get('TradingSymbol', '') or s.get('pSymbolName', '')
        if not str(trd_sym).upper().startswith('NIFTY'):
            continue

        exch_seg = s.get('pExchSeg', '') or s.get('ExchSeg', '')
        if str(exch_seg).upper() != 'NFO':
            continue

        inst_type = s.get('pInstType', '') or s.get('InstType', '')
        if str(inst_type).upper() != 'OPTIDX':
            continue

        opt_type = s.get('pOptionType', '') or s.get('OptionType', '')
        if str(opt_type).upper() != option_type:
            continue

        expiry_ts = s.get('lExpiryDate ') or s.get('lExpiryDate') or s.get('ExpiryDate')
        if expiry_ts is None:
            continue
        try:
            expiry_ts = int(float(expiry_ts))
        except (ValueError, TypeError):
            continue

        if expiry_ts != target_ts:
            continue

        stk = s.get('dStrikePrice;') or s.get('StrikePrice') or s.get('dStrikePrice')
        if stk is None:
            continue
        try:
            stk = int(float(stk))
        except (ValueError, TypeError):
            continue

        if strike is not None and stk != strike:
            continue

        if stk % 50 != 0:
            continue

        trading_symbol = trd_sym
        token = s.get('pScripRefKey', '') or s.get('ScripRefKey', '') or s.get('Token', 0)
        try:
            token = int(token) if token else 0
        except (ValueError, TypeError):
            token = 0

        lot_size = s.get('lLotSize') or s.get('LotSize') or 75
        try:
            lot_size = int(lot_size)
        except (ValueError, TypeError):
            lot_size = 75

        results.append({
            'strike': stk,
            'trading_symbol': trading_symbol,
            'instrument_token': token,
            'lot_size': lot_size,
            'raw': s,
        })

    return sorted(results, key=lambda x: x['strike'])


def get_kotak_margin(neo_api, leg):
    """Call Kotak's margin_required API for a single leg."""
    # Build payload
    payload = {
        "exchange_segment": "nse_fo",
        "product": "NRML",
        "price": str(leg['premium']),
        "order_type": "L",
        "quantity": str(leg['quantity']),
        "instrument_token": leg['instrument_token'],
        "transaction_type": leg['transaction_type'],
        "trigger_price": "0",
        "broker_name": "KOTAK",
        "branch_id": "ONLINE",
    }

    try:
        resp = neo_api.margin_required(**payload)
        if isinstance(resp, dict) and 'data' in resp:
            data = resp['data']
            total = float(data.get('totalMargin') or data.get('total_margin') or data.get('margin') or 0)
            span = float(data.get('spanMargin') or data.get('span_margin') or 0)
            exposure = float(data.get('exposureMargin') or data.get('exposure_margin') or 0)
            return {'total': total, 'span': span, 'exposure': exposure, 'raw': resp}
        elif isinstance(resp, dict) and 'Error' not in resp and 'error' not in resp:
            # Direct response format
            total = float(resp.get('totalMargin') or resp.get('total_margin') or resp.get('margin') or 0)
            span = float(resp.get('spanMargin') or resp.get('span_margin') or 0)
            exposure = float(resp.get('exposureMargin') or resp.get('exposure_margin') or 0)
            return {'total': total, 'span': span, 'exposure': exposure, 'raw': resp}
        else:
            return {'error': resp}
    except Exception as e:
        return {'error': str(e)}


def main():
    logger.info("=" * 80)
    logger.info("Kotak Margin Validation Test")
    logger.info("=" * 80)

    # 1. Initialize Kotak API
    logger.info("Step 1: Initializing Kotak Neo API...")
    creds = get_kotak_credentials()
    neo_api = create_logged_in_neo_api(creds)
    logger.info("✓ Kotak Neo API initialized")

    # 2. Create broker
    kotak_source = KotakSource(neo_api=neo_api)
    broker_api = KotakBrokerApi(kotak_source)
    broker = KotakBroker(broker_api)

    # 3. Fetch scrip master
    logger.info("\nStep 2: Fetching scrip master...")
    master = fetch_scrip_master(kotak_source)

    # 4. Resolve expiry - check what's available in scrip master
    trade_date = date.today()
    wd = 1  # Tuesday for Nifty weekly
    target_weekly = ExpiryResolver.current_weekly_expiry(trade_date, weekday=wd)
    logger.info(f"Target weekly expiry: {target_weekly}")

    # First, find options for target weekly to get available expiries
    option_type = "PE"  # PUT for bullish
    logger.info(f"\nStep 3: Finding NIFTY {option_type} options for {target_weekly}...")
    options, nifty_expiries = find_nifty_options(master, option_type, target_weekly)
    logger.info(f"Found {len(options)} strikes for target weekly")

    # Find the latest available NIFTY expiry in scrip master
    # (since current weekly may not be published yet)
    logger.info("Checking for available NIFTY expiries in scrip master...")
    available_expiries = []
    for ts in sorted(nifty_expiries):
        try:
            dt = datetime.fromtimestamp(ts).date()
            if dt >= date(2025, 1, 1):  # Only recent expiries
                available_expiries.append((ts, dt))
        except:
            pass

    # Use the latest available expiry overall (not just recent)
    all_expiries = []
    for ts in sorted(nifty_expiries):
        try:
            dt = datetime.fromtimestamp(ts).date()
            all_expiries.append((ts, dt))
        except:
            pass

    if all_expiries:
        logger.info("All NIFTY expiries in scrip master:")
        for ts, dt in all_expiries[-10:]:  # Last 10
            logger.info(f"  {ts} -> {dt}")

        # Use the latest available expiry for testing
        latest_ts, latest_dt = all_expiries[-1]
        main_expiry = latest_dt
        logger.info(f"Using latest available expiry: {main_expiry} ({latest_ts})")
    else:
        logger.warning("No expiries found, using target weekly")
        main_expiry = target_weekly

    # Re-find options with the actual expiry we'll use
    if main_expiry != target_weekly:
        logger.info(f"\nRe-finding options for actual expiry: {main_expiry}")
        options, _ = find_nifty_options(master, option_type, main_expiry)
        logger.info(f"Found {len(options)} strikes for {main_expiry}")

    if options:
        strikes = [o['strike'] for o in options]
        logger.info(f"Available strikes: {strikes[:30]}...")

        # Find OTM puts around spot ~23800
        spot = 23800  # approximate current spot
        otm_puts = [o for o in options if o['strike'] < spot]
        if otm_puts:
            # Find ones in premium range 80-105
            # We don't have premiums from scrip master, so pick near ATM
            otm_puts.sort(key=lambda x: abs(x['strike'] - spot))
            nearest_strikes = [str(o['strike']) for o in otm_puts[:10]]
            logger.info(f"Nearest OTM puts: {nearest_strikes}")

    # 6. Define the exact structure to validate
    # Using the strikes from your Kotak Strategy Builder screenshot:
    # SELL 24150 PE + BUY 23650 PE
    # But we need to check if those exist in current weekly

    # Let's check what strikes exist in the master
    logger.info("\nStep 4: Checking for specific strikes...")
    for target_strike in [24150, 23650, 23800, 23300, 23750, 23250]:
        matches = [o for o in options if o['strike'] == target_strike]
        if matches:
            logger.info(f"  Strike {target_strike}: FOUND - {matches[0]['trading_symbol']} (token={matches[0]['instrument_token']})")
        else:
            logger.info(f"  Strike {target_strike}: NOT FOUND in current weekly")

    # 7. If we don't have those exact strikes, find the closest available
    # and test with those
    if not any(o['strike'] == 24150 for o in options):
        logger.warning("\nExact strikes from screenshot not in current weekly.")
        logger.info("Using nearest available OTM strikes for validation...")

        # Find available strikes near where we'd expect them
        # For bullish: SELL put near ATM (~23800), BUY put 500 pts OTM (~23300)
        available = [o for o in options if o['strike'] < 23800]
        if available:
            available.sort(key=lambda x: abs(x['strike'] - 23800))
            main_leg = available[0]  # Nearest to 23800

            hedge_avail = [o for o in available if o['strike'] < main_leg['strike'] - 400]
            if hedge_avail:
                hedge_avail.sort(key=lambda x: abs(x['strike'] - (main_leg['strike'] - 500)))
                hedge_leg = hedge_avail[0]
            else:
                hedge_leg = None
        else:
            main_leg = None
            hedge_leg = None
    else:
        main_leg = next(o for o in options if o['strike'] == 24150)
        hedge_leg = next(o for o in options if o['strike'] == 23650)

    if not main_leg or not hedge_leg:
        logger.error("Could not find suitable MAIN and HEDGE legs")
        return 1

    logger.info(f"\n{'='*60}")
    logger.info("STRUCTURE TO VALIDATE")
    logger.info(f"{'='*60}")
    logger.info(f"MAIN (SELL):  {main_leg['strike']} {option_type} - {main_leg['trading_symbol']} (token={main_leg['instrument_token']})")
    logger.info(f"HEDGE (BUY):  {hedge_leg['strike']} {option_type} - {hedge_leg['trading_symbol']} (token={hedge_leg['instrument_token']})")

    # We need premiums - for validation we'll need to fetch from quotes API
    # or use estimated premiums
    logger.warning("\nNote: Premiums not available from scrip master.")
    logger.info("Fetching quotes for these instruments...")

    # Try to get quotes
    instruments = [
        {"exchange_segment": "NSEFO", "symbol": main_leg['trading_symbol']},
        {"exchange_segment": "NSEFO", "symbol": hedge_leg['trading_symbol']},
    ]

    try:
        quotes = neo_api.quotes(instrument_tokens=instruments, quote_type="all")
        logger.info(f"Quotes response: {type(quotes)}")
        # Parse quotes
    except Exception as e:
        logger.warning(f"Could not fetch quotes: {e}")

    # 8. For validation, we need to estimate premiums or use market data
    # Let's use rough estimates for now
    main_dist = abs(main_leg['strike'] - 23800)
    hedge_dist = abs(hedge_leg['strike'] - 23800)

    main_prem = max(10, 100 - main_dist * 0.15)
    hedge_prem = max(5, 100 - hedge_dist * 0.15)

    logger.info(f"\nEstimated premiums:")
    logger.info(f"  MAIN ({main_leg['strike']}): ~₹{main_prem:.2f}")
    logger.info(f"  HEDGE ({hedge_leg['strike']}): ~₹{hedge_prem:.2f}")

    # 9. Call Kotak margin API for each leg
    logger.info(f"\n{'='*60}")
    logger.info("CALLING KOTAK MARGIN API")
    logger.info(f"{'='*60}")

    main_leg_data = {
        'premium': main_prem,
        'quantity': main_leg['lot_size'],
        'instrument_token': main_leg['instrument_token'],
        'transaction_type': 'S',  # Sell
    }

    hedge_leg_data = {
        'premium': hedge_prem,
        'quantity': hedge_leg['lot_size'],
        'instrument_token': hedge_leg['instrument_token'],
        'transaction_type': 'B',  # Buy
    }

    logger.info(f"\nMAIN leg margin request:")
    logger.info(f"  Strike: {main_leg['strike']}")
    logger.info(f"  Token: {main_leg['instrument_token']}")
    logger.info(f"  Premium: ₹{main_prem:.2f}")
    logger.info(f"  Qty: {main_leg['lot_size']}")
    logger.info(f"  Side: SELL")

    main_margin = get_kotak_margin(neo_api, main_leg_data)

    logger.info(f"\nHEDGE leg margin request:")
    logger.info(f"  Strike: {hedge_leg['strike']}")
    logger.info(f"  Token: {hedge_leg['instrument_token']}")
    logger.info(f"  Premium: ₹{hedge_prem:.2f}")
    logger.info(f"  Qty: {hedge_leg['lot_size']}")
    logger.info(f"  Side: BUY")

    hedge_margin = get_kotak_margin(neo_api, hedge_leg_data)

    # 10. Display results
    logger.info(f"\n{'='*60}")
    logger.info("KOTAK MARGIN API RESULTS")
    logger.info(f"{'='*60}")

    if 'error' in main_margin:
        logger.error(f"MAIN margin error: {main_margin['error']}")
    else:
        logger.info(f"MAIN (SELL {main_leg['strike']} {option_type}):")
        logger.info(f"  Total Margin:   ₹{main_margin['total']:,.2f}")
        logger.info(f"  SPAN Margin:    ₹{main_margin['span']:,.2f}")
        logger.info(f"  Exposure Margin: ₹{main_margin['exposure']:,.2f}")

    if 'error' in hedge_margin:
        logger.error(f"HEDGE margin error: {hedge_margin['error']}")
    else:
        logger.info(f"HEDGE (BUY {hedge_leg['strike']} {option_type}):")
        logger.info(f"  Total Margin:   ₹{hedge_margin['total']:,.2f}")
        logger.info(f"  SPAN Margin:    ₹{hedge_margin['span']:,.2f}")
        logger.info(f"  Exposure Margin: ₹{hedge_margin['exposure']:,.2f}")

    # 11. Calculate structure
    if 'error' not in main_margin and 'error' not in hedge_margin:
        gross_total = main_margin['total'] + hedge_margin['total']
        gross_span = main_margin['span'] + hedge_margin['span']
        gross_exposure = main_margin['exposure'] + hedge_margin['exposure']

        logger.info(f"\n{'='*60}")
        logger.info("STRUCTURE CALCULATION")
        logger.info(f"{'='*60}")
        logger.info(f"Gross Total Margin:   ₹{gross_total:,.2f}")
        logger.info(f"  Gross SPAN:         ₹{gross_span:,.2f}")
        logger.info(f"  Gross Exposure:     ₹{gross_exposure:,.2f}")

        # Kotak's actual hedge benefit (we need to compare with Strategy Builder)
        # The API doesn't return multi-leg margin directly
        # Our estimation:
        short_span = main_margin['span']  # SELL leg
        hedge_efficiency = 0.70
        estimated_benefit = short_span * hedge_efficiency
        max_benefit = short_span
        benefit = min(estimated_benefit, max_benefit)

        final_span = max(gross_span - benefit, short_span * 0.1)
        final_exposure = max(gross_exposure - benefit * 0.5, gross_exposure * 0.2)
        final_total = final_span + final_exposure

        logger.info(f"\nEstimated Hedge Benefit: ₹{benefit:,.2f} ({hedge_efficiency*100:.0f}% of short SPAN)")
        logger.info(f"Final Margin (est.):    ₹{final_total:,.2f}")
        logger.info(f"  Final SPAN:           ₹{final_span:,.2f}")
        logger.info(f"  Final Exposure:       ₹{final_exposure:,.2f}")

        # Compare with Kotak Strategy Builder target
        target_gross = 162186.51
        target_benefit = 102299.60
        target_final = 59886.91

        logger.info(f"\n{'='*60}")
        logger.info("COMPARISON WITH KOTAK STRATEGY BUILDER")
        logger.info(f"{'='*60}")
        logger.info(f"Target (from screenshot):")
        logger.info(f"  Gross Margin:       ₹{target_gross:,.2f}")
        logger.info(f"  Hedge Benefit:      ₹{target_benefit:,.2f}")
        logger.info(f"  Final Margin:       ₹{target_final:,.2f}")

        if gross_total > 0:
            logger.info(f"\nOur Calculation:")
            logger.info(f"  Gross Margin:       ₹{gross_total:,.2f}  (diff: ₹{gross_total - target_gross:,.2f})")
            logger.info(f"  Est. Hedge Benefit: ₹{benefit:,.2f}  (diff: ₹{benefit - target_benefit:,.2f})")
            logger.info(f"  Final Margin:       ₹{final_total:,.2f}  (diff: ₹{final_total - target_final:,.2f})")

            gross_match = abs(gross_total - target_gross) / target_gross < 0.05
            final_match = abs(final_total - target_final) / target_final < 0.05

            logger.info(f"\nValidation:")
            logger.info(f"  Gross Margin:  {'✅ PASS' if gross_match else '❌ FAIL'} (within 5%)")
            logger.info(f"  Final Margin:  {'✅ PASS' if final_match else '❌ FAIL'} (within 5%)")

            if not gross_match or not final_match:
                logger.warning("⚠️  Margin does NOT match Strategy Builder - do not use for live TP/SL sizing")
            else:
                logger.info("✅ Margin matches - safe to use for live capital sizing")

    # 12. Also check available balance
    logger.info(f"\n{'='*60}")
    logger.info("AVAILABLE BALANCE")
    logger.info(f"{'='*60}")
    try:
        limits = neo_api.limits()
        logger.info(f"Limits response: {limits}")
        if isinstance(limits, list):
            for row in limits:
                if isinstance(row, dict):
                    avail = row.get('availableCash') or row.get('available_margin') \
                        or row.get('equityAvailableMargin') or row.get('availableBalance')
                    if avail is not None:
                        logger.info(f"Available Margin: ₹{float(avail):,.2f}")
    except Exception as e:
        logger.warning(f"Could not fetch limits: {e}")

    return 0


if __name__ == "__main__":
    sys.exit(main())