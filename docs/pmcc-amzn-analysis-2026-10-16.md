# PMCC Recommendation Analysis: AMZN 215C / 275C
## Date: 2026-10-16 | Screener: pmcc_quality.py | Issue #33

---

## The Recommendation

| Field | Value |
|-------|-------|
| **Symbol** | AMZN |
| **Structure** | Poor Man's Covered Call (PMCC) |
| **Long leg** | 215C LEAPS (270-800 DTE, 0.80-0.95Δ) |
| **Short leg** | 275C (21-60 DTE, 0.15-0.35Δ) |
| **P/D 30d** | 12.40% — monthly premium as % of capital |
| **Capital** | $5,905 (LEAPS debit) |
| **Monthly income** | ~$732 (12.40% × $5,905) |
| **Breach** | 4.8% — stock must rise 4.8% to threaten short call |

---

## 1. Technical Analysis

### Momentum: NEUTRAL (not overbought, not oversold)

| Indicator | Value | Signal |
|-----------|-------|--------|
| RSI (14) | 49.34 | Neutral — dead center, no extreme |
| MACD (12,26) | 0.77 | Sell — bearish crossover |
| Stochastic (9,6) | 58.96 | Neutral |
| Williams %R | -50.70 | Buy — mid-range |
| CCI (14) | 37.36 | Neutral |
| ADX (14) | 14.44 | Weak trend — no strong directional conviction |
| Bollinger %B | 0.48 | Dead center — maximum indecision |

**Reading:** Textbook neutral. RSI at 49 is neither overbought (>70) nor oversold (<30).
The MACD is the one bearish note, but ADX at 14 confirms there's no strong trend
in either direction. This is a coiling market, not a trending one.

### Trend: MIXED (short-term weak, long-term bullish)

| Timeframe | Signal |
|-----------|--------|
| Price vs SMA 200 ($242.53) | **Above** — long-term uptrend intact |
| Price vs SMA 50 ($257.88) | **Below** — short-term weakness |
| Price vs SMA 20 ($253.23) | **Above** — marginal |
| Price vs SMA 5 ($257.74) | **Below** — very short-term soft |

**Reading:** AMZN is above its 200-day (long-term bullish) but below its 50-day
(short-term resistance). This is a stock in a long-term uptrend experiencing
short-term consolidation — exactly the setup where PMCC works best (collect
premium while waiting for the uptrend to resume).

### Support & Resistance

| Level | Price | Type |
|-------|-------|------|
| Strong support | $198.58 | Long-term |
| Medium support | $203.97 | — |
| Weak support | $209.36 | — |
| Current | ~$254.76 | — |
| Weak resistance | $263.70 | Short-term |
| 52-week high | $287.20 | Long-term target |

**Key:** The 275 short strike sits between current price ($255) and the $263.70
resistance. If AMZN breaks above $264, the short call comes under pressure.
The 4.8% breach distance gives reasonable cushion.

### Pullback Risk: MODERATE

- Stock is **not** in a parabolic uptrend (RSI 49, not 70+)
- **Not** overbought — no exhaustion signal
- However, price is **below** the 50-day MA, suggesting recent weakness
- The "coil" pattern (tight Bollinger Bands, flat MACD) typically resolves
  with a volatility expansion — direction unknown
- **Q3 earnings on Oct 29** are the likely catalyst for resolution

**For PMCC:** A pullback would hurt the LEAPS (long call loses value) but the
short call premium provides partial offset. The structure is net-long delta,
so direction matters.

---

## 2. Fundamental Analysis

### Valuation: FAIR to CHEAP

| Metric | Value | Context |
|--------|-------|---------|
| P/E (TTM) | 20.5 | vs historical ~25.6 = **1.8% cheaper than history** |
| Forward P/E | 27.1 | Higher — market pricing in growth |
| PEG ratio | 0.23 | **Extremely low** — PEG < 1.0 = undervalued on growth |
| Price/Sales | 3.52 | Reasonable for mega-cap tech |
| Price/Book | 4.98 | — |
| EPS (TTM) | $12.44 | **+89.7% YoY growth** |
| Revenue (TTM) | $775.68B | +15.8% YoY |
| Gross margin | 50.77% | **Above 50%** — structural milestone |
| Operating margin | 12.08% | — |
| Net margin | 17.44% | Strong |
| ROE | 30.56% | Excellent |

**Reading:** At 20.5x trailing earnings with 89.7% EPS growth, the PEG of 0.23
is extraordinarily cheap. The market is not assigning a growth premium despite
massive earnings expansion. Forward P/E of 27.1 reflects expected growth
normalization.

**Verdict: UNDERVALUED on a PEG basis.** The stock looks cheap relative to its
earnings growth rate.

### Growth Drivers

- **AWS:** 37% growth (fastest in 18 quarters), $42.2B quarterly revenue
- **Q2 2026:** $200.6B revenue (+20% YoY), $27.5B operating income (+43% YoY)
- **Q3 guidance:** $197-202B revenue
- **Analyst consensus:** $829.29B FY2026 revenue (+15.67% YoY)

---

## 3. Analyst Ratings

| Source | Rating |
|--------|--------|
| Wall Street consensus | **$331.20 target (+30% upside)** |
| TipRanks technical | Hold (mixed signals) |
| PulsarSignals | Strong Buy (15) / Buy (50) / Hold (4) / Sell (0) |
| Sell ratings | **Zero** across all sources |

**Reading:** Overwhelmingly bullish on fundamentals (30% upside to $331),
but technically neutral in the short term. This divergence — bullish
fundamentals + neutral technicals — is exactly why PMCC makes sense:
collect premium while waiting for the fundamental thesis to play out.

---

## 4. Strategy Risk Assessment

### PMCC-Specific Risks

| Risk | Level | Detail |
|-----|-------|--------|
| **Directional** | Medium | Net-long delta. A sharp selloff hurts the LEAPS more than the short call helps. |
| **Earnings (Oct 29)** | **HIGH** | Q3 earnings in 13 days. AMZN has moved ±8-13% on recent earnings. The short 275C could be breached on a big beat. |
| **Time decay** | Low | LEAPS have minimal theta; short call theta works in your favor. |
| **Vol crush** | Medium | Post-earnings IV collapse would hurt the LEAPS value. |
| **Assignment** | Low | Short call is OTM; early assignment unlikely. |

### Expected Move

- **ATR (14):** $5.79 (~2.3% of price)
- **Weekly ATR:** $10.15 (~4.0%)
- **30-day expected move (1σ):** ~$18-22 (~7-8%)
- **Breach distance:** 4.8% ($255 → $267)

**Critical:** The 4.8% breach cushion is **less than the 7-8% expected 30-day move.**
This means there's a meaningful probability (~30-35%) that AMZN touches or exceeds
the 275 short strike within the short call's lifetime.

### What Happens If Breached?

If AMZN rallies above $275:
1. Short call goes ITM — you can roll up/out for a credit
2. LEAPS also gains value (delta hedge) — the pair remains profitable
3. **This is not a loss scenario** — it's a "profit capped" scenario
4. Action: roll the short call to a higher strike/next expiration

### Pullback Scenario

If AMZN drops 10% to ~$230:
1. LEAPS loses value (delta ~0.85 × $25 = ~$21.25 per share = -$2,125)
2. Short call expires worthless (+$732 premium kept)
3. Net: -$1,393 unrealized on the LEAPS
4. **The LEAPS still has 270+ days** — time to recover

---

## 5. Catalysts

| Date | Event | Impact |
|------|-------|--------|
| **Oct 29, 2026** | **Q3 earnings** (after close) | **HIGH** — consensus $2.01 EPS, $205.65B revenue. 5 straight beats. Could move ±10%. |
| Ongoing | AWS growth (37%) | Positive — cloud momentum supports multiple |
| Ongoing | Holiday season setup | Positive — Q4 is AMZN's strongest quarter |

**⚠️ EARNINGS WARNING:** The Oct 29 earnings fall within the short call window.
The screener flagged "earnings date unknown" because the date was just added.
**Consider:** Wait until after earnings to enter, OR use a wider short strike,
OR accept the binary risk for the higher premium.

---

## 6. What Was Discarded

### Screening Process (pmcc_quality.py)

The screener evaluates **every possible LEAPS × short-call combination** per symbol:

| Stage | Filter | Typical rejection rate |
|-------|--------|----------------------|
| 1. Universe | 20 symbols screened | — |
| 2. LEAPS eligibility | 0.80-0.95Δ, 270-800 DTE, liquid | ~30% rejected (no suitable LEAPS) |
| 3. Short call eligibility | 0.15-0.35Δ, 21-60 DTE, liquid | ~40% rejected (no suitable short) |
| 4. Pair gates | P/D ≥ 4.0%, breach ≤ 8%, no earnings | ~50% of pairs rejected |
| 5. Capital efficiency | Sort by P/D 30d | — |
| **Result** | **15 qualifying pairs** from 20 symbols | — |

### Why AMZN Ranked #1

| Criterion | AMZN | #2 GOOGL | Advantage |
|-----------|------|----------|-----------|
| P/D 30d | **12.40%** | 8.31% | **+49% more income** |
| Capital | $5,905 | $8,950 | **34% less capital** |
| Breach | 4.8% | 5.8% | Slightly tighter |
| Income/month | ~$732 | ~$744 | Similar absolute, better efficiency |

AMZN wins on **capital efficiency** — it generates nearly the same dollar income
as GOOGL with 34% less capital deployed.

### What Didn't Make It

- **5 symbols** produced zero qualifying pairs (failed LEAPS or short-call gates)
- Pairs with P/D < 4.0% were rejected (insufficient income)
- Pairs with breach > 8% were rejected (too much upside risk)
- Pairs with earnings in the short-call window were flagged

---

## 7. Bottom Line

**The PMCC is a HIGH-QUALITY setup with ONE major caveat:**

✅ **Pros:**
- Highest P/D (12.40%) in the universe — exceptional income
- Undervalued on PEG (0.23) with 89.7% EPS growth
- Zero analyst sell ratings, $331 target (+30%)
- Technically neutral (not overbought — no exhaustion)
- Above 200-day MA (long-term uptrend intact)

⚠️ **Cons:**
- **Q3 earnings Oct 29** — 13 days away, inside the short-call window
- Breach distance (4.8%) < expected 30-day move (7-8%)
- MACD bearish, price below 50-day (short-term soft)

**Recommendation:**
- **If entering now:** Accept earnings binary risk. The 12.4% monthly premium compensates.
- **If risk-averse:** Wait until Oct 30 (post-earnings) to enter. You'll miss one premium cycle but avoid the binary event.
- **If breached:** Roll the short call up and out — the LEAPS gains will offset.

---

## Data Sources

- Price/technical: Finnhub, TipRanks (Oct 15-16, 2026)
- Fundamentals: Forbes, FinanceCharts (TTM data)
- Analyst ratings: TipRanks, PulsarSignals
- Screener output: pmcc_quality.py run 2026-10-12

*Not investment advice. Model estimates labeled as such.*
