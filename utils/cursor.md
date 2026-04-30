
Act as a senior algorithmic trading engineer with deep experience in building low-latency, multi-strategy, multi-broker execution systems; prioritize correctness, robustness, and scalable architecture over quick fixes.
Treat this codebase as a production-grade trading system and operate as a senior algo developer with extensive experience in OMS design, market data systems, and fault-tolerant architectures.
Assume the role of a highly experienced quantitative trading systems engineer; make decisions that ensure deterministic execution, risk safety, and scalability across multiple brokers and accounts.

Implement this for dhan broker  and use this file as prompt and dont use this file name in project and main readme.md file


OI Positional buy strategy

Strikes in 100s

Timeframe: 15 min

09:30:
    capture full option chain snapshot
    candidates = strikes with 180–220 premium for both CE and PE
 
INTRADAY LOOP:
    if premium >= 1.5x or 50per:
        exit
        reselect  strike near to previously entered premium
        

    if SL hit 40per:
        exit (no revenge entry)

10:45:
     
    for each strike:
        compare with 9:30
        classify OI signal--> long

    select best valid strike
    enter trade


15:15:
    compare current vs 9:30

    if same signal:
        hold overnight
	Next day at 9:30 take the current holding strike data(OI and Premium) as benchmark and opp strike at 180-220 premium strike and compare at 10:45--> repeat the process

    elif opposite signal:
        exit
        scan opposite side
        if long signal on comparing with benchmark:
            enter

Additionally:
       
	Problem 3: Late entry risk (10:45)
	Sometimes move already done.
	✅ Fix:
	Add condition:
	premium change from 9:30 < 80%
	
