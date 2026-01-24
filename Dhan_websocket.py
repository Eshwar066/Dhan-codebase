"""
Dhan WebSocket LTP feed. Uses core.feed (Dhan as single source of truth).
Instrument master from Dhan (core.api.get_instrument_file).
"""
from core.feed.dhan_websocket import main_loop

# Backward compat: same default credentials as before; override via args or edit
DHAN_CLIENT_ID = "1102790337"
DHAN_ACCESS_TOKEN = "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzUxMiJ9.eyJpc3MiOiJkaGFuIiwicGFydG5lcklkIjoiIiwiZXhwIjoxNzMxNDc5MTg1LCJ0b2tlbkNvbnN1bWVyVHlwZSI6IlNFTEYiLCJ3ZWJob29rVXJsIjoiIiwiZGhhbkNsaWVudElkIjoiMTEwMjc5MDMzNyJ9.cJFmav3LOCQqz9Tp-KRJFPEYR-1Ds3G9YiZqXxcTfnQ3Nqgi4JJNd-y4XRbhfQD5RFAVLooTfZzpUGGstaLYLw"

if __name__ == "__main__":
    main_loop(DHAN_CLIENT_ID, DHAN_ACCESS_TOKEN)
