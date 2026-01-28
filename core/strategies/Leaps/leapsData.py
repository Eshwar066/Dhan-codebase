# import pandas as pd
# import datetime as dt
# import pdb

# START_TIME = dt.time(9, 10)
# END_TIME = dt.time(15, 30)

# #Backtesting Data
# class LeapsQuaterlyData:
#     def __init__(self, tsl):
#         self.tsl = tsl

    # def get_intraday(self, symbol, start_date, end_date):
    #     df = self.tsl.get_long_term_historical_data(
    #         tradingsymbol=symbol,
    #         exchange="INDEX",
    #         timeframe="60",
    #         from_date=start_date,
    #         to_date=end_date,
    #     )

    #     if df is None or df.empty:
    #         return None

    #     # Normalize timestamp
    #     if "timestamp" in df.columns:
    #         df["timestamp"] = pd.to_datetime(df["timestamp"])
    #     elif "date" in df.columns:
    #         df["timestamp"] = pd.to_datetime(df["date"])
    #     elif "start_Time" in df.columns:
    #         df["timestamp"] = pd.to_datetime(df["start_Time"])
    #     else:
    #         return None

    #     df = df.sort_values("timestamp").reset_index(drop=True)

    #     # Market hours filter
    #     df["time"] = df["timestamp"].dt.time
    #     df = df[(df["time"] >= START_TIME) & (df["time"] <= END_TIME)]

    #     return df.reset_index(drop=True)

    # def expiry_list(self, symbol, exchange):
    #     expiry_list = self.tsl.get_expiry_list(Underlying=symbol, exchange=exchange)
    #     return expiry_list

    # def get_expired_optionchain(self, symbol, monthlyExpiryDate):
    #     print(monthlyExpiryDate)
    #     data = self.tsl.get_expired_option_data(
    #         tradingsymbol="NIFTY",
    #         exchange="NSE",
    #         interval=60,  # 1-hour candle
    #         expiry_flag="MONTH",  # Monthly expiry
    #         expiry_code=4,  # March 2023 expiry (check your DHAN expiry sequence)
    #         strike="ATM",  # OTM strike relative to ATM
    #         option_type="CALL",
    #         from_date="2023-03-29",  # start of month
    #         to_date="2023-03-29",  # expiry date
    #     )

    #     return data
