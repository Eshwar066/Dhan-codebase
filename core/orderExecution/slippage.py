def allowed_slippage(signal_price, ltp, max_slip_pct=0.1):
    
    slip_pct = abs(ltp - signal_price) / signal_price * 100
    return slip_pct <= max_slip_pct

