| Canonical Field | CSV Column                 |
| --------------- | -------------------------- |
| exchange        | `SEM_EXM_EXCH_ID`          |
| segment         | `SEM_SEGMENT`              |
| instrument_id   | `SEM_SMST_SECURITY_ID`     |
| trading_symbol  | `SEM_TRADING_SYMBOL`       |
| custom_symbol   | `SEM_CUSTOM_SYMBOL`        |
| symbol          | `SM_SYMBOL_NAME`           |
| instrument_type | `SEM_EXCH_INSTRUMENT_TYPE` |
| option_type     | `SEM_OPTION_TYPE`          |
| strike          | `SEM_STRIKE_PRICE`         |
| expiry          | `SEM_EXPIRY_DATE`          |
| lot_size        | `SEM_LOT_UNITS`            |
| tick_size       | `SEM_TICK_SIZE`            |
| series          | `SEM_SERIES`               |

# print(instrument_store.df.columns)

    # print(instrument_store.df.head())

    # nifty_options = instrument_store.df[
    #     instrument_store.df["SEM_TRADING_SYMBOL"].str.contains("NIFTY")
    #     & (instrument_store.df["SEM_OPTION_TYPE"] == "PE")
    # ]

    # target_strike = 25000
    # nearest_strike_row = nifty_options.iloc[
    #     (nifty_options["SEM_STRIKE_PRICE"] - target_strike).abs().argmin()
    # ]
    # print(nearest_strike_row)

    # nifty_options = instrument_store.df[
    #     instrument_store.df["SEM_TRADING_SYMBOL"].str.contains("NIFTY")
    #     & (instrument_store.df["SEM_OPTION_TYPE"] == "PE")
    # ]

    # target_strike = 25000
    # nearest_row = nifty_options.iloc[
    #     (nifty_options["SEM_STRIKE_PRICE"] - target_strike).abs().argmin()
    # ]
    # print(nearest_row)
    # print(len(nifty_options))
    # print(nifty_options.head(5))

    # inst = instrument_store.resolve_index_option(
    #     index_symbol="NIFTY",
    #     strike_price=nearest_row["SEM_STRIKE_PRICE"],
    #     option_type=nearest_row["SEM_OPTION_TYPE"],
    # )

    # nifty_options = instrument_store.df[
    #     instrument_store.df["SEM_TRADING_SYMBOL"].str.contains("NIFTY")
    #     & (instrument_store.df["SEM_OPTION_TYPE"] == "PE")
    # ]

    # target_strike = 25000
    # nearest_row = nifty_options.iloc[
    #     (nifty_options["SEM_STRIKE_PRICE"] - target_strike).abs().argmin()
    # ]
    # print(nearest_row)


    #==============================================================================
    # instrument_store.df.columns.tolist()
# [
#     "Unnamed: 0",
#     "SEM_EXM_EXCH_ID",
#     "SEM_SEGMENT",
#     "SEM_SMST_SECURITY_ID",
#     "SEM_INSTRUMENT_NAME",
#     "SEM_EXPIRY_CODE",
#     "SEM_TRADING_SYMBOL",
#     "SEM_LOT_UNITS",
#     "SEM_CUSTOM_SYMBOL",
#     "SEM_EXPIRY_DATE",
#     "SEM_STRIKE_PRICE",
#     "SEM_OPTION_TYPE",
#     "SEM_TICK_SIZE",
#     "SEM_EXPIRY_FLAG",
#     "SEM_EXCH_INSTRUMENT_TYPE",
#     "SEM_SERIES",
#     "SM_SYMBOL_NAME",
# ]

#  instrument_store.df[instrument_store.df["SM_SYMBOL_NAME"] == "NIFTY" ].head()
# instrument_store.df[instrument_store.df["SEM_EXCH_INSTRUMENT_TYPE"] == "OPTIDX"]["SM_SYMBOL_NAME"].value_counts().head(10)


# 2️⃣ Filter NIFTY PE options
# nifty_options = instrument_store.df[
#     instrument_store.df["SEM_TRADING_SYMBOL"].str.contains("NIFTY")
#     & (instrument_store.df["SEM_OPTION_TYPE"] == "PE")
# ]

# # 3️⃣ Pick nearest strike to your target
# target_strike = 25000
# nearest_row = nifty_options.iloc[
#     (nifty_options["SEM_STRIKE_PRICE"] - target_strike).abs().argmin()
# ]

# ✅ Found security row:
# Unnamed: 0                                  216446
# SEM_EXM_EXCH_ID                                NSE
# SEM_SEGMENT                                      D
# SEM_SMST_SECURITY_ID                         62925
# SEM_INSTRUMENT_NAME                         OPTIDX
# SEM_EXPIRY_CODE                                  0
# SEM_TRADING_SYMBOL          NIFTY-Mar2026-24000-PE
# SEM_LOT_UNITS                                 65.0
# SEM_CUSTOM_SYMBOL           NIFTY 30 MAR 24000 PUT
# SEM_EXPIRY_DATE                         2026-03-30
# SEM_STRIKE_PRICE                           24000.0
# SEM_OPTION_TYPE                                 PE
# SEM_TICK_SIZE                                  5.0
# SEM_EXPIRY_FLAG                                  M
# SEM_EXCH_INSTRUMENT_TYPE                        OP
# SEM_SERIES                                     NaN
# SM_SYMBOL_NAME                                 NaN
