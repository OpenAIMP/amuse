# Options framework implementation status

**Reviewed:** 2026-10-13
**Repository revision:** `main` at `85aa64c` (PR #53 merged); issue #54 is the active implementation branch.

The complete framework with section-by-section status, rationale, and
prioritized remaining work is in the
[comprehensive framework assessment](comprehensive-options-market-analysis-framework.md).

## Summary

Amuse implements a capable options screening and paper-risk workflow. The
overall rating remains **about 50% implemented**. This is a qualitative
judgment about breadth and integration, not a count of checklist items. Core
screening is strongest; pricing utilities, portfolio-risk calculations, and
an advisory decision engine exist. PRs #46–#49 improved freshness controls,
dashboard visibility, and workflow reliability/confidentiality; PR #51 added
local bull-put position review, and PR #53 added a local timestamped market
context collector for portfolio risk. These improve
operation and reviewability but do not materially change breadth or prove
returns. Live data integration, calibration, and out-of-sample profitability
evidence remain limited or absent. The percentage is not a return measurement.

| Framework area | Status | What the repository supports |
|---|---|---|
| Technical analysis and regime/timing | **Mostly implemented** | Daily and intraday signals include trend, moving averages, RSI, Bollinger %B, VWAP, ATR, pivots/Fibonacci, gaps, relative volume, and opening-range logic. |
| Options opportunity signals | **Partly implemented** | Delta-based strike selection, provider Greeks, IV versus historical volatility, IV rank from accumulated snapshots, skew, term structure, plus reusable Black–Scholes and expected-move calculations. Pricing is not yet an independently calibrated candidate-ranking signal. No order-flow imbalance or systematic sentiment/cross-asset signals. |
| Catalyst information | **Partly implemented** | News headlines can be fetched and shown in reports. The premarket signal itself remains technical; there is no comprehensive, structured catalyst calendar or fundamental-data feed. |
| Strategy pricing and entry filters | **Mostly implemented** | Defined-risk spreads and condors, plus PMCC pairs, with conservative bid/ask assumptions, liquidity/friction/event gates, DTE and delta bands, max loss, breakeven, and return-on-risk ranking. |
| Unified decision synthesis | **Partly implemented** | PR #40 adds an advisory engine joining regime, horizon/events, timing, volatility, spread economics, and risk/sizing into ranked WATCH/CONSIDER/NO TRADE output. PR #47 surfaces the decision, six gates, expected move, and Kelly status in archived reports and the hub. Daily runs lack an account/ledger by default, so they cannot size positions. |
| Position sizing and book risk | **Partly implemented** | Existing ledger sizing and heat gates remain; PR #40 adds open-ledger Greeks and five model-based scenarios. PR #46 adds snapshot freshness and priced-leg coverage; PR #47 displays optional results; PR #53 adds a local collector for timestamped Public quotes, exact-OSI IV, and Treasury rate context. No scheduled canonical live-book feed, sector/correlation model, or automatic concentration check. |
| Exits and management | **Partly implemented** | `src/exits.py` contains configured bull-put rules. PR #51 adds a local manager that applies them to fresh explicit marks, reports coverage and actions, and never places orders. Other strategies lack exit policies, and marks are not automatically sourced. |
| Valuation, performance, and learning | **Partly implemented** | PR #40 adds European Black–Scholes pricing/Greeks, expected move, and fractional Kelly utility. Issue #54 adds a local mark-based replay for configured bull-put exits. Kelly and exit thresholds remain unvalidated out of sample; no historical quote provider or attribution loop exists. |

## Issue #52 — live market context for private portfolio-risk snapshots (merged in PR #53)

PR #53 added a local collector for timestamped Public underlying
quotes and exact-OSI option IV, plus the Treasury daily 3-month par yield.
Quote timestamps and the daily rate observation use separate freshness limits.
Exact contract mapping is required; unsupported adjusted deliverables and
missing observations remain visible as gaps. The collector feeds the existing
portfolio Greek/stress analyzer, while ledger data and generated snapshots
remain local and are not published to Pages.

**Benefit:** replace hand-entered market assumptions with traceable, fresh
observations and improve priced-leg coverage. **Evidence so far:** source and
freshness fields are emitted, but there is no multi-run coverage cohort yet.
Track snapshot completeness, stale/missing quote rates, rate freshness, and
priced-leg coverage. This is an input quality and risk-visibility benefit, not
evidence of improved returns; the rate is a maturity proxy and the model omits
dividends and early exercise.

## Impact interpretation

Benefits so far are **process, visibility, reliability, and risk-control
benefits**, not proven trading returns. Measure economic impact prospectively from recorded
recommendations, paper fills, fees/slippage, and outcomes by strategy and
regime. Implementation completion is not evidence of positive edge. The full
rationale, impact measures, caveats, and staged roadmap are in the
[comprehensive framework assessment](comprehensive-options-market-analysis-framework.md).

## Issue #50 — local bull-put exit review (merged in PR #51)

PR #51 added `src/position_manager.py` and
`bin/manage-positions.sh`. Given an open ledger and current per-position
buy-to-close asks with timestamps, the report applies the existing 50%-profit,
2×-credit stop, configured 7-DTE time exit, and no-assignment rules. Stale or
missing marks are `UNAVAILABLE`, not `HOLD`; other strategies are labeled
unsupported. Position details remain in ignored local reports, while the
public hub describes the workflow without showing an account's positions.

**Expected benefit:** auditable exit-policy coverage and explicit visibility
into missing inputs. **Current evidence:** code path and report schema only; no
live-fill or outcome cohort is recorded. Track fresh-mark coverage,
unavailable positions, action counts, human follow-through, net P&L, and
estimated-versus-realized slippage. This does not establish higher returns;
historical options evaluation (#11) and full policy validation (#9) remain open.

## Issue #54 — local historical bull-put exit replay (in progress)

The linked branch adds a local evaluator for supplied, source-attributed
historical marks. It replays configured exit rules chronologically and reports
scored-path coverage, mark-based net outcomes after explicit fees/slippage,
action counts, unresolved paths, and realized mark-P&L drawdown. Exact OSI
contracts and close-quote/underlying timestamps are required. There is no
historical quote download, synthetic mark generation, inferred fill, broker
execution, or public position data. Assignment uncertainty is counted and
disclosed, but actual early assignment is not modeled. A hold-to-expiration
baseline is explicitly omitted because the input format does not provide an
independent settlement or fill path.

**Expected benefit:** determine how often the configured exit policy would have
triggered on the supplied sample and expose data/cost sensitivity before
claiming an edge. After merge, measure dataset size, scored coverage, unresolved
paths, results by exit action, and any observed-versus-actual fill differences.
Mark replay does not establish future profitability or portfolio drawdown.

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
`src/historical_exit_evaluator.py`, `src/ledger.py`, `src/options_math.py`,
`src/portfolio_context.py`, `src/portfolio_risk.py`, and
`src/decision_engine.py`, plus workflows and README. Recheck the projected PR
state after merge and as impact data accumulates.
