# Options framework implementation status

**Reviewed:** 2026-10-13
**Repository revision:** `2d060e9` (`origin/main` at review time)

The complete framework with section-by-section status, rationale, and
prioritized remaining work is in the
[comprehensive framework assessment](comprehensive-options-market-analysis-framework.md).

## Summary

Amuse implements a capable options screening and paper-risk workflow. It does
not yet implement the unified, portfolio-level decision framework described in
the Comprehensive Options & Market Analysis Framework. A reasonable summary
rating is **about 45% implemented**. This is a judgment about breadth and
integration, not a count of checklist items: core screening and defined-risk
pricing are strong, while portfolio analytics, formal valuation, and
out-of-sample validation are largely absent.

| Framework area | Status | What the repository supports |
|---|---|---|
| Technical analysis and regime/timing | **Mostly implemented** | Daily and intraday signals include trend, moving averages, RSI, Bollinger %B, VWAP, ATR, pivots/Fibonacci, gaps, relative volume, and opening-range logic. |
| Options opportunity signals | **Partly implemented** | Delta-based strike selection, Greeks from the market-data provider, IV versus historical volatility, IV rank from accumulated snapshots, skew, and term structure. No order-flow imbalance or systematic sentiment/cross-asset signals. |
| Catalyst information | **Partly implemented** | News headlines can be fetched and shown in reports. The premarket signal itself remains technical; there is no comprehensive, structured catalyst calendar or fundamental-data feed. |
| Strategy pricing and entry filters | **Mostly implemented** | Defined-risk spreads and condors, plus PMCC pairs, with conservative bid/ask assumptions, liquidity/friction/event gates, DTE and delta bands, max loss, breakeven, and return-on-risk ranking. |
| Unified decision synthesis | **Partly implemented** | Screeners and reports present a staged workflow, but the stock regime and spread candidate are not joined by an automated master decision engine. Selection and confirmation remain human steps. |
| Position sizing and book risk | **Partly implemented** | The paper ledger supports 2%-risk sizing and a 35% open-risk heat cap. There is no live-book exposure view, portfolio Greeks, sector/correlation control, or portfolio stress matrix. |
| Exits and management | **Partly implemented** | Mechanical exit evaluation is implemented for bull put spreads only. Other strategies do not have complete automated exit policies. |
| Valuation, performance, and learning | **Mostly missing** | No Black–Scholes valuation/solver, expected-move or Kelly sizing module, options backtester, or performance attribution/journal loop. |

## Material differences from the proposed framework

- The configured exit time threshold is **7 DTE**, not 21 DTE. The 50%-of-credit profit target and 2×-credit stop are configured for bull put spreads.
- Volatility gates use **IV rank above 50 plus IV above realized volatility** to label premium rich, and IV rank below 25 to stand down. The spread screener consumes this assessment; the PMCC screen does not.
- Greek values are obtained and some per-structure values are reported, but Amuse does not aggregate net portfolio delta, gamma, vega, or theta or calculate the proposed five-scenario P&L matrix.
- News headlines are available in reports, but they do not amount to an event-aware catalyst model. The premarket screen documents that it does not use news to classify gaps.
- Option probabilities are market-derived from the chain; the system does not independently price options with Black–Scholes or backtest historical performance.

## Main gaps to close

1. Connect regime, timing, volatility, structure, sizing, and preflight into a
   single explainable decision result.
2. Add portfolio-level Greeks, concentration/correlation checks, and explicit
   underlying/volatility scenario stress tests.
3. Expand strategy-specific management rules beyond bull put spreads, while
   keeping configured thresholds explicit.
4. Add a research and validation layer: historical options data or documented
   price synthesis, backtesting, and attribution by signal/strategy.
5. Add the missing analytical lenses where data supports them: order flow,
   sentiment, cross-asset relationships, expected move, and independent option
   valuation. Treat Kelly sizing as research until expectancy is validated.
6. Distinguish headline display from structured event coverage; add dependable
   earnings, dividend/ex-date, and catalyst data before using those events as
   automated gates.

## Sources in this repository

The assessment is based on the code and configuration in `src/`, particularly
`src/spread_screener.py`, `src/pmcc_quality.py`, `src/vol.py`, `src/exits.py`,
`src/ledger.py`, and `src/gates.yaml`, plus the implementation limitations and
roadmap in `README.md`. Reassess this page when those capabilities change.
