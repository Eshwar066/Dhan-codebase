import pandas as pd
import datetime as dt
from core.engine.base_engine import BaseEngine
import pdb


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
            position_manager=position_manager,
        )
        self.order_router = order_router
        self.position_manager = position_manager
        # 🔔 Wire structure-exit callback (ONE TIME)
        self.position_manager.on_structure_exit = strategy.on_structure_exit

    # ==========================================================
    # MAIN RUN LOOP
    # ==========================================================
    def run(self, symbols, start_date, end_date, timeframe, exchange, sector):

        for symbol in symbols:
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
            warmup = self.strategy.get_warmup_period()
            df = df.iloc[warmup:].reset_index(drop=True)

            # -------- Candle loop --------
            for _, row in df.iterrows():
                candle = row.to_dict()
                ts = pd.to_datetime(candle["timestamp"])

                if ts.weekday() >= 5:
                    continue

                # -------- Runtime context --------
                ctx, entry_intent = self.build_context(candle)
                # pdb.set_trace()
                # 🔥 ALWAYS run exits + rollover
                self._run_risk_and_rollover(symbol, candle, ctx)

                # 🔒 ONLY gate entries
                if self.strategy.should_evaluate(candle):
                    self._run_entry(symbol, candle, entry_intent)

                self.update_risk_metrics(symbol, candle["close"])

    # ==========================================================
    # EXIT + ROLLOVER (ALWAYS EXECUTES)
    # ==========================================================
    def _run_risk_and_rollover(self, symbol, candle, ctx):

        open_positions = self.position_manager.get_open_positions(
            underlying=symbol,
            strategy=self.strategy.name,
        )

        # ---------- FORCED / STRATEGY EXITS ----------
        for pos in open_positions:
            if pos.tag == "MAIN" and self.strategy.should_exit(pos, candle, ctx):
                exit_intents = self.strategy.on_position_exit(pos, candle, ctx) or []
                for intent in exit_intents:
                    # dot notation since intent is now an object
                    price_map = {intent.instrument.trading_symbol: candle["close"]}
                    self.order_router.process_intent(intent, price_map)

        # ---------- HEDGE ROLLOVER ----------
        rollover_intents = (
            self.strategy.on_candle_rollover(
                open_positions=open_positions,
                candle=candle,
                ctx=ctx,
            )
            or []
        )

        for intent in rollover_intents:
            price_map = {intent.instrument.trading_symbol: candle["close"]}
            self.order_router.process_intent(intent, price_map)

    # ==========================================================
    # ENTRY (SIGNAL DRIVEN)
    # ==========================================================
    def _run_entry(self, symbol, candle, entry_intent):
        if not entry_intent:
            return

        # entry_intent can be a single OrderIntent or a list
        if not isinstance(entry_intent, list):
            entry_intent = [entry_intent]

        for intent in entry_intent:
            # dot notation since intent is an object
            price_map = {intent.instrument.trading_symbol: candle["close"]}
            self.order_router.process_intent(intent, price_map)

    # ==========================================================
    # RISK METRICS
    # ==========================================================
    def update_risk_metrics(self, symbol, ltp):
        pos = self.position_manager.positions.get(symbol)
        if not pos or pos.net_qty == 0:
            return

        diff = ltp - pos.entry_price
        if pos.net_qty < 0:
            diff *= -1

        pos.mfe = max(pos.mfe, diff)
        pos.mae = min(pos.mae, diff)
