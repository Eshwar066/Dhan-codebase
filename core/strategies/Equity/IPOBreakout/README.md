
# create same version for BTC and ETH

# IPOBreakout – Strategy Mastery

Equity strategy for **Dhan broker** (India). Trades IPO listing-day breakouts: long when price breaks above a reference level; exit on target % or stop-loss %.

## If you'd like next upgrades, we can add:

    Cross-above logic instead of simple above

    Minimum % distance filter

    Volume expansion filter

    Prevent same-day re-entry

    Position sizing logic

    Portfolio-level capital allocator

<!-- CHAT GPT -->

Great question — IPO breakout strategies need slightly different logic than normal stocks because:

Short price history

No long-term support/resistance

High volatility

Strong retail + operator participation

Often low float

So you evaluate them using structure + volume + volatility expansion.

Below is a structured framework you can use.

🧱 1️⃣ Core Breakout Structure Indicators (Must Have)

These detect actual breakout behavior.

🔹 1. Opening Range Breakout (ORB)

Best for newly listed IPOs (first 5–20 days).

Logic:

Take first 15–30 min high

Break above it with volume spike

Works well in first 30–60 trading days.

🔹 2. High of First N Days

Example:

Break above highest high of first 20 days

Or first 30 days

IPOs often form:

Listing spike → consolidation → expansion

🔹 3. All-Time High Breakout

Since IPOs don’t have long history:

if close > highest(high, lookback):


Lookback = full available history

Very powerful when combined with volume expansion.

📊 2️⃣ Volume Confirmation (Very Important)

IPOs need volume confirmation.

🔹 4. Volume Spike
volume_today > 2 * average_volume(20)


Breakouts without volume in IPOs often fail.

🔹 5. Relative Volume (RVOL)
volume_today / avg_volume_20 > 1.5


Better than absolute volume.

🔹 6. Delivery Percentage (Advanced – India Specific)

High delivery % breakout = strong accumulation.

Very powerful filter.

📈 3️⃣ Momentum Indicators

Used for confirmation, not trigger.

🔹 7. RSI (14)

Good IPO breakout filter:

RSI between 55–70 → strong

Avoid RSI > 85 → overheated

🔹 8. ADX (14)

ADX > 20–25 → trend strength confirmed

Very useful for IPO momentum continuation.

🔹 9. MACD Histogram Expansion

Use for:

Detecting fresh momentum

Avoiding late entries

📉 4️⃣ Volatility Expansion

IPOs compress → explode.

🔹 10. ATR Expansion
ATR_today > 1.5 * ATR_20_avg


Shows volatility expansion.

🔹 11. Bollinger Band Breakout

Close > Upper Band

volume spike

Classic expansion setup.

🧠 5️⃣ IPO-Specific Filters (Very Powerful)

These are underrated.

🔹 12. Days Since Listing Filter

Segment IPOs:

Days	Behavior
1–5	Pure volatility
6–20	Stabilization
20–90	First real breakout zone
90–365	Institutional accumulation

You can create strategies per phase.

🔹 13. Listing Gain Filter

Avoid IPOs that:

Listed 100% above issue price (often distribution)

Or use:

if current_price > listing_day_high:

🔹 14. Float / Market Cap Filter

Small float IPOs move faster.

Filter:

Market cap < X

Market lot small

Free float < threshold

🚀 6️⃣ Structure + Pullback Setup (Advanced)

Instead of breakout at highs:

IPO breaks out

Pulls back to 20 EMA

Volume dries up

Then resumes

Very high RR setup.

Indicators:

20 EMA

Volume contraction

Inside bar

🎯 7️⃣ Strong Institutional Pattern (Best Performing Combo)

For IPOBreakout strategy, I’d suggest this core logic:

Entry Conditions
1. Days since listing > 20
2. Close > Highest High (last 20 days)
3. Volume > 2x avg volume 20
4. RSI > 55
5. ADX > 20


This avoids:

Early noise

False breakouts

Illiquid names

🧮 8️⃣ Ranking Instead of Filtering (Better Approach)

Instead of yes/no filter, score IPOs:

Example scoring:

+2 if volume spike
+1 if RSI 60-70
+1 if ADX > 25
+2 if breakout above 30-day high
+1 if market cap < 5000cr


Trade top 10 ranked.

This is much more stable.