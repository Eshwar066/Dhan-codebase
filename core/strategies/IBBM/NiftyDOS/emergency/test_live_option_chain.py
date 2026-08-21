#!/usr/bin/env python3
import os
import sys
import pandas as pd

sys.path.insert(0, "/root/Dhan-codebase")

from core.utils.kotak_env import KotakCredentials, create_logged_in_neo_api
from core.data.sources.kotak_source import KotakSource
from core.data.datalayer.kotak_data_provider import KotakDataProvider
from core.utils.instruments.instrument_store import InstrumentStore

creds = KotakCredentials(
    consumer_key=os.getenv("KOTAK_CONSUMER_KEY"),
    consumer_secret=os.getenv("KOTAK_CONSUMER_SECRET"),
    mobile=os.getenv("KOTAK_MOBILE"),
    ucc=os.getenv("KOTAK_UCC"),
    mpin=os.getenv("KOTAK_MPIN"),
    totp_secret=os.getenv("KOTAK_TOTP_SECRET"),
    environment=os.getenv("KOTAK_ENVIRONMENT", "prod"),
)
neo_api = create_logged_in_neo_api(creds)
kotak_source = KotakSource(neo_api=neo_api)

# Create instrument store with the CSV path
csv_path = "/root/Dhan-codebase/kotak_instruments_latest.csv"
instrument_store = InstrumentStore(csv_path=csv_path, broker="KOTAK", kotak_source=kotak_source)

provider = KotakDataProvider(kotak_source)
provider.bind_instrument_store(instrument_store)

from datetime import date
from core.utils.expiry_resolver import ExpiryResolver
expiry = ExpiryResolver.current_weekly_expiry(date.today(), weekday=1)
print(f"Testing with expiry: {expiry}")

result = provider.get_live_option_chain(
    symbol="NIFTY",
    exchange="NFO",
    expiry_index=0,
    strikes_around_atm=60,
    expiry_flag="WEEK",
    spot_price=24000,
)

print(f"Result: {result is not None}")
if result:
    print(f"  Symbol: {result.get('symbol')}")
    print(f"  Expiry: {result.get('expiry')}")
    print(f"  ATM Strike: {result.get('atm_strike')}")
    chain = result.get("chain")
    if hasattr(chain, 'shape'):
        print(f"  Chain shape: {chain.shape}")
    else:
        print(f"  Chain: {chain}")