engine = LiveEngine(
    broker=DhanBroker(), strategy=ShortStrangleStrategy(), risk_manager=RiskManager()
)
engine.start()
