Live Engine:
    ## You get is_engine_blocked() = True when:
            Daily max loss breached
            Capital bucket violated
            Risk per trade exceeded
            Operational anomaly detected
            Broker reconciliation mismatch
            Manual override triggered

    ## To make it fully institutional:
        RiskManager daily reset auto-scheduler
        Latency histogram logging
        Slippage tracking
        Execution quality metrics
        Circuit breaker for high spread
        Position reconciliation timer every N minutes
        Heartbeat log every X seconds

    ## To upgrade further:
        1️⃣ Slippage tracking per trade
        2️⃣ Execution quality stats (fill vs mid price)
        3️⃣ Position exposure cap per symbol
        4️⃣ Spread-based block (avoid wide spreads)
        5️⃣ Order rejection rate monitoring
        6️⃣ Partial fill reconciliation logic

## delete instrument file on next day
## engine logger use indian time stamp in 24hrs format

