# Amuse Stock & Options Screening System: Criteria, Rules, Formulas, Strategies, Gaps, and Industry Comparison

**Document Version:** 1.0.0
**Target File:** `docs/architecture/business/amuse-logic.md`
**Repository:** `openaimp/amuse`
**Scope:** Architectural and Business Logic Assessment of Options & Stock Screening Engine

---

## Executive Summary & System Operating Discipline

The `amuse` repository (Options Lab) is an automated stock and options screening, monitoring, and decision-support engine. It retrieves live market data via Public.com's hosted MCP server and enforces a strict quantitative operating philosophy:

> **"No indicator places a trade. Every signal answers exactly one question, and a trade only happens when they all agree."**

The system operates across a 6-stage decision pipeline:

```
[ Screen ] ──> [ Regime ] ──> [ Timing ] ──> [ Strikes ] ──> [ Size ] ──> [ Preflight ]
 (Find)         (Strategy)     (Entry)       (Structure)    (Risk)        (Execute)
```

1. **Screen**: Which names meet baseline liquidity, price, and volatility thresholds?
2. **Regime**: Is the underlying in an Bullish (`UP`), Bearish (`DN`), or Neutral (`RNG`) regime? Which strategy family fits?
3. **Timing**: Is the entry current, extended (`%B > 1.0`), in a squeeze, or gapping?
4. **Strikes**: Where do option structure legs sit based on deltas ($0.10 - 0.20\Delta$ short spreads, $0.15 - 0.35\Delta$ PMCC short calls) and technical pivots / Fibonacci levels?
5. **Size**: How much capital is at risk? Max loss per structure gated at $\le \$1,000$ (spreads) or $\le \$10,000$ (PMCC), with account-level Kelly / heat caps (2% trade risk, 35% total open heat).
6. **Preflight**: Binary event gates (earnings, dividends) and human execution verification.

---

## 1. Inventory of Screening Criteria, Rules, Formulas & Strategies

### 1.1 Technical & Stock Screener (`src/stock_screener.py`, `src/indicators.py`)

The technical screener evaluates equity daily bar history (minimum 200 bars) across a 0–40 composite score scale (Base Score 0–30 + Signal Score 0–10).

#### Technical Indicators & Formulas
- **RSI (14)**:
  $$\text{RSI} = 100 - \frac{100}{1 + \frac{\text{EMA}(\text{Gain}, 14)}{\text{EMA}(\text{Loss}, 14)}}$$
  - *Readings*: $< 30$ Oversold, $> 70$ Overbought, $30-70$ Neutral.
- **Bollinger Bands (20, 2.0)**:
  $$\text{Middle} = \text{SMA}(P, 20), \quad \text{Upper/Lower} = \text{Middle} \pm 2.0 \times \sigma_{20}$$
  $$\%B = \frac{P - \text{Lower}}{\text{Upper} - \text{Lower}}$$
  - *Gate*: $\%B \in [0.0, 1.0]$. $\%B > 1.0$ flags overextended price ("don't chase").
  - *Squeeze*: Bandwidth ($\frac{\text{Upper} - \text{Lower}}{\text{Middle}}$) at $N$-day minimum ($N=125$).
- **Anchored VWAP (52-week low)**:
  $$\text{AVWAP} = \frac{\sum (P_i \times V_i)}{\sum V_i} \quad \text{from 52-week low bar}$$
  - *Gate*: Price must be above Anchored VWAP (`require_above_anchored_vwap: true`).
- **Moving Averages & Golden/Death Cross**:
  - $SMA_{50} > SMA_{200}$ required; recent Death Cross within 20 sessions rejects.
- **Fractal Pivots ($n=5$) & Fibonacci Retracements**:
  - High/Low pivot identified if $P_t$ is extreme compared to $n$ bars before and after.
  - Fib levels computed at $38.2\%, 50.0\%, 61.8\%$ of reference 6-month swing.
- **HH/HL Trend Structure & Regime Classification**:
  - `UP` (Uptrend): Higher Highs + Higher Lows.
  - `DN` (Downtrend): Lower Highs + Lower Lows (Hard rejection for bullish selling).
  - `RNG` (Range/Mixed): Neither strict UP nor DN.

#### 6-Vote Bias Composite Score
Evaluates 6 binary votes (1 point each):
1. $P > SMA_{50}$
2. $P > SMA_{200}$
3. $SMA_{50} > SMA_{200}$
4. $\text{MACD line} > 0$
5. $\text{RSI}_{14} > 50$
6. Pivot structure is `UP`
- **Bias Read**: $\ge 4$ Bullish, $\le 2$ Bearish, 3 Neutral.

---

### 1.2 Options Spread & Exotic Screener (`src/spread_screener.py`, `src/exotics.py`)

Prices 34 options strategies across 21–60 DTE with conservative fill estimation (**short leg bid $-$ long leg ask**).

#### Auto Width Scaling Formula
Spread width auto-scales according to underlying spot price $S$:
$$\text{Width} = \min\left(5.0, \max\left(1.0, \text{round}\left(\frac{S}{25}\right)\right)\right)$$

#### Expected Value (EV) & Delta-based Win% Formulas
$$\text{Win\%}_{\text{est}} = 1.0 - |\Delta_{\text{short}}|$$
$$\text{EV} = P(\text{Win}) \times \text{Credit}_{\text{net}} - P(\text{Loss}) \times \text{MaxLoss} - \text{Friction}$$
$$\text{Friction} = \frac{\sum (\text{Ask}_i - \text{Bid}_i)}{\text{Credit}_{\text{net}}} \quad (\text{Gate}: \text{Friction} \le 3.0)$$

#### Strategy Classification Matrix (34 Strategies)

| Family | Strategy Name | Legs & Selection Rules | Market Regime / Fits |
|---|---|---|---|
| **Defined-Risk Core** | Bull Put Spread | Short Put $0.10 - 0.20\Delta$, Long Put 1 width lower | Bullish / UP |
| | Bear Call Spread | Short Call $0.10 - 0.20\Delta$, Long Call 1 width higher | Bearish / DN |
| | Iron Condor | Bull Put Spread + Bear Call Spread | Neutral / RNG |
| | Asymmetric Condor | Bull Put Spread + Call wing $\ge 8\%$ OTM | Bullish tilt |
| | Iron Butterfly | ATM Short Call + Short Put, OTM Long Wings | Low Vol / Range |
| | Credit Calendar Spread | Sell Near DTE / Buy Far DTE at same strike | Vol expansion / Range |
| | Long Butterfly | Buy 1 Low, Sell 2 ATM, Buy 1 High | Target Price / Pin |
| | Covered Call | Long 100 shares + Short Call $0.15 - 0.35\Delta$ | Mildly Bullish |
| | Cash-Secured Put | Short Put $0.10 - 0.20\Delta$ collateralized | Neutral to Bullish |
| | Jade Lizard | Bull Put Spread + Far-OTM Short Call (Call wing $\ge 8\%$ OTM) | Bullish / No upside risk if Credit > Call width |
| | Reverse Jade Lizard | Bear Call Spread + Far-OTM Short Put | Bearish / No downside risk |
| **Exotics & Ratio Spreads** | Call Backspread | Sell 1 ITM/ATM Call, Buy 2 OTM Calls | Aggressive Bullish / Vol Breakout |
| | Put Backspread | Sell 1 ITM/ATM Put, Buy 2 OTM Puts | Aggressive Bearish / Crash |
| | Ratio Call Spread | Buy 1 OTM Call, Sell 2 Far-OTM Calls | Mild Bullish with Cap |
| | Ratio Put Spread | Buy 1 OTM Put, Sell 2 Far-OTM Puts | Mild Bearish with Cap |
| | Broken-Wing Butterfly | Asymmetric wing widths (e.g. +1 / -2 / +1 with wider upper wing) | Directional / Zero upside risk |
| | Call / Put Ladders | 3-leg combinations (e.g., +1 / -1 / -1) | High conviction directional |
| | Synthetic Futures | Long ATM Call + Short ATM Put (or vice versa) | Full Delta Directional |
| | Risk Reversal / Combo | Short OTM Put + Long OTM Call | Directional Leverage |
| | Straddle / Strangle | Long or Short ATM/OTM Call + Put pairs | Volatility Play |
| | Guts Spread | ITM Call + ITM Put | Deep Premium Capture |
| | Double Diagonal | Diagonal Call + Diagonal Put | Multi-expiry Range |

---

### 1.3 Poor Man's Covered Call (PMCC) Screener (`src/pmcc_quality.py`, `src/pmcc_watch.py`)

Evaluates LEAPS x Short Call pairs as structured replacement for covered calls.

#### Selection Rules & Gates
- **LEAPS Long Call**: DTE 270–800, Delta $0.80 - 0.95$, Open Interest / Volume $\ge 25$.
- **Near-term Short Call**: DTE 21–60, Delta $0.15 - 0.35$, Open Interest / Volume $\ge 10$.
- **Capital Gate**: Max debit per pair $\le \$10,000$.
- **Friction Gate**: $\frac{\text{Spread}_{\text{long}} + \text{Spread}_{\text{short}}}{\text{Bid}_{\text{short}}} \le 3.0$.
- **Breach Distance Gate**: Short strike must be $\ge 8\%$ above spot or LEAPS breakeven.
- **30-Day Premium-to-Debit Yield Metric**:
  $$\text{Yield}_{30d} = \frac{\text{Credit}_{\text{short}}}{\text{Debit}_{\text{LEAPS}}} \times \left(\frac{30}{\text{DTE}_{\text{short}}}\right) \ge 4.0\%$$

---

### 1.4 Pre-Market & Intraday Screeners (`src/premarket_screen.py`, `src/intraday_screen.py`)

#### Pre-Market Momentum
- **Gap Gate**: $|\text{Gap}\%| = \left|\frac{P_{\text{pre}} - P_{\text{close, prev}}}{P_{\text{close, prev}}}\right| \ge 2.0\%$.
- **Relative Volume (RVOL)**: Time-bucket prorated volume comparison vs 20-day average ($\ge 1.5\times$).
- **Developing Session VWAP**: Price above VWAP $\rightarrow$ Gap-and-Go; Price below VWAP $\rightarrow$ Fade Risk.
- **ATR% Gate**: $\text{ATR}\% \in [1.0\%, 8.0\%]$.

#### Intraday Opening-Range Breakouts (ORB)
- **15-Minute Opening Range**: Tracks High ($OR_{H}$) and Low ($OR_{L}$) from 09:30–09:45 ET.
- **Breakout Trigger**: Price clears $OR_H \times (1 + 0.001)$ with time-prorated RVOL $\ge 1.5\times$.
- **VWAP Confirmation**: Price holding above Session VWAP for $\ge 70\%$ of completed 15-min bars.

---

### 1.5 Volatility Framework (`src/vol.py`)

Evaluates implied vs realized volatility and term structure before selling options.

#### Formulas
- **Realized / Historical Volatility (HV)**:
  $$\text{HV}_{20/60} = \sqrt{252} \times \sigma\left(\ln\frac{P_t}{P_{t-1}}\right)$$
- **IV Rank (IVR)**:
  $$\text{IVR} = 100 \times \frac{\text{IV}_{\text{current}} - \text{IV}_{\min, 52w}}{\text{IV}_{\max, 52w} - \text{IV}_{\min, 52w}}$$
- **25-Delta Skew**:
  $$\text{Skew}_{25} = \text{IV}_{\text{Put}, 25\Delta} - \text{IV}_{\text{Call}, 25\Delta}$$
- **Term Structure**:
  $$\text{Term} = \text{IV}_{\text{Far}} - \text{IV}_{\text{Near}}$$

#### Decision Rules
- $\text{IVR} > 50$ **and** $\text{IV} > \text{HV}$ $\rightarrow$ **`SELL_PREMIUM`** (Options rich, edge to seller).
- $\text{IVR} < 25$ $\rightarrow$ **`STAND_DOWN`** (Options cheap; veto short-premium trades).
- Otherwise $\rightarrow$ **`NO_READ`** (Default to technical/options gates).

---

### 1.6 Risk Management, Ledger, Exit Policy & Portfolio Risk

- **Bull Put Exit Policy (`src/exits.py`, `src/position_manager.py`)**:
  - **Profit Target**: Close at $50\%$ of max credit captured.
  - **Stop Loss**: Close when buy-to-close cost reaches $2.0\times$ credit received.
  - **Time Exit**: Mandatory exit or roll at $7 \text{ DTE}$.
  - **Assignment Protection**: Close at $\le 2 \text{ DTE}$ if ITM; no physical assignment allowed.
- **Sizing & Portfolio Rules (`src/ledger.py`, `src/options_math.py`)**:
  - **Trade Risk Gate**: Max loss $\le 2\%$ of account net liquidation value per position.
  - **Heat Cap Gate**: Total open max loss $\le 35\%$ of account equity.
  - **Fractional Kelly Sizing**:
    $$f^* = \frac{p \cdot b - (1 - p)}{b} \times \text{Fraction} \quad (p = \text{Win\%}, b = \frac{\text{Credit}}{\text{MaxLoss}})$$
    Requires $\ge 30$ completed trades in history before sizing is unlocked.
- **Portfolio Risk & Black-Scholes Greeks (`src/portfolio_risk.py`, `src/options_math.py`)**:
  - Standard European Black-Scholes pricing for Delta, Gamma, Vega, Theta, Rho.
  - Stress tests portfolio across 5 spot/volatility scenarios ($\pm 5\%, \pm 10\%$ spot, $\pm 25\%$ IV).
  - Enforces 30-minute freshness window on quote/IV inputs.

---

## 2. Comprehensive Inventory of Gaps, Bottlenecks, Needed Improvements & Consolidation

Despite its technical breadth, a rigorous audit reveals several architectural, data, and algorithmic gaps within `amuse`:

### 2.1 Code Duplication & Fragmentation

1. **Duplicated Option Pricing Logic**:
   - `spread_screener.py`, `exotics.py`, `iv_premium_screener.py`, `pmcc_quality.py`, `pmcc.py`, `pmcc_etf.py`, and `pmcc_value.py` each reimplement distinct loops for parsing OSI symbols, calculating leg spreads, checking bid/ask width, and estimating conservative fills.
   - *Improvement*: Consolidate all option pricing and fill math into `src/options_chain.py` or a unified `src/pricing_engine.py`.
2. **Redundant PMCC Pricers**:
   - `src/pmcc.py`, `src/pmcc_etf.py`, and `src/pmcc_value.py` are early legacy scripts superseded by `src/pmcc_quality.py`. They clutter the codebase and cause confusion.
   - *Improvement*: Formally deprecate or archive legacy `pmcc*.py` files into an `archive/` folder.
3. **Report Render Fragmentation**:
   - `render_report.py` is over 2,300 lines of monolithic HTML builder code containing HTML strings for stock, spreads, PMCC, premarket, intraday, and decision sections.
   - *Improvement*: Refactor `render_report.py` into modular component renderers under `src/renderers/`.

### 2.2 Data Feed & API Limitations

1. **Zero Fundamental Data**:
   - Public.com MCP provides no Market Cap, P/E ratio, PEG, Revenue growth, Profit Margin, Debt/Equity, or Dividend yield.
   - The "Value" column in `stock_screener.py` is strictly a 52-week price range percentage ($\frac{P - L_{52}}{H_{52} - L_{52}}$), which can misguide traders looking for true fundamental value.
   - *Improvement*: Integrate an external open data source (e.g., Financial Modeling Prep, SEC EDGAR, or Yahoo Finance API) for fundamental filtering.
2. **Missing Real-Time Catalyst / Earnings Calendar Integration**:
   - Earnings gates in screeners rely on local static JSON files (`src/earnings_dates.json`) or flag missing data as "unknown date".
   - *Improvement*: Connect `update_earnings.py` to a reliable automated API feed (e.g., Zacks or Nasdaq calendar) with verified timestamps.
3. **Point-In-Time IV Rank Cold-Start Problem**:
   - Public MCP has no endpoint for historical IV. `vol.py` relies on forward-recording daily snapshots (`record_snapshot`) and requires 30 days before trusting IV Rank.
   - *Improvement*: Implement an IV proxy using 30-day historical volatility ($\text{HV}_{30}$) or integrate historical options data from LEAN / Tastytrade / ORATS.

### 2.3 System Integration & Execution Gaps

1. **Un-integrated Volatility Veto in PMCC**:
   - `vol.py` vetoes low-vol short premium in `spread_screener.py` (`STAND_DOWN`), but is **not** wired into `pmcc_quality.py`.
   - *Improvement*: Wire `vol.py` directly into `pmcc_quality.py` to prevent entering PMCC LEAPS when implied volatility is excessively deflated or inflated.
2. **Manual Portfolio Risk Workflow**:
   - `portfolio_risk.py` and `portfolio_context.py` require manual execution with local JSON inputs; they do not run automatically in scheduled GitHub Actions workflows because CI lacks account context.
   - *Improvement*: Build an automated paper-ledger context runner that runs portfolio risk stress-testing in the daily pipeline.
3. **No Intraday Options Exit Management**:
   - Intraday and pre-market screeners operate on equity bars only. There is no intraday options chain stream or intraday delta/gamma exit tracking.

---

## 3. Industry Benchmarking: Comparative Analysis against Leading Screeners

The table below benchmarks `amuse` against industry-standard platforms across key capabilities:

| Feature / Capability | `openaimp/amuse` | OptionStrat | Tastytrade / Tastyworks | MarketChameleon | Barchart / OptionAlpha | ThinkorSwim (TOS) |
|---|---|---|---|---|---|---|
| **Technical Screening** | ✅ High (RSI, %B, VWAP, Anchored VWAP, Fibs, Pivots) | ⚠️ Basic (Simple Trend/MA) | ⚠️ Basic (IV Rank, Liquidity) | ✅ High (Technical + Vol) | ✅ High (Custom Indicators) | ✅ Industry Standard (thinkScript) |
| **Options Strategy Coverage** | ✅ 34 Strategies (Defined-Risk + Exotics) | ✅ Complete (Visual Optimizer) | ✅ High (Standard Spreads) | ✅ High (Mispriced Options) | ✅ Automated Bots / Flow | ✅ Infinite (Custom Spreads) |
| **Fundamental Screening** | ❌ None (Technical Range proxy only) | ❌ None | ⚠️ Basic (Market Cap, Earnings) | ✅ Deep (Earnings, Financials) | ✅ High (Valuation metrics) | ✅ High (Company Profile) |
| **Vol Analysis (IVR / Skew)** | ⚠️ Point-in-time IVR, 25Δ Skew, HV | ✅ Real-time IV Percentile | ✅ IV Rank / IV Percentile | ✅ Skew Index, Vol Surface | ✅ IV Rank, Historical IV | ✅ Complete Vol Surface |
| **Order Flow & Institutional Data** | ❌ None | ❌ None | ❌ None | ✅ Deep (Unusual Options, Dark Pool) | ✅ High (Options Flow) | ✅ High (Time & Sales, Depth) |
| **Backtesting Engine** | ⚠️ Tastytrade API integration (#111) | ❌ None | ⚠️ Historical Lookback | ✅ High (10-yr Event Backtest) | ✅ Complete Event-Driven Engine | ✅ thinkBack / OnDemand |
| **Automated Portfolio Risk** | ⚠️ B-S Scenarios (Manual JSON) | ⚠️ Visual Net Greeks | ✅ Real-time Portfolio Beta-Weighted Delta | ✅ Portfolio Risk Stress | ✅ Bot Portfolio Limits | ✅ Portfolio Margin / Risk Graph |

---

## 4. Key Areas to Add, Enhance & Roadmap

To bring `amuse` to parity with leading institutional and retail screeners, the following criteria, strategies, and architectural components should be added:

### 4.1 Missing Screening Criteria & Metrics to Add

1. **Fundamental Filters**:
   - **Market Cap**: Minimum cutoff ($\ge \$2\text{B}$) to filter out illiquid micro-caps.
   - **Earnings Yield / P/E Ratio**: Avoid selling put spreads on fundamentally overvalued bubble stocks.
   - **Free Cash Flow Yield & Debt-to-Equity**: Fundamental solvency filters for PMCC underlying selection.
2. **Advanced Volatility & Skew Metrics**:
   - **IV Percentile (IVP)**: Percentage of days in the past year where IV was lower than current IV (more robust against outliers than IV Rank).
   - **Volatility Smirk / Skew Slope**: Slope of IV across deltas ($\frac{\text{IV}_{20\Delta \text{Put}} - \text{IV}_{20\Delta \text{Call}}}{\text{IV}_{\text{ATM}}}$) to identify crash-hedging demand.
   - **VIX / Broad Market Regime Overlay**: VIX term structure (Contango vs Backwardation) to scale overall portfolio exposure.
3. **Options Order Flow & Sentiment Criteria**:
   - **Unusual Option Volume Ratio**: $\frac{\text{Option Volume}_{\text{today}}}{\text{Option Volume}_{30d \text{ avg}}}$.
   - **Put/Call Open Interest Ratio**: Sentiment read on underlying positioning.
   - **Earnings Expected Move vs Historical Crush**: Compare market-implied earnings move ($S \times \text{ATM Straddle}$) against actual post-earnings 1-day historical moves over the last 8 quarters.

### 4.2 Missing Options Strategies to Add

1. **Diagonal Calendar Spreads & Ratio Diagonals**:
   - Sell near-term OTM option, buy longer-term ITM/OTM option at a different strike (flexible PMCC variant for bearish or neutral regimes).
2. **Collar & Costless Collar**:
   - Long Stock + Long OTM Put + Short OTM Call (financed downside protection for long equity portfolios).
3. **Iron Calendar / Iron Diagonal**:
   - Combination of OTM Put Calendar + OTM Call Calendar for low-IV range-bound regimes.
4. **The Wheel Strategy Orchestration**:
   - Automated lifecycle manager: Cash-Secured Put $\rightarrow$ Assignment $\rightarrow$ Covered Call $\rightarrow$ Call Exercise.

### 4.3 Advanced System & Architectural Roadmap

1. **Consolidated Option Pricing Core (`src/pricing_engine.py`)**:
   - Single point of truth for multi-leg pricing, conservative fill rules, friction calculation, and Greek aggregation.
2. **Adoption of FOSS Quantitative Libraries**:
   - Integrate `py_vollib` / `QuantLib` for pricing/Greeks validation.
   - Integrate `arch` for GARCH-based volatility forecasting.
   - Integrate `quantstats` / `empyrical` for paper ledger tear-sheet reporting (Sharpe ratio, Sortino ratio, max drawdown).
3. **Full Volatility Veto Integration**:
   - Connect `vol.py` across **all** strategy screeners (`pmcc_quality.py`, `exotics.py`, `iv_premium_screener.py`).
4. **Automated Event-Driven Backtesting**:
   - Expand `tastytrade_backtest.py` or integrate `Optopsy` / `LEAN` for historical validation of rules in `gates.yaml`.

---

## 5. Summary & Recommendation

The `openaimp/amuse` system possesses an exceptionally clear, rule-based design grounded in disciplined operating stages and defined-risk income strategies. By consolidating duplicated pricing modules, integrating external fundamental/earnings feeds, expanding volatility metrics (IVP, Skew), and implementing automated portfolio risk execution, `amuse` can achieve parity with top-tier commercial screening platforms.
