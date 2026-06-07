# Crypto RSI Indicator Alerts

Run **BTCUSD** and **ETHUSD** on **1-minute** candles. Compute RSI(14) every bar and send a **Telegram** alert when:

- RSI crosses **above 70** (overbought)
- RSI crosses **below 30** (oversold)

No orders are placed — alerts only.

## Implementation

| Item | Location |
|------|----------|
| Strategy | `core/strategies/Crypto/Indicator/CryptoRsiIndicator.py` |
| Registry | `STRATEGY_MAP["CryptoRsiIndicator"]` |
| Engine job | `run/config.py` → `delta_crypto_rsi_indicator` |

## Run (live)

Set Telegram env vars (or edit `telegram` block in config):

```powershell
$env:TELEGRAM_CRYPTO_RSI_BOT_TOKEN = "<your-bot-token>"
$env:TELEGRAM_CRYPTO_RSI_CHAT_ID = "<your-chat-id>"
python -m run.main --engine-id delta_crypto_rsi_indicator
```

## Backtest (prints alerts to console)

Set `"run_mode": "BACKTEST"` on the job, then:

```powershell
python -m run.main --engine-id delta_crypto_rsi_indicator
```
