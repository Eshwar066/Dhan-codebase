core/models/
├── __init__.py
├── position.py
├── order.py
├── trade.py
├── candle.py
├── instrument.py
├── signal.py          # optional but powerful
└── enums.py
==================

A Position should:

    Be broker-agnostic

    Work for backtest, paper, live

    Support options + equity

    Be simple but extensible
===============================
✅ Why this design works long-term
    ✔ Supports Options + Cash

    option_type, strike, expiry are optional

    Equity trades just ignore them

    ✔ Same object everywhere

    Used by:

    Strategy

    Risk Manager

    Broker

    Portfolio

    Engine

 ===============
 pos = Position(
    symbol="NIFTY",
    side="SELL",
    qty=50,
    entry_price=120.5,
    sl=150,
    target=60,
    option_type="CALL",
    strike=22500,
)

print(pos.is_open())  # True
   