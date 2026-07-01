"""
Send alerts via Telegram bot. Used by Delta (and optionally Dhan) for order placement,
errors, and slippage notifications. Logic mirrors dhan_tradehull.send_telegram_alert.

Closed-candle rows are not sent to Telegram for DELTA (see EngineLogger._send_telegram_alert).
"""

import logging
import urllib.parse

import requests

logger = logging.getLogger(__name__)


def send_telegram_alert(message: str, receiver_chat_id: str, bot_token: str) -> None:
    """
    Sends a message via Telegram bot to a specific chat ID.

    Parameters:
        message: The message to be sent.
        receiver_chat_id: The chat ID of the receiver.
        bot_token: The token of the Telegram bot.
    """
    if not receiver_chat_id or not bot_token:
        return
    try:
        encoded_message = urllib.parse.quote(message)
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage?chat_id={receiver_chat_id}&text={encoded_message}"
        response = requests.get(url, timeout=10)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        # Log but do not raise; alert failure must not break trading
        logger.warning("Telegram alert failed: %s", e)
