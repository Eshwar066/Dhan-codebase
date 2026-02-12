class Instrument:
    def calc_pnl(self, position, exit_price):
        raise NotImplementedError


class EquityInstrument(Instrument):
    def calc_pnl(self, pos, exit_price):
        return (
            (exit_price - pos.entry_price) * pos.qty
            if pos.side == "BUY"
            else (pos.entry_price - exit_price) * pos.qty
        )


class OptionInstrument(Instrument):
    def calc_pnl(self, pos, exit_price):
        # SELL option → profit if premium decays
        return (pos.entry_price - exit_price) * pos.qty


class FutureInstrument(Instrument):
    def calc_pnl(self, pos, exit_price):
        multiplier = getattr(pos, "lot_size", 1)

        price_diff = (
            exit_price - pos.entry_price
            if pos.side == "BUY"
            else pos.entry_price - exit_price
        )

        return price_diff * pos.qty * multiplier
