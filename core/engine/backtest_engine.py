import pandas as pd
import datetime as dt
from collections import deque
import pdb

from core.engine.base_engine import BaseEngine


class BacktestEngine(BaseEngine):
    def __init__(
        self,
        data_provider,
        strategy,
        instrument_store,
        order_router,
        position_manager,
        universe_service=None,
        broker_name=None,
    ):
        super().__init__(
            strategy=strategy,
            data=data_provider,
            instrument_store=instrument_store,
            position_manager=position_manager,
            universe_service=universe_service,
        )
        self.order_router = order_router
        self.position_manager = position_manager
        self.broker_name = broker_name or ""
        # Wire structure-exit callback (ONE TIME)
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
            # df1 = self.data.get_products()
            # df2 = self.data.product_id_for_symbol("BTCUSD")
            # df3 = self.data.get_latest_candles({"BTCUSD", "ETHUSD"})
            # df4 = self.data.get_live_expiry("BTCUSD")
            # pdb.set_trace()

            if df is None or len(df) < 50:
                continue

            df["symbol"] = symbol
            df["exchange"] = exchange

            # -------- ema  slop used in btc: Macro trend filter (same-TF): set candle["htf_trend"] before should_evaluate --------
            macro_slope = getattr(self.strategy, "macro_ema_slope_period", None)
            macro_ema = getattr(self.strategy, "macro_ema_period", None)
            slope_threshold = getattr(self.strategy, "macro_ema_slope_threshold", 0.5)
            if macro_slope is not None:
                df["ema_50"] = df["close"].ewm(span=macro_slope, adjust=False).mean()
                df["ema_slope"] = df["ema_50"].diff()
                df["htf_trend"] = None
                df.loc[df["ema_slope"] > slope_threshold, "htf_trend"] = "BULL"
                df.loc[df["ema_slope"] < -slope_threshold, "htf_trend"] = "BEAR"
            elif macro_ema is not None:
                df["ema_100"] = df["close"].ewm(span=macro_ema, adjust=False).mean()
                df["htf_trend"] = None
                df.loc[df["close"] > df["ema_100"], "htf_trend"] = "BULL"
                df.loc[df["close"] < df["ema_100"], "htf_trend"] = "BEAR"
            else:
                df["htf_trend"] = None

            # -------- Indicators --------
            if self.broker_name == "DHAN" and "timestamp" in df.columns:
                ts_col = pd.to_datetime(df["timestamp"], utc=True)
                df["timestamp"] = ts_col.dt.tz_convert("Asia/Kolkata")
            if "time" in df.columns:
                df["time"] = df["timestamp"].dt.time
            df = self.strategy.prepare_indicators(df)
            warmup = self.strategy.get_warmup_period()
            # Include macro EMA warmup so first ~50 (slope) or ~100 (ema) candles are stable
            macro_warmup = max(warmup, macro_slope or 0, macro_ema or 0)
            df = df.iloc[macro_warmup:].reset_index(drop=True)

            # Rolling buffer of recent candles for this symbol (max 50)
            candle_buffer = deque(maxlen=50)

            # -------- Candle loop (candle["htf_trend"] already set above for macro filter) --------
            for _, row in df.iterrows():
                candle = row.to_dict()
                ts = pd.to_datetime(candle["timestamp"])
                if "htf_trend" not in candle or pd.isna(candle.get("htf_trend")):
                    candle["htf_trend"] = None

                # Skip weekends for equity/index; crypto (DELTA) runs 24/7
                # if self.broker_name != "DELTA" and ts.weekday() >= 5:
                #     continue

                candle_buffer.append(candle)

                # -------- Runtime context --------
                ctx, entry_intent = self.build_context(
                    candle, recent_candles=list(candle_buffer)
                )
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
