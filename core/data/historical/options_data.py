class OptionHistoricalData:
    """
    Generic option chain access for ANY option strategy
    ✅ Can be used by:
        Leaps quarterly
        Short strangle
        Iron condor
        Calendar spreads
        Any options strategy
    """

    def __init__(self, tsl):
        self.tsl = tsl

    def get_expiry_list(self, symbol, exchange="NSE"):
        return self.tsl.get_expiry_list(Underlying=symbol, exchange=exchange)

    def get_expired_option_chain(
        self,
        symbol,
        expiry_date,
        option_type,
        strike="ATM",
        timeframe=60,
        from_date=None,
        to_date=None,
    ):
        return self.tsl.get_expired_option_data(
            tradingsymbol=symbol,
            exchange="NSE",
            interval=timeframe,
            expiry_flag="MONTH",
            expiry_code=None,
            strike=strike,
            option_type=option_type,
            from_date=from_date,
            to_date=to_date,
        )
