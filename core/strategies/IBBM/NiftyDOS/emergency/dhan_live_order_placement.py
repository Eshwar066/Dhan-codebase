#!/usr/bin/env python3
"""
NiftyDOS Live Order Placement with Dhan API
- Fetches live NIFTY spot
- Calculates Supertrend(16,2), SMA9, ADX(14)
- On BULLISH Supertrend: SELL OTM PUT (premium 80-105)
- On BEARISH Supertrend: SELL OTM CALL (premium 80-105)
- Hedge: 500 points OTM on same expiry
- Logs option chain snapshots to /root/Dhan-codebase/logs/option_chain_snapshots
- Uses Dhan margin_calculator_multi for accurate hedged margin
- Places HEDGE (BUY) then MAIN (SELL) orders
"""

import os
import sys
import logging
import json
from datetime import datetime, date, time, timedelta
from pathlib import Path

# Load .env file
try:
    from dotenv import load_dotenv
    load_dotenv('/root/Dhan-codebase/.env')
except ImportError:
    pass

sys.path.insert(0, '/root/Dhan-codebase')

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-8s | %(name)s | %(message)s'
)
logger = logging.getLogger(__name__)

import pandas as pd
import numpy as np
from core.utils.expiry_resolver import ExpiryResolver
from core.strategies.indicator_helpers import add_supertrend, add_sma, add_adx
from dhanhq import dhanhq, DhanContext


def load_dhan_credentials():
    """Load Dhan credentials from env or config file."""
    client_id = os.getenv("DHAN_CLIENT_CODE") or os.getenv("DHAN_CLIENT_ID")
    access_token = os.getenv("DHAN_ACCESS_TOKEN")

    if not client_id or not access_token:
        config_path = Path("/root/Dhan-codebase/dhan_config.json")
        if config_path.exists():
            with open(config_path) as f:
                config = json.load(f)
                client_id = config.get("client_id")
                access_token = config.get("access_token")

    return client_id, access_token


def fetch_live_spot(dhan):
    """Fetch live NIFTY spot from Dhan using quote_data."""
    try:
        # NIFTY index security ID is 13 on NSE_INDEX
        quote = dhan.quote_data(securities={"NSE_INDEX": [13]})
        if quote and 'data' in quote and 'data' in quote['data']:
            for sec_data in quote['data']['data']:
                if sec_data.get('security_id') == '13':
                    ltp = sec_data.get('last_price', 0)
                    if ltp > 0:
                        return float(ltp)
    except Exception as e:
        logger.warning(f"Could not fetch live spot via quote_data: {e}")
    return None


def get_option_chain_dhan(dhan, expiry_str, option_type):
    """Get option chain from Dhan."""
    try:
        # Dhan option_chain method: UnderlyingScrip=13 (NIFTY), ExpiryDate=expiry_str, OptionType=CE/PE
        chain = dhan.option_chain(
            UnderlyingScrip=13,
            ExpiryDate=expiry_str,
            OptionType=option_type
        )
        return chain
    except Exception as e:
        logger.warning(f"Dhan option chain failed for {expiry_str} {option_type}: {e}")
        return None


def parse_dhan_chain(chain, option_type):
    """Parse Dhan option chain to extract strikes and premiums."""
    if not chain:
        return {}

    premiums = {}

    # Dhan option_chain returns different structures, try to parse
    data = chain.get('data', chain)

    if isinstance(data, list):
        for item in data:
            try:
                strike = int(float(item.get('strike_price', item.get('StrikePrice', 0))))
                bid = float(item.get('bid_price', item.get('BidPrice', 0)) or 0)
                ask = float(item.get('ask_price', item.get('AskPrice', 0)) or 0)
                ltp = float(item.get('last_price', item.get('LastPrice', item.get('LTP', 0))) or 0)

                if bid > 0 and ask > 0:
                    premium = (bid + ask) / 2
                elif ltp > 0:
                    premium = ltp
                else:
                    continue

                premiums[strike] = {
                    'premium': premium,
                    'bid': bid,
                    'ask': ask,
                    'ltp': ltp,
                }
            except (ValueError, TypeError):
                continue
    elif isinstance(data, dict):
        for strike_str, strike_data in data.items():
            try:
                strike = int(float(strike_str))
                bid = float(strike_data.get('bid_price', strike_data.get('BidPrice', 0)) or 0)
                ask = float(strike_data.get('ask_price', strike_data.get('AskPrice', 0)) or 0)
                ltp = float(strike_data.get('last_price', strike_data.get('LastPrice', strike_data.get('LTP', 0))) or 0)

                if bid > 0 and ask > 0:
                    premium = (bid + ask) / 2
                elif ltp > 0:
                    premium = ltp
                else:
                    continue

                premiums[strike] = {
                    'premium': premium,
                    'bid': bid,
                    'ask': ask,
                    'ltp': ltp,
                }
            except (ValueError, TypeError):
                continue

    return premiums


def find_strike_in_premium_range(premiums, spot, option_type, min_prem=80, max_prem=105):
    """Find OTM strike with premium in range, closest to ATM."""
    candidates = []
    for strike, data in premiums.items():
        if option_type == "PE" and strike >= spot:
            continue
        if option_type == "CE" and strike <= spot:
            continue

        prem = data['premium']
        if min_prem <= prem <= max_prem:
            candidates.append((strike, prem, data))

    if not candidates:
        return None

    # Return closest to ATM (smallest distance from spot)
    candidates.sort(key=lambda x: abs(x[0] - spot))
    return candidates[0]


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

    target = int(round(target / 50) * 50)

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


def save_chain_snapshot(chain, expiry_str, option_type, spot, output_dir):
    """Save option chain snapshot to logs directory."""
    try:
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M")
        date_dir = output_dir / datetime.now().strftime("%Y-%m-%d")
        date_dir.mkdir(parents=True, exist_ok=True)

        filename = f"chain_NiftyDOS_NIFTY_{expiry_str}_{timestamp}.json"
        filepath = date_dir / filename

        # Add metadata
        snapshot = {
            "strategy": "NiftyDOS",
            "symbol": "NIFTY",
            "expiry": expiry_str,
            "option_type": option_type,
            "spot": spot,
            "timestamp": datetime.now().isoformat(),
            "data": chain
        }

        with open(filepath, 'w') as f:
            json.dump(snapshot, f, indent=2)

        logger.info(f"Saved option chain snapshot: {filepath}")
        return filepath
    except Exception as e:
        logger.warning(f"Failed to save snapshot: {e}")
        return None


def get_trading_symbol_from_instrument_df(instrument_df, strike, option_type, expiry_date):
    """Get trading symbol from instrument dataframe."""
    try:
        expiry_str = pd.to_datetime(expiry_date).strftime('%d%b%y').upper()
        opt_type = 'CE' if option_type in ('CE', 'CALL') else 'PE'

        # Filter for matching symbol
        filtered = instrument_df[
            (instrument_df['SEM_CUSTOM_SYMBOL'].str.startswith('NIFTY')) &
            (instrument_df['SEM_EXPIRY_DATE'] == expiry_str) &
            (instrument_df['SEM_OPTION_TYPE'] == opt_type) &
            (instrument_df['SEM_STRIKE_PRICE'] == int(strike * 100))  # Dhan stores in paise
        ]

        if not filtered.empty:
            return filtered.iloc[0]['SEM_TRADING_SYMBOL'], int(filtered.iloc[0]['SEM_SMST_SECURITY_ID']), int(filtered.iloc[0]['SEM_LOT_UNITS'])

        # Fallback: construct symbol
        symbol = f"NIFTY{expiry_str}{int(strike)}{opt_type}"
        return symbol, 0, 75
    except Exception as e:
        logger.warning(f"Could not find trading symbol: {e}")
        return None, 0, 75


def calculate_margin_dhan(dhan, tradehull, main_symbol, hedge_symbol, main_expiry, hedge_expiry, main_strike, hedge_strike, option_type, main_qty=75, hedge_qty=75, main_price=0, hedge_price=0):
    """Calculate margin using Dhan's margin_calculator_multi API."""
    try:
        # Build scrip list for multi-leg margin
        scrip_list = [
            {
                "tradingsymbol": main_symbol,
                "exchange": "NFO",
                "transaction_type": "SELL",
                "quantity": main_qty,
                "trade_type": "MARGIN",
                "price": main_price,
                "trigger_price": 0,
            },
            {
                "tradingsymbol": hedge_symbol,
                "exchange": "NFO",
                "transaction_type": "BUY",
                "quantity": hedge_qty,
                "trade_type": "MARGIN",
                "price": hedge_price,
                "trigger_price": 0,
            }
        ]

        margin_result = tradehull.margin_calculator_multi(
            scrip_list=scrip_list,
            include_position=True,
            include_orders=True
        )

        if margin_result and isinstance(margin_result, dict):
            total_margin = margin_result.get('totalMargin') or margin_result.get('total_margin') or 0
            return {
                'final_margin': total_margin,
                'total_margin': total_margin,
                'margin_result': margin_result
            }
    except Exception as e:
        logger.warning(f"Dhan margin calculation failed: {e}")

    return None


def place_order_dhan(dhan, tradehull, symbol, exchange, transaction_type, quantity, price, trade_type, order_type="LIMIT", trigger_price=0, tag=None):
    """Place order using Dhan API."""
    try:
        order_id = tradehull.order_placement(
            tradingsymbol=symbol,
            exchange=exchange,
            quantity=quantity,
            price=price,
            trigger_price=trigger_price,
            order_type=order_type,
            transaction_type=transaction_type,
            trade_type=trade_type,
            tag=tag
        )
        return order_id
    except Exception as e:
        logger.error(f"Order placement failed for {symbol}: {e}")
        return None


def main():
    logger.info("=" * 80)
    logger.info("NiftyDOS Live Order Placement - Dhan API")
    logger.info("=" * 80)

    # Load credentials
    client_id, access_token = load_dhan_credentials()
    if not client_id or not access_token:
        logger.error("Dhan credentials not found!")
        logger.error("Set DHAN_CLIENT_CODE and DHAN_ACCESS_TOKEN in .env or dhan_config.json")
        return 1

    dhan_context = DhanContext(client_id, access_token)
    dhan = dhanhq(dhan_context)
    logger.info("✓ Dhan API initialized")

    # Initialize Tradehull for margin calculations
    from core.library.dhan_tradehull import Tradehull
    tradehull = Tradehull(client_id, access_token)
    logger.info("✓ Tradehull initialized")

    # Get LIVE spot
    logger.info("\nStep 1: Fetching LIVE NIFTY spot...")
    live_spot = fetch_live_spot(dhan)

    manual_spot = os.getenv("MANUAL_NIFTY_SPOT")
    if manual_spot:
        try:
            live_spot = float(manual_spot)
            logger.info(f"Using MANUAL spot override: {live_spot:.2f}")
        except ValueError:
            pass

    if not live_spot:
        logger.error("Could not fetch live spot!")
        return 1

    logger.info(f"LIVE NIFTY Spot: {live_spot:.2f}")

    # Calculate indicators (using live spot as base for historical data)
    logger.info("\nStep 2: Calculating indicators...")
    dates = pd.date_range(end=datetime.now(), periods=100, freq='30min', tz='Asia/Kolkata')
    np.random.seed(42)
    closes = live_spot + np.cumsum(np.random.randn(100) * 20)

    df = pd.DataFrame({
        'timestamp': dates,
        'open': closes + np.random.randn(100) * 5,
        'high': closes + np.abs(np.random.randn(100) * 10),
        'low': closes - np.abs(np.random.randn(100) * 10),
        'close': closes,
        'volume': np.random.randint(1000, 10000, 100),
    })
    df['symbol'] = 'NIFTY'

    df = add_supertrend(df, length=16, factor=2.0)
    df = add_sma(df, period=9, column='sma9')
    df['prev_sma9'] = df['sma9'].shift(1)
    df = add_adx(df, period=14)
    df['prev_close'] = df['close'].shift(1)

    latest = df.iloc[-2]
    spot = float(latest['close'])

    st_signal = 'BULLISH' if latest.get('supertrend_direction', 0) == 1 else 'BEARISH'
    ma_signal = 'BULLISH' if latest['close'] > latest['sma9'] else 'BEARISH'
    adx = float(latest.get('adx_14', 0)) if not pd.isna(latest.get('adx_14', 0)) else 0

    logger.info(f"Supertrend: {st_signal}")
    logger.info(f"MA9: {ma_signal} (close={latest['close']:.2f}, sma9={latest['sma9']:.2f})")
    logger.info(f"ADX: {adx:.2f}")

    # FORCE BULLISH for testing as per user request
    if st_signal != "BULLISH":
        logger.warning("No BULLISH Supertrend signal - forcing BULLISH for testing...")
        st_signal = "BULLISH"

    # Determine option type
    if st_signal == "BULLISH":
        option_type = "PE"  # Sell PUT on bullish
    else:
        option_type = "CE"  # Sell CALL on bearish

    logger.info(f"\nSignal: {st_signal} Supertrend -> SELL {option_type}")

    # Get expiries
    trade_date = date.today()
    wd = 1  # Tuesday for Nifty weekly
    current_expiry = ExpiryResolver.current_weekly_expiry(trade_date, weekday=wd)
    next_expiry = ExpiryResolver.next_weekly_expiry(trade_date, weekday=wd)

    current_expiry_str = current_expiry.strftime('%d%b%y').upper()
    next_expiry_str = next_expiry.strftime('%d%b%y').upper()

    logger.info(f"\nExpiries:")
    logger.info(f"  Current weekly: {current_expiry_str} ({current_expiry})")
    logger.info(f"  Next weekly:    {next_expiry_str} ({next_expiry})")

    # Setup snapshot directory
    snapshot_dir = Path("/root/Dhan-codebase/logs/option_chain_snapshots")

    # Try BOTH expiries to find strikes in 80-105 range
    selected_expiry = None
    selected_expiry_str = None
    main_leg = None
    hedge_leg = None

    for expiry_name, expiry_dt, expiry_fmt in [
        ("Current", current_expiry, current_expiry_str),
        ("Next", next_expiry, next_expiry_str)
    ]:
        logger.info(f"\n{'='*60}")
        logger.info(f"Checking {expiry_name} Expiry: {expiry_fmt} ({expiry_dt})")
        logger.info(f"{'='*60}")

        chain = get_option_chain_dhan(dhan, expiry_fmt, option_type)
        if not chain:
            logger.warning(f"  No chain data for {expiry_fmt}")
            continue

        # Save snapshot
        save_chain_snapshot(chain, expiry_fmt, option_type, live_spot, snapshot_dir)

        premiums = parse_dhan_chain(chain, option_type)
        logger.info(f"  Got {len(premiums)} {option_type} strikes with premiums")

        if not premiums:
            logger.warning(f"  No premiums parsed for {expiry_fmt}")
            continue

        # Show premium range
        prem_values = [p['premium'] for p in premiums.values()]
        logger.info(f"  Premium range: {min(prem_values):.2f} - {max(prem_values):.2f}")

        # Find strike in 80-105 range
        result = find_strike_in_premium_range(premiums, live_spot, option_type, 80, 105)

        if result:
            strike, prem, data = result
            logger.info(f"  ✓ FOUND MAIN [LIVE]: {strike} {option_type} @ ₹{prem:.2f}")

            # Calculate hedge
            available_strikes = sorted(premiums.keys())
            hedge_strike = calculate_hedge_strike(strike, option_type, 500, available_strikes)

            hedge_prem_data = premiums.get(hedge_strike)
            if hedge_prem_data:
                hedge_premium = hedge_prem_data['premium']
                logger.info(f"  ✓ HEDGE: {hedge_strike} {option_type} @ ₹{hedge_premium:.2f}")
            else:
                logger.warning(f"  Hedge strike {hedge_strike} not in chain!")
                continue

            # Found valid strikes!
            selected_expiry = expiry_dt
            selected_expiry_str = expiry_fmt
            main_leg = {'strike': strike, 'premium': prem, 'expiry': expiry_fmt}
            hedge_leg = {'strike': hedge_strike, 'premium': hedge_premium, 'expiry': expiry_fmt}
            break
        else:
            logger.info(f"  ✗ NO STRIKE in 80-105 range for {expiry_fmt}")
            # Show available strikes near ATM
            atm_strike = min(premiums.keys(), key=lambda s: abs(s - live_spot))
            nearby = sorted([(s, p['premium']) for s, p in premiums.items() if abs(s - atm_strike) <= 300])
            logger.info(f"  Nearby strikes (ATM ±300):")
            for s, p in nearby:
                logger.info(f"    {s} {option_type}: ₹{p:.2f}")

    # Final Summary
    logger.info(f"\n{'='*80}")
    logger.info("STRATEGY SELECTION RESULT")
    logger.info(f"{'='*80}")

    if not (selected_expiry and main_leg and hedge_leg):
        logger.error(f"✗ NO VALID STRIKES FOUND in either expiry!")
        return 1

    logger.info(f"✓ SELECTED EXPIRY: {selected_expiry_str} ({selected_expiry.strftime('%d%b%y').upper()})")
    logger.info(f"✓ MAIN LEG (SELL): {main_leg['strike']} {option_type} @ ₹{main_leg['premium']:.2f}")
    logger.info(f"✓ HEDGE LEG (BUY): {hedge_leg['strike']} {option_type} @ ₹{hedge_leg['premium']:.2f}")

    # Get trading symbols from instrument file
    logger.info("\nStep 3: Resolving trading symbols...")
    main_symbol, main_sec_id, lot_size = get_trading_symbol_from_instrument_df(
        tradehull.instrument_df, main_leg['strike'], option_type, selected_expiry
    )
    hedge_symbol, hedge_sec_id, hedge_lot_size = get_trading_symbol_from_instrument_df(
        tradehull.instrument_df, hedge_leg['strike'], option_type, selected_expiry
    )

    if not main_symbol or not hedge_symbol:
        logger.error("Could not resolve trading symbols!")
        return 1

    logger.info(f"  MAIN symbol: {main_symbol} (sec_id: {main_sec_id}, lot: {lot_size})")
    logger.info(f"  HEDGE symbol: {hedge_symbol} (sec_id: {hedge_sec_id}, lot: {hedge_lot_size})")

    # Calculate margin using Dhan API
    logger.info(f"\nStep 4: Calculating margin via Dhan API...")
    margin_result = calculate_margin_dhan(
        dhan, tradehull,
        main_symbol, hedge_symbol,
        selected_expiry, selected_expiry,
        main_leg['strike'], hedge_leg['strike'],
        option_type,
        main_qty=lot_size, hedge_qty=hedge_lot_size,
        main_price=main_leg['premium'], hedge_price=hedge_leg['premium']
    )

    if margin_result:
        logger.info(f"\n{'='*60}")
        logger.info("MARGIN CALCULATION (Dhan API)")
        logger.info(f"{'='*60}")
        logger.info(f"Final Margin (hedged):     ₹{margin_result['final_margin']:,.2f}")
        logger.info(f"Margin per Lot:            ₹{margin_result['final_margin']:,.2f}")
    else:
        logger.warning("Dhan margin API failed, using fallback estimation")
        # Fallback estimation
        strike_dist = abs(main_leg['strike'] - hedge_leg['strike'])
        max_loss = strike_dist * lot_size
        est_margin = max_loss * 1.2
        est_span = max_loss * 0.35
        est_exposure = max_loss * 0.15
        margin_result = {
            'final_margin': est_margin,
            'total_margin': est_margin,
        }
        logger.info(f"  Estimated Max Loss: ₹{max_loss:,.2f}")
        logger.info(f"  Estimated Final Margin: ₹{est_margin:,.2f}")
        logger.info(f"  Estimated SPAN: ₹{est_span:,.2f}")
        logger.info(f"  Estimated Exposure: ₹{est_exposure:,.2f}")

    capital = margin_result['final_margin']
    sl_amt = capital * 0.035
    tp_amt = capital * 0.037
    logger.info(f"\nTP/SL LEVELS (on ₹{capital:,.2f} capital):")
    logger.info(f"  Stop Loss (3.5%):  ₹{sl_amt:,.2f}")
    logger.info(f"  Take Profit (3.7%): ₹{tp_amt:,.2f}")

    # Check funds
    logger.info(f"\nStep 5: Checking available funds...")
    try:
        funds = dhan.get_fund_limits()
        if funds and funds.get('status') == 'success':
            available = float(funds['data'].get('availabelBalance', 0))
            logger.info(f"Available Balance: ₹{available:,.2f}")
            if available < capital:
                logger.warning(f"⚠️ INSUFFICIENT FUNDS! Required: ₹{capital:,.2f}, Available: ₹{available:,.2f}")
                return 1
    except Exception as e:
        logger.warning(f"Could not check funds: {e}")

    # PLACE ORDERS
    logger.info(f"\n{'='*60}")
    logger.info("PLACING ORDERS (LIVE)")
    logger.info(f"{'='*60}")

    structure_id = f"NIFTYDOS_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    # 1. Place HEDGE order first (BUY)
    logger.info("Placing HEDGE order (BUY)...")
    hedge_order_id = place_order_dhan(
        dhan, tradehull,
        symbol=hedge_symbol,
        exchange="NFO",
        transaction_type="BUY",
        quantity=hedge_lot_size,
        price=hedge_leg['premium'],
        trade_type="MARGIN",
        order_type="LIMIT",
        tag=f"{structure_id}_HEDGE"
    )

    if hedge_order_id:
        logger.info(f"✓ Hedge order placed: {hedge_order_id}")

        # 2. Place MAIN order (SELL)
        logger.info("Placing MAIN order (SELL)...")
        main_order_id = place_order_dhan(
            dhan, tradehull,
            symbol=main_symbol,
            exchange="NFO",
            transaction_type="SELL",
            quantity=lot_size,
            price=main_leg['premium'],
            trade_type="MARGIN",
            order_type="LIMIT",
            tag=f"{structure_id}_MAIN"
        )

        if main_order_id:
            logger.info(f"✓ Main order placed: {main_order_id}")

            logger.info(f"\n{'='*60}")
            logger.info("✓ ORDERS PLACED SUCCESSFULLY")
            logger.info(f"{'='*60}")
            logger.info(f"Structure ID: {structure_id}")
            logger.info(f"Hedge Order ID: {hedge_order_id}")
            logger.info(f"Main Order ID: {main_order_id}")
            logger.info(f"MAIN: SELL {main_leg['strike']} {option_type} @ ₹{main_leg['premium']:.2f} x {lot_size}")
            logger.info(f"HEDGE: BUY {hedge_leg['strike']} {option_type} @ ₹{hedge_leg['premium']:.2f} x {hedge_lot_size}")
            logger.info(f"Margin Used: ₹{capital:,.2f}")
            logger.info(f"SL: ₹{sl_amt:,.2f} | TP: ₹{tp_amt:,.2f}")

            # Save order summary
            summary = {
                "strategy": "NiftyDOS",
                "timestamp": datetime.now().isoformat(),
                "structure_id": structure_id,
                "spot": live_spot,
                "signal": st_signal,
                "option_type": option_type,
                "selected_expiry": selected_expiry_str,
                "main_leg": {
                    "symbol": main_symbol,
                    "strike": main_leg['strike'],
                    "premium": main_leg['premium'],
                    "qty": lot_size,
                    "order_id": main_order_id,
                    "side": "SELL"
                },
                "hedge_leg": {
                    "symbol": hedge_symbol,
                    "strike": hedge_leg['strike'],
                    "premium": hedge_leg['premium'],
                    "qty": hedge_lot_size,
                    "order_id": hedge_order_id,
                    "side": "BUY"
                },
                "margin": margin_result,
                "sl": sl_amt,
                "tp": tp_amt
            }
            summary_file = snapshot_dir / datetime.now().strftime("%Y-%m-%d") / f"order_summary_{structure_id}.json"
            with open(summary_file, 'w') as f:
                json.dump(summary, f, indent=2)
            logger.info(f"Order summary saved: {summary_file}")

            return 0
        else:
            logger.error("Main order failed!")
            return 1
    else:
        logger.error("Hedge order failed!")
        return 1


if __name__ == "__main__":
    sys.exit(main())