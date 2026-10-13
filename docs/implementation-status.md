# Options framework implementation status

**Reviewed:** 2026-10-13
**Repository revision:** `main` at `c268d8d` (PR #40 merged)

The complete framework with section-by-section status, rationale, and
prioritized remaining work is in the
[comprehensive framework assessment](comprehensive-options-market-analysis-framework.md).

## Summary

Amuse implements a capable options screening and paper-risk workflow. With
PR #40 included, a reasonable summary rating is **about 50% implemented**.
This is a qualitative judgment about breadth and integration, not a count of
checklist items. Core screening is strongest; pricing utilities, portfolio
risk calculations, and an advisory decision engine now exist, while live data
integration, calibration, and out-of-sample profitability evidence remain
limited or absent. This describes current `main` after PR #40 merged. The
percentage remains a qualitative breadth/integration estimate, not a return
measurement.

| Framework area | Status | What the repository supports |
|---|---|---|
| Technical analysis and regime/timing | **Mostly implemented** | Daily and intraday signals include trend, moving averages, RSI, Bollinger %B, VWAP, ATR, pivots/Fibonacci, gaps, relative volume, and opening-range logic. |
| Options opportunity signals | **Partly implemented** | Delta-based strike selection, provider Greeks, IV versus historical volatility, IV rank from accumulated snapshots, skew, term structure, plus reusable Black–Scholes and expected-move calculations. Pricing is not yet an independently calibrated candidate-ranking signal. No order-flow imbalance or systematic sentiment/cross-asset signals. |
| Catalyst information | **Partly implemented** | News headlines can be fetched and shown in reports. The premarket signal itself remains technical; there is no comprehensive, structured catalyst calendar or fundamental-data feed. |
| Strategy pricing and entry filters | **Mostly implemented** | Defined-risk spreads and condors, plus PMCC pairs, with conservative bid/ask assumptions, liquidity/friction/event gates, DTE and delta bands, max loss, breakeven, and return-on-risk ranking. |
| Unified decision synthesis | **Partly implemented** | PR #40 adds an advisory engine joining regime, horizon/events, timing, volatility, spread economics, and risk/sizing into ranked WATCH/CONSIDER/NO TRADE output. Daily runs lack an account/ledger by default, so they cannot size positions. |
| Position sizing and book risk | **Partly implemented** | Existing ledger sizing and heat gates remain; PR #40 adds open-ledger Greeks and five model-based scenarios given current market context. No scheduled live-book feed, sector/correlation model, or automatic concentration check. |
| Exits and management | **Partly implemented** | Mechanical exit evaluation is implemented for bull put spreads only. Other strategies do not have complete automated exit policies. |
| Valuation, performance, and learning | **Partly implemented** | PR #40 adds European Black–Scholes pricing/Greeks, expected move, and fractional Kelly utility. Kelly requires 30 realized trades per strategy and an account value; inputs are not out-of-sample validated. No options backtester or attribution loop. |

## Impact interpretation

PR #40's benefits are currently **process and risk-control benefits**, not
proven trading returns. Measure economic impact prospectively from recorded
recommendations, paper fills, fees/slippage, and outcomes by strategy and
regime. Implementation completion is not evidence of positive edge. The full
rationale, impact measures, caveats, and staged roadmap are in the
[comprehensive framework assessment](comprehensive-options-market-analysis-framework.md).

## Material differences from the proposed framework

- The configured exit time threshold is **7 DTE**, not 21 DTE. The 50%-of-credit profit target and 2×-credit stop are configured for bull put spreads.
- Volatility gates use **IV rank above 50 plus IV above realized volatility** to label premium rich, and IV rank below 25 to stand down. The spread screener consumes this assessment; the PMCC screen does not.
- PR #40 adds portfolio Greek aggregation and a five-scenario model stress report when the user supplies an open ledger and current market context; this is not yet scheduled or backed by a canonical live-book feed.
- News headlines are available in reports, but they do not amount to an event-aware catalyst model. The premarket screen documents that it does not use news to classify gaps.
- Screen win-probability/EV remain delta-derived proxies. PR #40 adds Black–Scholes utilities, but does not yet calibrate model marks against executable quotes or backtest historical options performance.

## Main gaps to close

1. Operationalize the new decision and portfolio-risk tools with timestamped
   market/ledger inputs, decision/outcome logging, and data-freshness checks.
2. Add validated sector/correlation concentration analysis and use scenario
   stress results alongside (not in place of) the existing heat cap.
3. Expand strategy-specific management rules beyond bull put spreads, while
   keeping configured thresholds explicit.
4. Add a research and validation layer: historical options data or documented
   price synthesis, backtesting, and attribution by signal/strategy. Measure
   prices, expected-move coverage, fill friction, net expectancy, and drawdown
   before claiming a profitability benefit or enabling Kelly sizing.
5. Add missing analytical lenses where data supports them: order flow,
   sentiment/crowding, and cross-asset relationships; calibrate the new
   expected-move/pricing utilities. Treat Kelly as research until expectancy
   is validated.
6. Distinguish headline display from structured event coverage; add dependable
   earnings, dividend/ex-date, and catalyst data before using those events as
   automated gates.

## Sources in this repository

The assessment is based on `src/` code/configuration, particularly
`src/spread_screener.py`, `src/pmcc_quality.py`, `src/vol.py`, `src/exits.py`,
`src/ledger.py`, `src/options_math.py`, `src/portfolio_risk.py`, and
`src/decision_engine.py`, plus workflows and README. Recheck the projected PR
state after merge and as impact data accumulates.
