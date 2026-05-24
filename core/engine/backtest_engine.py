import pandas as pd
import datetime as dt
from collections import deque
from typing import Any

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
        self.position_manager.on_forced_exit = getattr(
            strategy, "on_forced_exit", None
        )
        # Deferred ENTRY after MAIN_EXIT fill (e.g. OneDayMagicalLine / NiftyIntradayMagicalLine reversal)
        self.position_manager.on_main_exit_fill = self._on_pm_main_exit_fill
        self.position_manager.on_main_entry_fill = self._on_pm_main_entry_fill
        self._last_candle: Any = None
        self._last_candle_buffer: list = []

    def _on_pm_main_entry_fill(self, **kwargs: Any) -> None:
        strategy = kwargs.get("strategy")
        if strategy != self.strategy.name:
            return
        fn = getattr(self.strategy, "on_main_entry_filled", None)
        if not callable(fn):
            return
        candle = getattr(self, "_last_candle", None)
        if not candle:
            return
        recent = getattr(self, "_last_candle_buffer", None) or []
        ctx = self.build_context_only(candle, recent_candles=recent)
        intents = fn(ctx=ctx, **kwargs) or []
        for intent in intents:
            inst = intent.instrument
            sym = inst.trading_symbol
            px = self.strategy.get_option_price_at_candle(
                candle,
                ctx,
                inst.strike,
                inst.option_type,
                inst.expiry,
                trading_symbol=sym,
            )
            if px is None:
                px = float(intent.price)
            price_map = {sym: float(px)}
            self.order_router.process_intent(intent, price_map)

    def _on_pm_main_exit_fill(self, **kwargs: Any) -> None:
        strategy = kwargs.get("strategy")
        if strategy != self.strategy.name:
            return
        fn = getattr(self.strategy, "on_main_exit_filled", None)
        if not callable(fn):
            return
        inst = kwargs.get("instrument")
        sym = None
        if inst is not None:
            sym = getattr(inst, "underlying_symbol", None) or getattr(
                inst, "symbol", None
            )
        ts = kwargs.get("candle_ts")
        candle_stub = {"symbol": sym or "", "timestamp": ts, "close": 0.0}
        ctx = (
            self.build_context(candle_stub)
            if sym and callable(getattr(self, "build_context", None))
            else None
        )
        pairs = fn(ctx=ctx, **kwargs) or []
        for intent, candle in pairs:
            sym = candle.get("symbol")
            if not sym:
                continue
            price_map = {
                intent.instrument.trading_symbol: float(
                    intent.price
                )
            }
            self.order_router.process_intent(intent, price_map)

    def build_context(self, candle, recent_candles=None):
        intent_store = getattr(self.order_router, "intent_store", None)
        return super().build_context(
            candle, recent_candles=recent_candles, intent_store=intent_store
        )

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

            if df is None or len(df) < 50:
                continue

            df["symbol"] = symbol
            df["exchange"] = exchange

            # -------- Indicators (strategy computes htf_trend in prepare_indicators) --------

            ts_col = pd.to_datetime(df["timestamp"], utc=True)
            df["timestamp"] = ts_col.dt.tz_convert("Asia/Kolkata")
            if "time" in df.columns:
                df["time"] = df["timestamp"].dt.time

            df = self.strategy.prepare_indicators(df)
            warmup = self.strategy.get_warmup_period()
            # Include macro EMA warmup so first ~50 (slope) or ~100 (ema) candles are stable
            macro_slope = getattr(self.strategy, "macro_ema_slope_period", None)
            macro_ema = getattr(self.strategy, "macro_ema_period", None)
            macro_warmup = max(warmup, macro_slope or 0, macro_ema or 0)
            df = df.iloc[macro_warmup:].reset_index(drop=True)

            # Rolling buffer of recent candles for this symbol (max 50)
            candle_buffer = deque(maxlen=220)

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
                self._last_candle = candle
                self._last_candle_buffer = list(candle_buffer)

                # -------- Runtime context --------
                ctx, entry_intent = self.build_context(
                    candle, recent_candles=list(candle_buffer)
                )
                self.evaluate_sim_broker_stops(candle, ctx)
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
                    price_map = {intent.instrument.trading_symbol: intent.price}
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
            price_map = {intent.instrument.trading_symbol: intent.price}
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
            price_map = {intent.instrument.trading_symbol: intent.price}
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
