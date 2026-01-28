If nifty rsi is below 32 will sell call option in 1hr candle, until it crosses rsi 52

If nifty rsi is above 52 will sell put option in 1hr candle, until it crosses rsi 32

timeframe to check the logic is at 10:15,11:15,12:15,1:15,2:15,3:15 since we are using 1hr candle

sell 500-1000 roundoff strikes in quaterly month
jan-march, below 15th feb, take march strikes
after 15th feb, sell June strikes
april-June, in may after 15th we take september strikes
july-september, in aug after 15th will take december strikes
oct- decemeber, in nov after 15th will take march strikes

Hedging in monthly of current expiry: Buy Monthly Hedge from nifty, approx 2per away from selling strike
Rollover hedging on 18th of every month, if 18th is holiday or saturaday or sunday will do 1 day before

if new tradas comes 15th or after that then take hedging of next month only


In live: while placing order will get market_depth and place limit order for best price.


