# Screener Guide: Capabilities, Relationships & Value

This document describes every screener in the system, what each does, how they relate to each other, the value each adds, and how to harvest that value.

## Screener Inventory

| Screener | File | Purpose | Runs When |
|----------|------|---------|-----------|
| Stock Screener | `src/stock_screener.py` | Technical analysis + regime detection | Daily 9:45am ET |
| Spread Screener | `src/spread_screener.py` | 34 options strategies pricing | Daily 9:45am ET |
| High-IV Screener | `src/iv_premium_screener.py` | Deep OTM put selling opportunities | Daily 9:45am ET |
| PMCC Quality | `src/pmcc_quality.py` | PMCC pair quality ranking | Daily 9:45am ET |
| Premarket | `src/premarket_screen.py` | Gap + opening range signals | 9:00am ET |
| Intraday | `src/intraday_screen.py` | Momentum (ORB, VWAP) | 11am, 2pm ET |
| Decision Engine | `src/decision_engine.py` | Ranks candidates, regime routing | Daily 9:45am ET |
| Compare | `src/compare.py` | Side-by-side / leaderboard | On demand |

## 1. Stock Screener (`src/stock_screener.py`)

**Capability:** Screens a watchlist on technical gates computed from 1 year of daily bars. Detects trend regime (UP/DN/RNG), computes RSI, ATR, Bollinger, SMA distances, volume ratios. Ranks survivors by composite score.

**Gates:** Price, volume, trend alignment, volatility filters (see `gates.yaml`).

**Value:** Filters 100+ names down to technically qualified candidates. The regime label (UP/DN/RNG) drives the entire downstream strategy routing — without it, the spread screener doesn't know which strategies fit.

**How to harvest:** Read the "Verdict" column (Go/Watch/Pass). "Go" names proceed to spread screening. The regime determines which strategies the Decision Engine will consider.

**Relationships:**
- **Feeds →** Spread Screener (provides qualified symbols + regime)
- **Feeds →** Decision Engine (regime for strategy routing)
- **Feeds →** Compare (universe for leaderboard)

## 2. Spread Screener (`src/spread_screener.py` + `src/exotics.py`)

**Capability:** Prices 34 options strategies across 21–60 DTE. Two-stage: GATE (reject bad quotes, illiquid, event conflicts) then RANK (by return on risk).

**Strategies (34):**
- **Defined-risk core (21):** Bull/bear verticals, iron condors/butterflies, calendars, long butterflies, covered calls, cash-secured puts, straddles/strangles, naked puts/calls (with warnings), ratio spreads
- **Exotics (13, #107):** Call/put backspreads, broken-wing butterflies, inverse broken wings, call/put ladders, Jade Lizards (proper + reverse), synthetic futures, combos/risk-reversals, strips/straps, guts, double diagonals

**Value:** Turns qualified stocks into priced, ranked trade structures with conservative fills (short bid − long ask), Win% estimates, EV calculations, and Lucrative verdicts. Every rejection carries a reason — nothing silently dropped.

**How to harvest:** Sort by EV$ → Win% → RoR. "Lucrative" (70%+ Win, +EV, ≤3× loss) are highest-conviction. Check "Events" column for earnings conflicts.

**Relationships:**
- **Consumes ←** Stock Screener (symbols + regime)
- **Feeds →** Decision Engine (priced structures)
- **Feeds →** Compare (structures for leaderboard)
- **Uses:** `src/exotics.py` for exotic evaluators, `src/options_chain.py` for chain parsing

## 3. High-IV Screener (`src/iv_premium_screener.py`)

**Capability:** Finds deep OTM put-selling opportunities: strikes ≤60% of spot, 30/60/90 DTE windows, ranked by implied volatility (richest premium first).

**Value:** Answers "where can I sell deep OTM puts with good premium?" — a different question than the spread screener. Targets high-IV names (often leveraged ETFs) where premium is rich relative to the distance OTM.

**How to harvest:** Top of the list = highest IV at deep OTM strikes. Check Win% column (should be very high given the distance). Best for income generation on high-vol underlyings.

**Relationships:**
- **Standalone:** Doesn't depend on stock screener (uses its own universe, typically `lev_etf`)
- **Feeds →** `src/render_iv_premium.py` for HTML output (#115)

## 4. PMCC Quality Screener (`src/pmcc_quality.py`)

**Capability:** Ranks PMCC (Poor Man's Covered Call) pairs: LEAPS (0.80–0.95Δ, 270–800 DTE) + short calls (0.15–0.35Δ, 21–60 DTE). Ranks by premium-to-debit ratio (30d normalized).

**Value:** Identifies capital-efficient long-term bullish positions. The LEAPS provides leveraged upside; the short calls generate income against it.

**How to harvest:** Top-ranked pairs have the best income-to-capital ratio. Check the short call's delta (should be 0.15–0.35) and the LEAPS delta (0.80–0.95).

**Relationships:**
- **Feeds →** `src/recommendation_analyzer.py` (comprehensive PMCC analysis with technicals + fundamentals)
- **Related:** `src/pmcc_watch.py` (daily exception monitoring), `src/pmcc_value.py`, `src/pmcc_etf.py`

## 5. Premarket Screener (`src/premarket_screen.py`)

**Capability:** Gap and opening-range analysis at 9:00am ET. Computes gap %, ATR-normalized gap, VWAP distance, relative volume.

**Value:** Catches overnight movers before the open. Gap + volume + ATR context tells you if the move is significant or noise.

**How to harvest:** Large |gap|/ATR% with high relative volume = meaningful move. Use for day-trade watchlist or to avoid opening new swing positions into volatility.

**Relationships:**
- **Standalone:** Runs before market open, independent of daily screeners
- **Feeds →** Day-trade decisions (not the income framework)

## 6. Intraday Screener (`src/intraday_screen.py`)

**Capability:** Momentum signals at 11am and 2pm ET: Opening Range Breakout (ORB), VWAP reclaim/loss, time-prorated relative volume.

**Value:** Mid-session momentum confirmation. ORB breakouts with volume confirmation are higher-probability than premarket gaps alone.

**How to harvest:** ORB breakout + VWAP reclaim + RVOL ≥1.5 = strongest signal. Use for intraday entries or to confirm daily screener candidates.

**Relationships:**
- **Standalone:** Intraday timing, separate from daily income process

## 7. Decision Engine (`src/decision_engine.py`)

**Capability:** Six-step advisory engine. Reads stock + spread screener output, applies regime routing (UP→bullish strategies, DN→bearish, RNG→neutral), ranks by EV, applies Kelly sizing (when available), checks ledger for position limits.

**Regime Routing (#106):**
- **UP:** Bull puts, bull calls, covered calls, CSPs, naked puts, call backspreads, Jade Lizards, synthetic longs
- **DN:** Bear calls, bear puts, naked calls, put backspreads, reverse Jade Lizards, synthetic shorts
- **RNG:** Iron condors/butterflies, calendars, straddles/strangles, broken wings, ladders, guts, double diagonals

**Value:** Turns raw screener output into actionable recommendations. The regime router ensures you don't get bearish strategies for bullish stocks (and vice versa).

**How to harvest:** Read the decision report. It shows top candidates per regime with sizing guidance. "No trade" is a valid output.

**Relationships:**
- **Consumes ←** Stock Screener (regime), Spread Screener (priced structures), Ledger (position limits)
- **Feeds →** Daily report, "Why No Trade Today" log

## 8. Compare (`src/compare.py`)

**Capability:** Side-by-side analysis for two symbols, or leaderboard across a universe. Four views: bullish, bearish, neutral, directional.

**Value:** Answers "which has the better setup?" using the screener's own data — never invented numbers.

**How to harvest:** Use for final selection when multiple candidates pass. The leaderboard view ranks an entire universe.

**Relationships:**
- **Consumes ←** Stock + Spread screener output
- **Feeds →** `src/render_compare.py` → `docs/compare.html`

## Capability Interaction Map

```
                    ┌─────────────────┐
                    │  Stock Screener │
                    │ (regime, score) │
                    └────────┬────────┘
                             │
              ┌──────────────┼──────────────┐
              ▼              ▼              ▼
    ┌─────────────┐ ┌──────────────┐ ┌────────────┐
    │   Spread    │ │    PMCC      │ │  Compare   │
    │  Screener   │ │   Quality    │ │(leaderboard)│
    │(34 strategies)│ │            │ └────────────┘
    └──────┬──────┘ └──────┬───────┘
           │               │
           └───────┬───────┘
                   ▼
          ┌────────────────┐
          │ Decision Engine│
          │(regime routing)│
          └───────┬────────┘
                  ▼
          ┌────────────────┐
          │ Daily Report   │
          │  + Why No Trade│
          └────────────────┘

    ┌──────────────┐  ┌──────────────┐  ┌──────────────┐
    │ High-IV      │  │ Premarket    │  │  Intraday    │
    │ (standalone) │  │ (standalone) │  │ (standalone) │
    └──────────────┘  └──────────────┘  └──────────────┘
```

## Value Chain: How $10M Capital Harvests This

1. **Universe → Candidates:** Stock screener filters 100+ names to technically qualified set with regime labels
2. **Candidates → Structures:** Spread screener prices 34 strategies per name, ranks by risk-adjusted return
3. **Structures → Recommendations:** Decision engine routes by regime, applies sizing, checks portfolio limits
4. **Recommendations → Action:** Human reviews, confirms, executes (never automated)
5. **Action → Learning:** Ledger tracks P&L, backtester validates edge, gates calibrate

The system is a **funnel**: wide at the top (100+ names), narrow at the bottom (0–5 actionable trades, often zero). Zero is a valid output — the system vetoes more than it recommends.

## Data Providers by Screener

| Screener | Market Data | Fundamentals | Earnings |
|----------|-------------|--------------|----------|
| Stock | Public MCP (bars) | — | — |
| Spread | Public MCP (chains, greeks) | — | Nasdaq API |
| High-IV | Public MCP (chains) | — | — |
| PMCC | Public MCP (chains) | Finnhub (via analyzer) | Nasdaq API |
| Premarket | Public MCP (quotes) | — | — |
| Intraday | Public MCP (bars) | — | — |

See issue #118 for full data provider inventory.
