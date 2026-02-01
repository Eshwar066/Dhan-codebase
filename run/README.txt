main.py
 └── run_job()
      └── BacktestEngine.run()
            ├── load historical data
            ├── for each candle:
            │     └── strategy.on_candle()
            ├── place virtual orders
            └── update portfolio



To get instrument symbols
#     import time
    # import pandas as pd
    # from pathlib import Path
    # import pdb

    # # ---- instrument dataframe ----
    # df = instrument_store.df

    # # ---- pick required columns safely ----
    # cols = ["SEM_TRADING_SYMBOL", "SEM_CUSTOM_SYMBOL", "SEM_EXM_EXCH_ID"]
    # df_symbols = df[cols].dropna(how="all").copy()

    # # normalize (important for later matching)
    # df_symbols["SEM_TRADING_SYMBOL"] = (
    #     df_symbols["SEM_TRADING_SYMBOL"].astype(str).str.strip()
    # )
    # df_symbols["SEM_CUSTOM_SYMBOL"] = (
    #     df_symbols["SEM_CUSTOM_SYMBOL"].astype(str).str.strip()
    # )
    # df_symbols["SEM_EXM_EXCH_ID"] = (
    #     df_symbols["SEM_EXM_EXCH_ID"].astype(str).str.strip()
    # )

    # # remove fully empty symbol rows
    # df_symbols = df_symbols[
    #     (df_symbols["SEM_TRADING_SYMBOL"] != "")
    #     | (df_symbols["SEM_CUSTOM_SYMBOL"] != "")
    # ]

    # # ---- paths ----
    # BASE_DIR = Path(__file__).resolve().parents[1]
    # current_date = time.strftime("%Y-%m-%d")

    # log_path = BASE_DIR / "logs" / f"instrument_symbols_{current_date}.log"
    # csv_path = BASE_DIR / "logs" / f"instrument_symbols_{current_date}.csv"

    # log_path.parent.mkdir(parents=True, exist_ok=True)

    # # ---- save LOG (human readable) ----
    # with open(log_path, "w", encoding="utf-8") as f:
    #     f.write("SEM_TRADING_SYMBOL | SEM_CUSTOM_SYMBOL | SEM_EXM_EXCH_ID\n")
    #     f.write("-" * 80 + "\n")

    #     for _, row in df_symbols.iterrows():
    #         f.write(
    #             f"{row['SEM_TRADING_SYMBOL']} | "
    #             f"{row['SEM_CUSTOM_SYMBOL']} | "
    #             f"{row['SEM_EXM_EXCH_ID']}\n"
    #         )

    # # ---- save CSV (machine readable) ----
    # df_symbols.to_csv(csv_path, index=False)

    # print(f"✅ Saved {len(df_symbols)} instrument rows")
    # print(f"📄 Log : {log_path}")
    # print(f"📊 CSV : {csv_path}")

    # pdb.set_trace()