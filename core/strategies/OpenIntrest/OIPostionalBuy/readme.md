Strikes in 100s

Expiry: before 16th this month expiry , after 15th nex month expiry

09:30:
    capture full option chain snapshot
 
INTRADAY LOOP:
	Target:
	    if premium >= 1.5x or 50per:
		○         exit and re-entry  reselect new  strike near to previously entered premium (BUY)
		○        at next available slot either 10:45 or 3:15  compare that with 9:30 Option chain snapshot at next available slot either 10:45 or 3:15 (no need of extra logic as the below logic should work for this)
	   
	SL: 40per of premium
	    if SL hit 40per:
	        exit (no reentry ,no revenge entry)


10:45:
	
	1. Capture option chain
	2. If position exists, check that strike premium with 9:30 option chain strike 
		If it is in long buildup or short covering --> continue
		If it is short buildup or long unwinding --> exit positions
	3. If no position exits or just exited positions:
		Check CE and PE in premium in range 170-220 --> select a strike and compare that with 9:30 option chain for both CE and PE, if it comes out to be  long buildup or short covering and premium is <80per  from 9:30 premium --> enter the position 
     

15:15:

	1. Capture option chain
	2. If position exists, check that strike premium with 9:30 option chain strike 
		If it is in long buildup or short covering --> continue ( holding overnight)
		If it is short buildup or long unwinding --> exit positions
	3. If no position exits or just exited positions:
		Check CE and PE in premium in range 170-220 --> select a strike and compare that with 9:30 option chain for both CE and PE, if it comes out to be  long buildup or short covering and premium is <80per  from 9:30 premium--> enter the position 


 