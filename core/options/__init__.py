class OptionSelector:

    @staticmethod
    def atm(option_chain, atm_strike):
        return option_chain[option_chain["SEM_STRIKE_PRICE"] == atm_strike]

    @staticmethod
    def otm(option_chain, atm_strike, step, steps=1):
        target = atm_strike + steps * step
        return option_chain[option_chain["SEM_STRIKE_PRICE"] == target]

    @staticmethod
    def itm(option_chain, atm_strike, step, steps=1):
        target = atm_strike - steps * step
        return option_chain[option_chain["SEM_STRIKE_PRICE"] == target]
