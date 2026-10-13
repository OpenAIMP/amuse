# Comprehensive Options & Market Analysis Framework

**Implementation review:** 2026-10-13
**Code reviewed:** `origin/main` at `2d060e9`
**Overall estimate:** **about 45% implemented**

This is the framework and its implementation assessment in one place. The
percentage is a qualitative estimate of breadth and integration, not a count
of checklist items. Amuse is strongest at technical screening, defined-risk
structure pricing, and paper sizing. Portfolio-wide risk, a unified decision
engine, independent pricing, and performance validation remain substantial
gaps.

## Status key

- **Implemented:** the capability is present in code and used for the stated
  purpose.
- **Partial:** useful pieces exist, but coverage, integration, or automation is
  incomplete.
- **Missing:** no corresponding implementation was found in the repository.

## 1. Technical analysis and opportunity lenses

**Status: Partial to mostly implemented.**

Amuse computes technical indicators and uses them to screen and describe market
conditions. The implemented toolkit includes trend structure, SMA50/SMA200,
RSI, Bollinger %B and squeeze, anchored/session VWAP, ATR, pivots/Fibonacci,
gaps, relative volume, opening-range behavior, and option-chain delta/Greeks.
The vol layer also calculates realized volatility, IV rank from accumulated
snapshots, IV versus HV, 25-delta skew, and term structure.

Execution quality is partly represented by conservative bid/ask fills,
per-leg liquidity gates, and a friction ratio. News headlines can appear in
reports, but the premarket signal remains technical and headlines are not a
structured event model.

The following lenses from the proposed framework are **missing or materially
incomplete**: order-flow imbalance (OFI), systematic sentiment/crowding,
cross-asset correlation, options-flow positioning, a structured catalyst and
earnings/dividend calendar, and a common execution-quality model. No
tick-level flow or streaming feed is used.

**Why this rating:** see `src/indicators.py`, `src/vol.py`,
`src/spread_screener.py`, `src/fetch_news.py`, and `src/premarket_screen.py`.
The code demonstrates a broad signal set, but several proposed lenses have no
data source or calculation path.

## 2. Analysis disciplines and synthesis

**Status: Partial.**

The repository covers substantial parts of **value-as-price/structure**,
**timing**, **regime**, **risk**, and **execution**. It ranks strategies by
return on risk, filters entries, estimates max loss and breakeven, and applies
conservative fills. The framework's broader distinctions—especially
fundamental value, crowding, portfolio context, and execution conditions—are
not fully modeled.

There is no single synthesis layer that answers *Value, Timing, Crowding,
Regime, Risk,* and *Execution* together for each proposed trade. Screeners
run separately; a person compares stock regime output with spread candidates.
The reports explain individual outputs but do not produce a master trade
decision with one traceable rationale.

**Why this rating:** the staged flow in `README.md` describes how the tools
should be used, while separate screeners implement individual stages. The
spread screener does not take the stock screener's regime result as an input.

## 3. PM decision guidebook

**Status: Partial.**

Amuse has a practical screen → regime → timing → strikes → size → preflight
workflow. Its paper ledger can calculate contract counts under a 2% maximum
loss-per-trade rule and reject a position that exceeds a 35% portfolio heat
cap. Daily, premarket/intraday, and monthly PMCC flows cover different holding
horizons.

The proposed 12 universal pre-trade questions, explicit horizon decision
matrix, and nine-step sequential workflow are not implemented as a guided,
enforced checklist. Buying-power confirmation and final trade selection still
belong to the user. The 2% rule is a configured risk constraint, not an
expectancy-optimized allocation model.

The target guidebook calls for: (a) a 12-question pre-trade checklist,
(b) a time-horizon matrix, (c) a nine-step workflow that moves from thesis and
market context through structure, risk, execution, and review, and (d)
fixed-fractional risk sizing. Amuse implements pieces of (c) and (d), but does
not enforce the checklist or provide a single horizon-to-strategy matrix.

**Why this rating:** `src/ledger.py` implements sizing and heat functions;
`src/gates.yaml` sets their thresholds. Reports and workflows do not enforce a
full PM checklist.

## 4. Option optimization and risk categories

**Status: Mostly implemented for defined-risk credit structures; partial for
active management.**

The spread screen prices defined-risk verticals, iron condors, and asymmetric
condors; the PMCC screen evaluates a long LEAPS plus short-call pair. The
screeners report conservative estimated credit/debit, max loss, breakeven,
and return on risk. Naked legs are not screened as candidates.

The framework's core distinction is present in the priced structures: a net
credit is collected at entry, while max loss is the defined worst-case loss
after accounting for that credit. The code screens defined-risk structures;
it does not offer a comparable optimizer that chooses among defined-risk and
undefined-risk strategies based on portfolio-level trade-offs. Undefined-risk
strategies are outside the supported candidate set.

The paper ledger records positions, fees, exits, and realized P&L. Mechanical
management rules cover bull put spreads, including profit-taking, a stop, a
time exit, and an assignment-risk exit. Other structures do not have complete
strategy-specific exit policies. There is no automated open-order execution
or live-book manager.

**Why this rating:** structure arithmetic and risk ceilings are in
`src/spread_screener.py`, `src/pmcc_quality.py`, `src/exits.py`, and
`src/ledger.py`; exit evaluation is specifically scoped to bull put spreads.

## 5. Quantitative formulas and scoring

**Status: Partial.**

Implemented quantities include option-chain Greeks, per-structure net risk
metrics, historical volatility, IV rank, IV/HV, skew, term structure, and
return-on-risk ranking. The rank is built forward from snapshots and is
trusted only after the configured minimum history is available.

The repository does **not** implement an independent Black–Scholes pricer or
IV solver, an expected-move model using the proposed formula, portfolio-level
Greek aggregation, formal expected value based on validated outcomes, or
fractional Kelly sizing. It also has no five-scenario portfolio stress test.
Reported return on risk is a screening ratio, not expected return.

| Proposed measure | Framework formula/definition | Amuse status |
|---|---|---|
| Black–Scholes | Price from underlying price `S`, strike `K`, time `T`, rate `r`, volatility `σ` (and dividend yield where applicable) | **Missing:** broker Greeks/prices are consumed; no independent pricing or IV solver |
| Portfolio Greeks | Sum signed leg/position Greeks, scaled by quantity and contract multiplier | **Missing at portfolio level:** some structure Greeks are reported, but not book-wide aggregation |
| Expected move | `S × IV × √(DTE / 365)` | **Missing:** ATR/range measures exist; this options-implied formula is not calculated |
| IV Rank | Current IV's location within its trailing IV distribution | **Partial:** `src/vol.py` computes percentile versus accumulated snapshots and requires a minimum history; no historical IV endpoint |
| Volatility risk premium | `IV − HV` (or an explicitly chosen ratio) | **Partial:** IV/HV comparison exists; the framework's subtraction is not a separate portfolio decision model |
| Expected value | `P(win) × average win − P(loss) × average loss − costs` | **Missing as a validated edge estimate:** ledger reports realized win rate and average outcomes, but does not use them to forecast candidates |
| Fractional Kelly | A capped fraction of a Kelly allocation based on validated outcome probabilities and payoff odds | **Missing:** no validated probability/payoff estimate feeds position sizing |

**Why this rating:** see `src/vol.py`, `src/spread_screener.py`, and
`src/ledger.py`. Greek data comes from the market-data provider; it is not
recomputed or aggregated across open positions.

## 6. Entry, exit, and volatility triggers

**Status: Partial; material threshold difference from the proposed document.**

| Rule | Proposed framework | Amuse implementation |
|---|---|---|
| Short spread delta | 0.10–0.20 | **Implemented:** 0.10–0.20 absolute short delta in spread screening |
| Volatility entry | IVR range described as 30–50 | **Different:** `SELL_PREMIUM` requires IV rank above 50 and IV above HV; IV rank below 25 yields `STAND_DOWN` |
| Profit exit | Close after 50% of max profit | **Implemented for bull put spreads:** close when buyback cost is at most half the entry credit |
| Stop exit | Close at 2× credit | **Implemented for bull put spreads:** close when buyback cost reaches 2× entry credit |
| Time exit | 21 DTE | **Different:** configured minimum is 7 DTE |
| Assignment handling | Close before assignment risk | **Implemented for bull put spreads:** ITM short put inside the 2-DTE assignment window triggers an exit |

The 21-versus-7-DTE difference matters: these are different holding rules and
should not be described as equivalent. The current 7-DTE threshold is code,
not a recommendation that it is optimal. It has not been validated by a
backtest. The vol assessment is consumed by the spread screener, not the PMCC
screener, and no long-premium structure is available for cheap-vol regimes.

**Why this rating:** settings are in `src/gates.yaml`; evaluation is in
`src/exits.py` and `src/vol.py`.

## 7. Objective function and market economics

**Status: Mostly missing.**

The screeners use return on risk, premium/debit yield, and friction to rank
candidates. The ledger reports realized wins, losses, and P&L. These are
useful ingredients, but Amuse does not solve a portfolio-manager objective
such as expected return minus risk subject to constraints. It has no
calibrated expected-value model, OFI calculation, or repricing-cycle trigger
system.

**Why this rating:** current rankings prioritize structural price ratios, not
validated statistical expectancy; the ledger is recordkeeping, not an
optimization engine.

## 8. Multi-leg valuation and portfolio stress

**Status: Partial at trade level; missing at portfolio level.**

The screeners price supported multi-leg strategies and calculate maximum loss,
breakevens, and some per-structure Greeks. They do not provide a universal
valuation model for arbitrary signed legs, aggregate portfolio Greeks across
positions, or calculate the proposed five-scenario P&L matrix.

The proposed generic position value is `V_position = Σ(q_i × V_i)`, where
`q_i` is the signed quantity and `V_i` the value of leg `i`. The proposed
stress grid reprices the book under five market scenarios, including the
framework's underlying and volatility shocks (for example, ±10% underlying
and ±50% implied volatility). Neither the generic signed-leg valuation nor
that scenario grid is implemented at portfolio level.

There is no portfolio concentration or correlation analysis, and no combined
underlying/volatility shock view. The 35% heat cap sums position maximum loss;
it does not model correlated losses or changing Greeks.

**Why this rating:** `src/ledger.py` calculates open heat from recorded max
loss, while no portfolio scenario or Greek aggregation module is present.

## 9. Overall unified master decision framework

**Status: Partial.**

The six-stage operating loop and separate scheduled workflows exist. Signals,
strategy prices, event flags, risk amounts, and reports are available across
the application. What is missing is the proposed unified algorithm that
consumes all relevant evidence, applies portfolio constraints, explains
rejections, and emits a consistent action/size/management plan. The
quick-reference formulas and triggers also need to distinguish implemented
rules from proposed ones.

The target **six-step master algorithm** can be summarized as: qualify market
regime; establish thesis and horizon; assess timing and volatility; select and
price a defined-risk structure; apply portfolio risk, size, and event gates;
then define execution, exit, and review conditions. Amuse has separate code
for several steps, but this sequence is not yet executed end-to-end by one
decision service.

**Why this rating:** README describes a human-operated process across
independent screeners; no common decision engine joins their outputs.

## Remaining work by priority

### Priority 0 — Establish trustworthy risk and validation before expanding
live use

1. **Portfolio exposure and stress view:** aggregate open positions' Greeks,
   concentration, and loss under explicit underlying/volatility scenarios.
   Reconcile this with the existing heat cap so correlated positions are
   visible.
2. **Validate the risk rules:** add an options-aware historical evaluation
   using real historical option quotes where available, or clearly disclosed
   price-surface assumptions. Test exit rules, slippage, fees, and regime
   filters out of sample before treating thresholds as an edge.
3. **Close data-quality risks:** dependable earnings/dividend/ex-date inputs,
   stale quote handling, contract deliverable/corporate-action checks, and
   visible uncertainty when data is missing.

### Priority 1 — Complete the decision and management loop

4. **Unified decision record:** join regime, timing, vol, structure, event
   flags, sizing, and preflight in one explainable result; retain the human
   confirmation step.
5. **Strategy-specific exits:** define and validate management rules for
   condors, asymmetric condors, PMCCs, and any new strategy. Decide explicitly
   whether the bull-put time exit remains 7 DTE or changes to 21 DTE; document
   the rationale and validate either value.
6. **Journal and attribution:** connect entries/exits to signal snapshots so
   realized results can be attributed by regime, strategy, and rule.

### Priority 2 — Add statistical decision measures after outcome data exists

7. **Expected value and sizing:** estimate win/loss distributions after
   collecting validated outcomes. Only then consider fractional Kelly, with
   conservative caps and uncertainty handling.
8. **Independent valuation and move estimates:** add an independently checked
   option-pricing/IV method and a documented expected-move calculation.
9. **Quantitative scoring:** separate market-implied probability, observed
   historical outcomes, and model forecasts; avoid presenting one as another.

### Priority 3 — Extend the opportunity lenses where reliable data is available

10. Add order-flow imbalance, sentiment/crowding, cross-asset correlation,
    and options-flow signals with explicit data provenance and missing-data
    behavior.
11. Extend execution-quality measures beyond quote friction when fill data
    becomes available; compare estimated and realized fills.
12. Add a structured catalyst calendar and distinguish event risk from
    headline context.

## Assessment limits

This is a repository implementation review as of the revision above. It does
not establish that any trading rule is profitable or optimal. Several data
capabilities depend on external feeds, and the available README identifies
limits including no historical option quotes, no fundamentals from the MCP,
and request/response rather than streaming data. Revisit the status as code,
data access, and test evidence change.
