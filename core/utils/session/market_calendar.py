import datetime as dt

MARKET_SESSIONS = {
    "NSE": {
        "timezone": "Asia/Kolkata",
        "regular": {
            "start": dt.time(9, 15),
            "end": dt.time(15, 30),
        },
    },
    "NSE_INDEX": {
        "timezone": "Asia/Kolkata",
        "regular": {
            "start": dt.time(9, 15),
            "end": dt.time(15, 30),
        },
    },
    "MCX": {
        "timezone": "Asia/Kolkata",
        "regular": {
            "start": dt.time(9, 0),
            "end": dt.time(23, 30),
        },
    },
}
