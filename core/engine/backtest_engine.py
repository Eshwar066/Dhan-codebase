import pandas as pd
from core.engine.base_engine import BaseEngine
import datetime as dt


class BacktestEngine(BaseEngine):

    def __init__(
        self,
        data_provider,
        strategy,
        instrument_store,
        order_router,
        position_manager,
    ):
        super().__init__(
            strategy=strategy,
            data=data_provider,
            instrument_store=instrument_store,
        )
        self.order_router = order_router
        self.position_manager = position_manager

    def run(self, symbols, start_date, end_date, timeframe, exchange, sector):

        for symbol in symbols:

            # -------- Load full historical data --------
            df = self.data.get_intraday(
                symbol=symbol,
                start_date=start_date,
                end_date=end_date,
                timeframe=timeframe,
                exchange=exchange,
                sector=sector,
            )

            if df is None or len(df) < 50:
                continue

            df["symbol"] = symbol
            df["exchange"] = exchange

            # -------- Indicators --------
            df = self.strategy.prepare_indicators(df)

            # -------- Candle-by-candle simulation --------
            for _, row in df.iterrows():
                candle = row.to_dict()

                ts = pd.to_datetime(candle["timestamp"])
                if ts.weekday() >= 5:
                    continue

                # -------- Runtime context --------
                ctx, entry_intent = self.build_context(candle)

                self._run_strategy(symbol, candle, ctx, entry_intent)
                self.update_risk_metrics(symbol, candle["close"])

    def _run_strategy(self, symbol, candle, ctx, entry_intent):
        # ---------- EXIT ----------
        open_positions = self.position_manager.get_open_positions(
            symbol=symbol, strategy=self.strategy.name
        )

        for position in open_positions:
            exit_signal = self.strategy.should_exit(position, candle, ctx)

            if exit_signal:
                exit_intent = self.strategy.create_exit_intent(position, exit_signal)

                price_map = candle["close"]
                self.order_router.process_intent(exit_intent, price_map)

            # ---------- ENTRY ----------
            # intent = self.strategy.on_candle(candle, ctx)

            if entry_intent:
                # pdb.set_trace()
                price_map = candle["close"]
                self.order_router.process_intent(entry_intent, price_map)

    def update_risk_metrics(self, symbol, ltp):
        pos = self.position_manager.positions.get(symbol)
        if not pos or pos.net_qty == 0:
            return

        diff = ltp - pos.entry_price

        if pos.net_qty < 0:
            diff *= -1

        pos.mfe = max(pos.mfe, diff)
        pos.mae = min(pos.mae, diff)
