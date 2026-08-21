#!/usr/bin/env python3
"""
Validate Kotak Neo margin using CURRENT expiry and real premiums.

Uses scrip master to get tokens, then quotes API for real premiums.
"""

import os
import sys
import logging
import re
import requests
import io
from datetime import date, datetime

sys.path.insert(0, '/root/Dhan-codebase')

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-8s | %(name)s | %(message)s'
)
logger = logging.getLogger(__name__)

from core.utils.kotak_env import KotakCredentials, create_logged_in_neo_api
from core.utils.expiry_resolver import ExpiryResolver
import pandas as pd


def get_kotak_credentials():
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


def get_current_expiry():
    """Get current weekly expiry for NIFTY."""
    trade_date = date.today()
    wd = 1  # Tuesday
    return ExpiryResolver.current_weekly_expiry(trade_date, weekday=wd)


def find_strikes_near_spot(spot, count=15):
    """Find strikes near spot by searching for NIFTY options."""
    step = 50
    start = int(spot / step) * step
    strikes = list(range(start - count * step, start + count * step + step, step))
    return strikes


def build_option_symbol(expiry, strike, option_type):
    """Build Kotak trading symbol: NIFTY{YY}{MMM}{STRIKE}{CE/PE}"""
    exp_str = expiry.strftime('%y%b').upper()
    return f"NIFTY{exp_str}{strike}{option_type}"


def fetch_scrip_master(neo_api):
    """Download and parse scrip master."""
    raw = neo_api.scrip_master(exchange_segment="nse_fo")
    csv_url = raw if isinstance(raw, str) else (raw.get('data') if isinstance(raw, dict) else '')

    resp = requests.get(csv_url, timeout=30)
    df = pd.read_csv(io.StringIO(resp.text))
    return df


def get_quotes(neo_api, instruments):
    """Fetch quotes for list of instruments with tokens."""
    # Kotak quotes API expects instrument_tokens with exchange_segment and token
    tokens = []
    for inst in instruments:
        tokens.append({
            "exchange_segment": "nse_fo",
            "instrument_token": str(inst['token'])
        })

    try:
        response = neo_api.quotes(instrument_tokens=tokens, quote_type="all")
        return response
    except Exception as e:
        logger.error(f"Quotes fetch failed: {e}")
        return None


def parse_quotes_response(response):
    """Parse quotes response to extract premiums."""
    premiums = {}

    if not response:
        return premiums

    rows = response
    if isinstance(response, dict):
        rows = response.get('data') or response.get('quotes') or []
    if isinstance(rows, dict):
        rows = [rows]
    if not isinstance(rows, list):
        return premiums

    for row in rows:
        if not isinstance(row, dict):
            continue
        sym = str(row.get('trading_symbol') or row.get('ts') or row.get('symbol') or '')
        if not sym:
            continue

        # Get premium (mid of bid/ask or last price)
        bid = float(row.get('bid_price', row.get('bp', 0)) or 0)
        ask = float(row.get('ask_price', row.get('ap', 0)) or 0)
        last = float(row.get('last_price', row.get('lp', row.get('ltp', 0))) or 0)

        if bid > 0 and ask > 0:
            premium = (bid + ask) / 2
        elif last > 0:
            premium = last
        else:
            continue

        # Extract strike from symbol
        match = re.search(r'NIFTY.*?(\d{4,6})(?:CE|PE)$', sym.upper())
        if match:
            strike = int(match.group(1))
            premiums[strike] = {
                'premium': premium,
                'bid': bid,
                'ask': ask,
                'last': last,
                'symbol': sym,
            }

    return premiums


def get_spot_from_quotes(neo_api):
    """Get NIFTY spot from quotes."""
    try:
        instruments = [{"exchange_segment": "nse_fo", "symbol": "NIFTY"}]
        resp = neo_api.quotes(instrument_tokens=instruments, quote_type="ltp")
        if resp:
            rows = resp.get('data') or resp.get('quotes') or []
            for row in rows:
                ltp = float(row.get('last_price', row.get('lp', row.get('ltp', 0))) or 0)
                if ltp > 0:
                    return ltp
    except Exception as e:
        logger.warning(f"Could not fetch spot: {e}")
    return 24000


def get_kotak_margin(neo_api, leg):
    """Call Kotak's margin_required API."""
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
    logger.info("Kotak Current Expiry Margin Validation")
    logger.info("=" * 80)

    # 1. Initialize
    logger.info("Step 1: Initializing Kotak Neo API...")
    creds = get_kotak_credentials()
    neo_api = create_logged_in_neo_api(creds)
    logger.info("✓ Kotak Neo API initialized")

    # 2. Get current expiry
    main_expiry = get_current_expiry()
    logger.info(f"\nCurrent weekly expiry: {main_expiry}")

    # 3. Get spot
    spot = get_spot_from_quotes(neo_api)
    logger.info(f"Current NIFTY spot: {spot:.2f}")

    # 4. Fetch scrip master for tokens
    logger.info(f"\nStep 2: Fetching scrip master...")
    df = fetch_scrip_master(neo_api)
    logger.info(f"Scrip master loaded: {len(df)} rows")

    # 5. Find current expiry options in scrip master
    expiry_ts = int(pd.Timestamp(main_expiry).timestamp())
    expiry_end_ts = expiry_ts + 86399

    # Filter for current expiry NIFTY options - handle non-string columns
    df['pSymbol_str'] = df['pSymbol'].astype(str).str.upper()
    df['pExchSeg_str'] = df['pExchSeg'].astype(str)
    df['pInstType_str'] = df['pInstType'].astype(str)
    df['pOptionType_str'] = df['pOptionType'].astype(str)

    mask = (
        (df['pSymbol_str'].str.startswith('NIFTY')) &
        (df['pExchSeg_str'] == 'nse_fo') &
        (df['pInstType_str'] == 'OPTIDX') &
        (df['lExpiryDate '] >= expiry_ts) &
        (df['lExpiryDate '] <= expiry_end_ts)
    )
    expiry_df = df[mask].copy()
    logger.info(f"Found {len(expiry_df)} options for expiry {main_expiry}")

    if len(expiry_df) == 0:
        logger.error("No options found for current expiry in scrip master")
        return 1

    # 6. Get spot (approximate from near-ATM)
    spot = 24000  # fallback
    try:
        atm_df = expiry_df.copy()
        atm_df['dist'] = (atm_df['dStrikePrice;'] - 24000).abs()
        atm_row = atm_df.nsmallest(1, 'dist').iloc[0]
        # Could estimate spot from ATM premium but use 24000 for now
    except:
        pass

    logger.info(f"Using spot: {spot}")

    # 7. Find strikes in premium range 80-105 for PE (bullish)
    option_type = "PE"
    pe_df = expiry_df[expiry_df['pOptionType'] == option_type].copy()
    pe_df = pe_df[pe_df['dStrikePrice;'] < spot]  # OTM puts

    # 8. Get quotes for all strikes to find premiums
    pe_symbols = pe_df['pTrdSymbol'].tolist()
    pe_tokens = pe_df.set_index('pTrdSymbol')['pAssetCode'].to_dict()

    logger.info(f"\nStep 3: Fetching quotes for {len(pe_symbols)} PE options...")

    # Batch quotes (Kotak may have limits)
    batch_size = 50
    all_premiums = {}

    for i in range(0, len(pe_symbols), batch_size):
        batch = pe_symbols[i:i+batch_size]
        batch_tokens = [pe_tokens[s] for s in batch]
        instruments = [{"exchange_segment": "nse_fo", "instrument_token": str(t)} for t in batch_tokens]

        try:
            quote_resp = neo_api.quotes(instrument_tokens=instruments, quote_type="all")
            batch_premiums = {}
            if quote_resp:
                rows = quote_resp.get('data') or quote_resp.get('quotes') or []
                for row in rows:
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

                    match = re.search(r'NIFTY.*?(\d{4,6})(?:CE|PE)$', sym.upper())
                    if match:
                        strike = int(match.group(1))
                        batch_premiums[strike] = {
                            'premium': premium,
                            'bid': bid,
                            'ask': ask,
                            'last': last,
                            'symbol': sym,
                        }
            all_premiums.update(batch_premiums)
        except Exception as e:
            logger.warning(f"Batch quotes failed: {e}")

    logger.info(f"Got premiums for {len(all_premiums)} strikes")
    for k, v in sorted(all_premiums.items()):
        logger.info(f"  {k} {option_type}: ₹{v['premium']:.2f} (bid={v['bid']}, ask={v['ask']}) symbol={v['symbol']}")

    # 9. Find MAIN leg (premium 80-105, OTM)
    logger.info(f"\nStep 4: Finding MAIN leg (premium 80-105, OTM)...")
    main_leg = None
    for strike in sorted(all_premiums.keys()):
        p = all_premiums[strike]['premium']
        if 80 <= p <= 105:
            main_leg = {
                'strike': strike,
                'premium': p,
                'symbol': all_premiums[strike]['symbol'],
            }
            logger.info(f"  ✓ MAIN: {strike} {option_type} @ ₹{p:.2f}")
            break

    if not main_leg:
        logger.warning("No strike in premium range 80-105")
        for strike in sorted(all_premiums.keys()):
            p = all_premiums[strike]['premium']
            logger.info(f"  {strike} {option_type}: ₹{p:.2f}")
        return 1

    # 10. Find HEDGE leg (500 pts OTM)
    hedge_strike = main_leg['strike'] - 500
    hedge_strike = int(round(hedge_strike / 50) * 50)

    logger.info(f"\nStep 5: Finding HEDGE leg (500 pts OTM from {main_leg['strike']} -> {hedge_strike})")

    hedge_symbol = f"NIFTY{main_expiry.strftime('%y%b').upper()}{hedge_strike}{option_type}"

    # Check if hedge strike exists in premiums
    if hedge_strike in all_premiums:
        hedge_leg = {
            'strike': hedge_strike,
            'premium': all_premiums[hedge_strike]['premium'],
            'symbol': all_premiums[hedge_strike]['symbol'],
        }
        logger.info(f"  ✓ HEDGE: {hedge_strike} {option_type} @ ₹{hedge_leg['premium']:.2f}")
    else:
        logger.warning(f"Hedge strike {hedge_strike} not in premiums, trying nearby...")
        # Find nearest available
        available = [s for s in all_premiums.keys() if s < main_leg['strike']]
        if available:
            nearest = min(available, key=lambda x: abs(x - hedge_strike))
            hedge_strike = nearest
            hedge_leg = {
                'strike': hedge_strike,
                'premium': all_premiums[hedge_strike]['premium'],
                'symbol': all_premiums[hedge_strike]['symbol'],
            }
            logger.info(f"  ✓ HEDGE (nearest): {hedge_strike} {option_type} @ ₹{hedge_leg['premium']:.2f}")
        else:
            logger.error("No hedge leg available")
            return 1

    # 11. Get tokens and lot sizes
    main_row = df[df['pTrdSymbol'] == main_leg['symbol']]
    hedge_row = df[df['pTrdSymbol'] == hedge_leg['symbol']]

    main_token = str(int(main_row['pAssetCode'].iloc[0])) if len(main_row) else '0'
    hedge_token = str(int(hedge_row['pAssetCode'].iloc[0])) if len(hedge_row) else '0'

    main_lot = int(main_row['lLotSize'].iloc[0]) if len(main_row) else 75
    hedge_lot = int(hedge_row['lLotSize'].iloc[0]) if len(hedge_row) else 75

    logger.info(f"\nTokens & Lot Sizes:")
    logger.info(f"  MAIN: token={main_token}, lot={main_lot}")
    logger.info(f"  HEDGE: token={hedge_token}, lot={hedge_lot}")

    if not main_token or not hedge_token:
        logger.error("Could not find tokens in scrip master")
        return 1

    # 12. Calculate margins
    logger.info(f"\n{'='*60}")
    logger.info("MARGIN CALCULATION")
    logger.info(f"{'='*60}")

    def get_kotak_margin(neo_api, leg):
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
                total = float(resp.get('totalMargin') or resp.get('total_margin') or resp.get('margin') or 0)
                span = float(resp.get('spanMargin') or resp.get('span_margin') or 0)
                exposure = float(resp.get('exposureMargin') or resp.get('exposure_margin') or 0)
                return {'total': total, 'span': span, 'exposure': exposure, 'raw': resp}
            else:
                return {'error': resp}
        except Exception as e:
            return {'error': str(e)}

    # MAIN leg
    main_margin = get_kotak_margin(neo_api, {
        'premium': main_leg['premium'],
        'quantity': main_lot,
        'instrument_token': main_token,
        'transaction_type': 'S',  # SELL
    })

    # HEDGE leg
    hedge_margin = get_kotak_margin(neo_api, {
        'premium': hedge_leg['premium'],
        'quantity': hedge_lot,
        'instrument_token': hedge_token,
        'transaction_type': 'B',  # BUY
    })

    # 13. Display results
    logger.info(f"\n{'='*60}")
    logger.info("RESULTS")
    logger.info(f"{'='*60}")

    logger.info(f"\nSTRUCTURE:")
    logger.info(f"  MAIN (SELL):  {main_leg['strike']} {option_type} @ ₹{main_leg['premium']:.2f} | token={main_token} | lot={main_lot}")
    logger.info(f"  HEDGE (BUY):  {hedge_leg['strike']} {option_type} @ ₹{hedge_leg['premium']:.2f} | token={hedge_token} | lot={hedge_lot}")

    if 'error' in main_margin:
        logger.error(f"MAIN margin error: {main_margin['error']}")
    else:
        logger.info(f"\nMAIN MARGIN (SELL):")
        logger.info(f"  Total Margin:   ₹{main_margin['total']:,.2f}")
        logger.info(f"  SPAN Margin:    ₹{main_margin['span']:,.2f}")
        logger.info(f"  Exposure Margin: ₹{main_margin['exposure']:,.2f}")

    if 'error' in hedge_margin:
        logger.error(f"HEDGE margin error: {hedge_margin['error']}")
    else:
        logger.info(f"\nHEDGE MARGIN (BUY):")
        logger.info(f"  Total Margin:   ₹{hedge_margin['total']:,.2f}")
        logger.info(f"  SPAN Margin:    ₹{hedge_margin['span']:,.2f}")
        logger.info(f"  Exposure Margin: ₹{hedge_margin['exposure']:,.2f}")

    # Structure calculation
    if 'error' not in main_margin and 'error' not in hedge_margin:
        gross_total = main_margin['total'] + hedge_margin['total']
        gross_span = main_margin['span'] + hedge_margin['span']
        gross_exposure = main_margin['exposure'] + hedge_margin['exposure']

        short_span = main_margin['span']
        hedge_benefit = short_span * 0.70
        final_span = max(gross_span - hedge_benefit, short_span * 0.1)
        final_exposure = max(gross_exposure - hedge_benefit * 0.5, gross_exposure * 0.2)
        final_total = final_span + final_exposure

        logger.info(f"\n{'='*60}")
        logger.info("STRUCTURE MARGIN")
        logger.info(f"{'='*60}")
        logger.info(f"Gross Total Margin:   ₹{gross_total:,.2f}")
        logger.info(f"  Gross SPAN:         ₹{gross_span:,.2f}")
        logger.info(f"  Gross Exposure:     ₹{gross_exposure:,.2f}")
        logger.info(f"Hedge Benefit (est.): ₹{hedge_benefit:,.2f}")
        logger.info(f"Final Margin:         ₹{final_total:,.2f}")
        logger.info(f"  Final SPAN:         ₹{final_span:,.2f}")
        logger.info(f"  Final Exposure:     ₹{final_exposure:,.2f}")

        # TP/SL levels
        capital = final_total
        sl_amt = capital * 0.035
        tp_amt = capital * 0.037
        logger.info(f"\nTP/SL LEVELS (on ₹{capital:,.2f} capital):")
        logger.info(f"  Stop Loss (3.5%):  ₹{sl_amt:,.2f}")
        logger.info(f"  Take Profit (3.7%): ₹{tp_amt:,.2f}")

        logger.info(f"\n{'='*60}")
        logger.info("COMPARISON WITH KOTAK STRATEGY BUILDER")
        logger.info(f"{'='*60}")
        logger.info(f"Target (from screenshot):")
        logger.info(f"  Gross Margin:       ₹162,186.51")
        logger.info(f"  Hedge Benefit:      ₹102,299.60")
        logger.info(f"  Final Margin:       ₹59,886.91")

    return 0


if __name__ == "__main__":
    sys.exit(main())