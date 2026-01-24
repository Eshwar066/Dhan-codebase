"""
Constants for Dhan integration.
Single source: values used by api, broker, and strategies.
"""

import pandas as pd
from typing import Dict

# --- Interval (seconds) ---
INTERVAL_PARAMS = {
    "minute": 60,
    "2minute": 120,
    "3minute": 180,
    "4minute": 240,
    "5minute": 300,
    "day": 86400,
    "10minute": 600,
    "15minute": 900,
    "30minute": 1800,
    "60minute": 3600,
}

# --- Index / Underlying mapping ---
INDEX_UNDERLYING = {
    "NIFTY 50": "NIFTY",
    "NIFTY BANK": "BANKNIFTY",
    "NIFTY FIN SERVICE": "FINNIFTY",
    "NIFTY MID SELECT": "MIDCPNIFTY",
}

# --- Segment (Dhan) ---
SEGMENT_DICT = {
    "NSECM": 1,
    "NSEFO": 2,
    "NSECD": 3,
    "BSECM": 11,
    "BSEFO": 12,
    "MCXFO": 51,
}

# --- Index step for strike ---
INDEX_STEP_DICT = {
    "MIDCPNIFTY": 25,
    "SENSEX": 100,
    "BANKEX": 100,
    "NIFTY": 50,
    "NIFTY 50": 50,
    "NIFTY BANK": 100,
    "BANKNIFTY": 100,
    "NIFTY FIN SERVICE": 50,
    "FINNIFTY": 50,
}

# --- Index token (Dhan) ---
TOKEN_DICT = {
    "NIFTY": {"token": 26000, "exchange": "NSECM"},
    "NIFTY 50": {"token": 26000, "exchange": "NSECM"},
    "BANKNIFTY": {"token": 26001, "exchange": "NSECM"},
    "NIFTY BANK": {"token": 26001, "exchange": "NSECM"},
    "FINNIFTY": {"token": 26034, "exchange": "NSECM"},
    "NIFTY FIN SERVICE": {"token": 26034, "exchange": "NSECM"},
    "MIDCPNIFTY": {"token": 26121, "exchange": "NSECM"},
    "NIFTY MID SELECT": {"token": 26121, "exchange": "NSECM"},
    "SENSEX": {"token": 26065, "exchange": "BSECM"},
    "BANKEX": {"token": 26118, "exchange": "BSECM"},
}

# --- Dhan intervals (API) ---
INTERVALS_DICT = {
    "minute": 3,
    "2minute": 4,
    "3minute": 4,
    "5minute": 5,
    "10minute": 10,
    "15minute": 15,
    "30minute": 25,
    "60minute": 40,
    "day": 80,
}

# --- Step value (lot / strike) per symbol. From NSE; used when Dhan/NSE master not available. ---
def get_step_value_dict() -> Dict[str, float]:
    return {
        "NIFTY": 50, "NIFTY 50": 50, "NIFTY BANK": 100, "BANKNIFTY": 100,
        "NIFTY FIN SERVICE": 50, "FINNIFTY": 50,
        "AARTIIND": 5, "ABB": 50, "ABBOTINDIA": 250, "ACC": 20, "ADANIENT": 50,
        "ADANIPORTS": 10, "ALKEM": 20, "AMBUJACEM": 10, "APOLLOHOSP": 50,
        "APOLLOTYRE": 5, "ASHOKLEY": 1, "ASIANPAINT": 20, "ASTRAL": 20,
        "ATUL": 50, "AUBANK": 10, "AUROPHARMA": 10, "AXISBANK": 10,
        "BAJAJ-AUTO": 50, "BAJAJFINSV": 20, "BAJFINANCE": 50, "BALKRISIND": 20,
        "BALRAMCHIN": 5, "BATAINDIA": 10, "BEL": 1, "BERGEPAINT": 5,
        "BHARATFORG": 10, "BHARTIARTL": 10, "BHEL": 1, "BOSCHLTD": 100,
        "BPCL": 5, "BRITANNIA": 50, "BSOFT": 10, "CANBK": 5, "CANFINHOME": 10,
        "CHOLAFIN": 10, "CIPLA": 10, "COFORGE": 100, "COLPAL": 10,
        "CONCOR": 10, "COROMANDEL": 10, "CUB": 1, "CUMMINSIND": 20,
        "DABUR": 5, "DALBHARAT": 20, "DEEPAKNTR": 20, "DELTACORP": 5,
        "DIVISLAB": 50, "DIXON": 50, "DLF": 5, "DRREDDY": 50, "EICHERMOT": 50,
        "ESCORTS": 20, "FEDERALBNK": 1, "GAIL": 1, "GLENMARK": 10,
        "GMRINFRA": 1, "GNFC": 10, "GODREJCP": 10, "GODREJPROP": 20,
        "GRASIM": 20, "GUJGASLTD": 5, "HAL": 20, "HAVELLS": 10, "HCLTECH": 10,
        "HDFCAMC": 20, "HDFCBANK": 10, "HDFCLIFE": 5, "HEROMOTOCO": 20,
        "HINDALCO": 5, "HINDCOPPER": 2.5, "HINDUNILVR": 20, "ICICIBANK": 10,
        "ICICIGI": 10, "ICICIPRULI": 5, "IDEA": 1, "IDFC": 1, "IDFCFIRSTB": 1,
        "IEX": 1, "IGL": 5, "INDHOTEL": 5, "INDIAMART": 50, "INDIGO": 20,
        "INDUSINDBK": 20, "INFY": 10, "IOC": 1, "IPCALAB": 10, "IRCTC": 10,
        "ITC": 5, "JINDALSTEL": 10, "JKCEMENT": 50, "JSWSTEEL": 10,
        "JUBLFOOD": 5, "KOTAKBANK": 20, "L&TFH": 1, "LALPATHLAB": 20,
        "LAURUSLABS": 5, "LICHSGFIN": 5, "LT": 20, "LTIM": 50, "LTTS": 50,
        "LUPIN": 10, "M&M": 10, "M&MFIN": 5, "MARICO": 5, "MARUTI": 100,
        "MCDOWELL-N": 10, "MCX": 20, "METROPOLIS": 20, "MFSL": 10, "MGL": 10,
        "MOTHERSON": 1, "MPHASIS": 20, "MRF": 500, "MUTHOOTFIN": 10,
        "NATIONALUM": 1, "NAUKRI": 50, "NAVINFLUOR": 50, "NESTLEIND": 100,
        "NMDC": 1, "NTPC": 1, "OBEROIRLTY": 10, "OFSS": 20, "ONGC": 2.5,
        "PAGEIND": 500, "PEL": 10, "PERSISTENT": 50, "PIDILITIND": 20,
        "PIIND": 50, "PNB": 1, "POLYCAB": 50, "PVRINOX": 20, "RAMCOCEM": 10,
        "RELIANCE": 20, "SAIL": 1, "SBICARD": 10, "SBILIFE": 10, "SBIN": 5,
        "SHREECEM": 250, "SHRIRAMFIN": 20, "SIEMENS": 50, "SRF": 20,
        "SUNPHARMA": 10, "SUNTV": 5, "SYNGENE": 10, "TATACHEM": 10,
        "TATACOMM": 20, "TATACONSUM": 5, "TATAMOTORS": 5, "TATASTEEL": 1,
        "TCS": 20, "TECHM": 10, "TITAN": 20, "TORNTPHARM": 20, "TRENT": 20,
        "TVSMOTOR": 20, "UBL": 10, "ULTRACEMCO": 50, "UPL": 5, "VOLTAS": 10,
        "ZYDUSLIFE": 5, "ABCAPITAL": 2.5, "ABFRL": 2.5, "BANDHANBNK": 2.5,
        "BANKBARODA": 2.5, "BIOCON": 2.5, "CHAMBLFERT": 5, "COALINDIA": 2.5,
        "CROMPTON": 2.5, "EXIDEIND": 2.5, "GRANULES": 2.5, "HINDPETRO": 5,
        "IBULHSGFIN": 2.5, "INDIACEM": 2.5, "INDUSTOWER": 2.5,
        "MANAPPURAM": 2.5, "PETRONET": 2.5, "PFC": 2.5, "POWERGRID": 2.5,
        "RBLBANK": 2.5, "RECLTD": 2.5, "TATAPOWER": 5, "VEDL": 2.5,
        "WIPRO": 2.5, "ZEEL": 2.5, "AMARAJABAT": 10, "APLLTD": 10,
        "CADILAHC": 5, "HDFC": 50, "LTI": 100, "MINDTREE": 20,
        "MOTHERSUMI": 5, "NAM-INDIA": 5, "PFIZER": 50, "PVR": 20,
        "SRTRANSFIN": 20, "TORNTPOWER": 5,
    }


def get_step_df() -> pd.DataFrame:
    d = get_step_value_dict()
    df = pd.DataFrame.from_dict(d, orient="index").reset_index()
    df.rename(columns={"index": "Symbol", 0: "Applicable Step value"}, inplace=True)
    return df
