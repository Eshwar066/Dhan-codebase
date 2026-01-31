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
