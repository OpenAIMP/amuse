# Comprehensive Options & Market Analysis Framework

**Implementation review:** 2026-10-13
**Code reviewed:** `main` at merge commit `2dd5fd1` (PR #49); issue #50 is in progress on its linked PR branch.

This document begins with the framework blueprint reconstructed from the
nine-part description supplied in chat, then assesses how much of each part
Amuse implements. The linked Google Doc itself is not accessible in this
session, so this is a structured restatement rather than a verbatim import.
The framework is a target specification; its thresholds and methods are not
claims of proven trading edge.

## Framework blueprint

### 1. Technical analysis and opportunity lenses

Summarize chart and price patterns and indicator families, then evaluate the
broader lenses: order flow, market regime, sentiment/crowding, catalysts,
cross-asset relationships, statistical measures, options-derived signals,
and execution quality. Use the lenses to answer distinct questions rather
than treating any one indicator as a trade instruction.

### 2. Analysis disciplines and synthesis

Bring the 15 analysis disciplines into one decision view organized around six
questions: **Value, Timing, Crowding, Regime, Risk, and Execution**. Keep the
evidence for each question visible so conflicting signals can be resolved
before selecting a trade.

### 3. PM decision guidebook

Provide 12 universal pre-trade questions, a time-horizon matrix, a nine-step
sequential decision workflow, and fixed-fractional risk-sizing rules. The
workflow should carry a candidate from thesis and market context through
structure selection, risk, execution, exits, and review.

### 4. Option optimization and risk categories

Explain how net credit relates to maximum profit, breakeven, and maximum loss
for spreads. Compare defined-risk structures with undefined-risk exposure,
and set out active management choices such as taking profit, stopping out,
adjusting, rolling, or closing ahead of assignment risk.

### 5. Quantitative formulas and scoring

Define Black–Scholes inputs and valuation; portfolio Greeks; expected move
(`S × IV × √(DTE / 365)`); IV Rank; volatility risk premium (`IV − HV`);
expected value; and fractional Kelly position sizing. State the units,
assumptions, data source, and limitations for each measure.

### 6. Entry, exit, and volatility triggers

State measurable entry criteria: IV Rank in the 30–50 range as specified by
the source framework and short-leg absolute delta from 0.10 to 0.20. Define
mechanical exits: close at 50% of maximum profit, stop at a buyback cost of 2×
the opening credit, and use a 21-DTE time stop, with assignment and event risk
handled explicitly. Thresholds are proposed rules that require validation.

### 7. Objective function and market economics

Express portfolio selection as maximizing expected return against risk
(`E[R] − Risk`) subject to portfolio constraints. Define order-flow imbalance
(OFI) and repricing-cycle triggers, and show how they affect the decision
rather than using them as unexplained scores.

### 8. Multi-leg valuation and portfolio stress

Use a common signed-leg valuation (`Vₚ = Σ(qᵢ × Vᵢ)`), aggregate portfolio
Greeks across positions, and calculate a five-scenario stress matrix. Include
underlying and volatility shocks, including examples of ±10% underlying and
±50% implied volatility, and show the portfolio P&L under each case.

### 9. Overall master decision framework

Combine the analysis into a six-step master decision algorithm that qualifies
the regime, establishes thesis and horizon, assesses timing and volatility,
selects and prices the structure, applies portfolio risk and event limits,
and defines execution, exits, and review. Finish with a quick-reference table
for formulas, entry/exit criteria, and risk parameters, clearly labeling what
is implemented, proposed, or unvalidated.

## Implementation status assessment

**Overall estimate: about 50% implemented after PR #49 merged.** This is a
qualitative estimate of breadth and integration, not a count of checklist
items or an estimate of trading performance.
Amuse remains strongest at technical screening and defined-risk structures.
It now has reusable option math, optional book-level risk analysis, and a
joined advisory decision report. The daily pipeline still lacks a canonical
account/position feed, book-risk calculations need supplied market context,
and no out-of-sample result establishes that these changes increase returns.
PRs #46–#49 improved risk freshness reporting, dashboard visibility, and
workflow reliability/confidentiality without materially changing this breadth
estimate. Issue #50 adds a local exit-review path; this has not yet merged.

## Status key

- **Implemented:** the capability is present in code and used for the stated
  purpose.
- **Partial:** useful pieces exist, but coverage, integration, or automation is
  incomplete.
- **Missing:** no corresponding implementation was found in the repository.

## PR #40 — what changed, expected impact, and how to measure it

These additions are **additive**: they preserve the stock/spread screeners,
provider quotes, existing gates, and human preflight. The new code consumes
existing screen output or an explicitly supplied ledger/market snapshot; it
does not send orders or silently change existing entry/exit thresholds.

The economic mechanisms below are hypotheses about how better process can
protect or improve net returns. The impact column separates available evidence
from unmeasured benefit: implementation alone does not prove that any strategy
has an edge.

**Measured trading impact to date: none.** The code and documentation change
does not include a persisted decision-to-outcome journal or a before/after
paper-trading cohort. The measures below are the evidence to collect next;
benefits should remain labeled as hypotheses until that evidence is reviewed.

| Change | What it does now | Expected benefit / mechanism | Measure of impact | Status and limitation |
|---|---|---|---|---|
| Black–Scholes math (`src/options_math.py`) | Prices European calls/puts and returns delta, gamma, theta, vega, and rho; defines one-standard-deviation expected move and fractional Kelly calculation. | Creates a repeatable valuation basis; makes IV/time risk explicit; supplies bounded sizing math when outcome estimates are credible. | Compare model marks with contemporaneous market marks and realized fills by expiry/moneyness/IV; measure expected-move coverage; compare paper/out-of-sample returns and drawdown across sizing methods. | Math is implemented. Candidate ranking does not yet compare modeled fair value with executable quotes. No calibration, IV solver, transaction costs, or profitability result. Kelly utility does not make its inputs reliable. |
| Portfolio Greeks and scenario stress (`src/portfolio_risk.py`, issue [#42](https://github.com/OpenAIMP/amuse/issues/42)) | Requires a versioned snapshot with source and UTC timestamps for the snapshot, rate, spot, and IV; rejects stale observations (30-minute default), reports ledger timestamp and open-leg coverage, and excludes unavailable legs. | Makes stale/partial exposure harder to mistake for current whole-book risk; exposes directional/volatility sensitivity before adding risk. | Track priced-leg coverage, stale/missing-input frequency, risk reports blocked by freshness checks, and modeled scenario loss versus subsequent realized book changes. | Freshness/coverage controls are implemented, but snapshot values remain user-supplied and portfolio reports are not scheduled. Dashboard issue [#45](https://github.com/OpenAIMP/amuse/issues/45) renders supplied output and labels missing output. Staleness metrics are emitted per run but not yet persisted/aggregated. Uniform shocks and Black–Scholes limitations remain. |
| Six-step decision engine (`src/decision_engine.py`) | Joins regime, horizon/events, technical timing, volatility, spread economics, and risk/sizing into ranked WATCH/CONSIDER/NO TRADE results with reasons. Runs after daily screeners. Dashboard PR [#47](https://github.com/OpenAIMP/amuse/pull/47) adds recommendation, six gates, expected move, and Kelly-sizing visibility to archived HTML and hub summary. | Makes handoffs and vetoes consistent and visible; can reduce missed conflicts and unsuitable entries, and focus review on stronger-aligned candidates. | Track share of daily pages with complete decision section; then persist inputs/overrides, pass-through, paper fills, costs, realized expectancy, drawdown, and results versus prior manual/screener-only process. | Advisory only. Daily run has no account/ledger, so sizes normally remain unavailable and candidates are WATCH/NO TRADE. Events are only as good as upstream flags. Delta-derived win probability/EV are proxies, not calibrated forecasts. |
| Fractional Kelly with ledger caps | Uses realized closed outcomes by strategy only after 30 trades; applies fractional Kelly, caps at 2% account risk, and checks existing per-trade/35% heat limits if account and ledger are supplied. | Connects allocation to observed payoff history while keeping conservative hard limits; could reduce allocation when observed expectancy is weak. | Paper compare with fixed 0.5%, 1%, and 2% risk baselines; track net return, drawdown, tail losses, estimation error, and stability across time windows. | Calculation/gates exist, but account/ledger are not wired into scheduled runs. Thirty trades is a minimum gate, not statistical validation; Kelly is sensitive to noisy and regime-dependent estimates. |

### Dashboard visibility and benefit measurement

Dashboard PR #47 renders the six-step recommendation,
candidate gate statuses, one-standard-deviation expected move, and Kelly
sizing availability on the HTML report linked from `docs/index.html`. The hub
entry previews the recommendation, expected move, Kelly status, and
portfolio-risk availability/coverage before opening the report. The report
also renders Greeks, scenario P&amp;L, freshness, and priced-leg coverage when
a portfolio-risk JSON is provided. If that input is absent, the page labels
portfolio risk as unavailable rather than implying zero exposure. The Actions
workflow has no canonical ledger or live timestamped market snapshot, so it
does not invent portfolio-level risk values.

**Delivered benefit is visibility and reviewability, not proven profitability.**
Measure daily-report decision-section coverage first; when risk files exist,
measure freshness and priced-leg coverage. Then persist overrides and connect
recommendations to paper/live fills and costs. No return improvement can be
claimed until evaluated out of sample after costs.

### Workflow confidentiality and reliability

The GitHub Actions follow-up in issue [#48](https://github.com/OpenAIMP/amuse/issues/48)
removes the account-ID literal fallback, requires the repository secret,
enables `pipefail` for screener output piped through `tee`, and runs the daily
PMCC exception monitor after earlier step failures. This should prevent
account identifiers from being newly exposed in workflow source and reduce
false-green runs or missed monitoring. These are security/operational benefits;
they do not establish a trading-performance improvement. After merge, track
workflow failures accurately detected and PMCC runs completed after upstream
failures.

### Local bull-put position review (issue #50)

`src/position_manager.py` applies the existing configured bull-put exit rules
to open ledger entries only when a supplied mark snapshot and each position's
buy-to-close ask are fresh (30-minute default). It reports policy action,
reason, source/time, coverage, and missing/stale/unsupported positions in a
local JSON/Markdown report. `bin/manage-positions.sh` keeps these files under
the ignored root `reports/` folder; the public dashboard explains the workflow
without rendering account positions. No broker order is sent.

The incremental benefit is auditable rule coverage: an operator can see which
open bull-put positions were evaluated and which trigger or data gap applies.
Measure supported open positions, fresh-mark coverage, unavailable marks,
action counts, human follow-through, realized P&L after fees, and estimated vs
realized slippage. Initial implementation creates no trading-outcome evidence;
it does not prove that taking any exit improves returns. It also depends on
manually supplied executable complete-spread asks, and other structures remain
unsupported. Issue [#9](https://github.com/OpenAIMP/amuse/issues/9) still owns
complete entry-to-exit policy validation, and [#11](https://github.com/OpenAIMP/amuse/issues/11)
owns out-of-sample comparison.

### Gradual improvement path

1. **Connect a dependable snapshot source:** replace manual spot/IV/rate
   snapshot preparation with a documented feed, retain timestamps/provenance,
   and measure freshness/coverage over repeated runs.
2. **Record decisions before outcomes:** persist six-step rationale, prices,
   model inputs, overrides, and later fills/exits to create an auditable
   baseline and avoid reconstructing signals after the result is known.
3. **Paper trade and calibrate:** compare theoretical prices and expected
   moves with market/fill data; measure fill friction, EV calibration, stress
   accuracy, and strategy outcomes across regimes, including fees and slippage.
4. **Promote only evidence-backed changes:** require walk-forward/out-of-sample
   results, acceptable drawdown/tail risk, and stable performance before
   tuning thresholds or allowing Kelly to influence actual allocation. Keep
   hard risk caps and human order preflight.

This is a feedback process, **not self-modifying code**: the engine does not
learn weights, optimize thresholds, or update itself from profits/losses.
Outcome attribution and automated monitoring remain future work. Success means
better net, risk-adjusted results after costs over a credible evaluation
period—not more signals or higher paper EV alone.

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

PR #40 introduces a single advisory synthesis for stock regime, horizon/event
flags, technical timing, volatility, spread economics, and optional ledger
risk. It produces one traceable rationale across those inputs. It still does
not model fundamental value, crowding, cross-asset context, or execution
quality as a complete set of decision dimensions, so this is partial synthesis
rather than all 15 analysis disciplines.

**Why this rating:** `src/decision_engine.py` now joins the stock and spread
screen outputs. The absent data lenses and missing scheduled account/ledger
inputs keep the synthesis incomplete.

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

PR #40 adds an independent European Black–Scholes pricer with Greeks, the
expected-move formula, and a fractional-Kelly utility. The portfolio module
uses the pricer to aggregate ledger Greeks and scenario marks when supplied
with market context. The six-step engine can use expected move and realized
ledger outcomes. These are now implemented calculations, but expected return
is still not validated and Kelly sizing is generally unavailable in scheduled
runs because no account/ledger is passed. Reported screen EV remains a
delta-based proxy, not a historical forecast.

| Proposed measure | Framework formula/definition | Amuse status |
|---|---|---|
| Black–Scholes | Price from underlying price `S`, strike `K`, time `T`, rate `r`, volatility `σ` (and dividend yield where applicable) | **Implemented as a utility:** European pricing/Greeks; no IV solver, market quote calibration, or candidate fair-value ranking |
| Portfolio Greeks | Sum signed leg/position Greeks, scaled by quantity and contract multiplier | **Implemented with supplied inputs:** aggregates open-ledger legs; not connected to a canonical live book or scheduled market snapshot |
| Expected move | `S × IV × √(DTE / 365)` | **Implemented as a utility:** decision report adds a one-standard-deviation range when stock price, IV, and DTE are available; not a calibrated forecast |
| IV Rank | Current IV's location within its trailing IV distribution | **Partial:** `src/vol.py` computes percentile versus accumulated snapshots and requires a minimum history; no historical IV endpoint |
| Volatility risk premium | `IV − HV` (or an explicitly chosen ratio) | **Partial:** IV/HV comparison exists; the framework's subtraction is not a separate portfolio decision model |
| Expected value | `P(win) × average win − P(loss) × average loss − costs` | **Partial:** screen EV is delta-derived; realized strategy history is used for Kelly inputs after 30 closed trades, but no calibrated candidate EV including costs exists |
| Fractional Kelly | A capped fraction of a Kelly allocation based on validated outcome probabilities and payoff odds | **Implemented with safeguards:** ledger history + account required, fractional/capped at 2%, existing heat gate applied; no scheduled inputs or statistical validation |

**Why this rating:** see `src/options_math.py`, `src/portfolio_risk.py`,
`src/decision_engine.py`, `src/vol.py`, `src/spread_screener.py`, and
`src/ledger.py`. The new calculations improve consistency and visibility;
their predictive benefit remains to be measured.

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

**Status: Partial; portfolio calculations implemented, operational coverage incomplete.**

The screeners price supported multi-leg strategies and calculate maximum loss,
breakevens, and some per-structure Greeks. PR #40 adds Black–Scholes signed-leg
valuation in the open-ledger portfolio report, aggregates portfolio Greeks,
and calculates five theoretical scenarios from supplied market inputs.

The position value is `V_position = Σ(q_i × V_i)`, where `q_i` is the signed
quantity and `V_i` the model value of leg `i`. The stress grid reprices the
book under a base case and four combinations of ±10% underlying and ±50% IV.
Results are theoretical and require per-symbol spot/IV data plus valid ledger
legs; missing inputs are surfaced rather than treated as zero.

There is still no sector concentration or correlation model. All underlyings
receive the same percentage shock in a given scenario, a useful sensitivity
view but not a correlation forecast. The 35% heat cap sums position maximum
loss; it does not model correlated losses or changing Greeks.

**Why this rating:** `src/portfolio_risk.py` now performs model-based
aggregation/stress; `src/ledger.py` still calculates open heat from recorded
max loss. Data collection, freshness checks, and operational coverage remain
manual.

## 9. Overall unified master decision framework

**Status: Partial.**

PR #40 adds an advisory algorithm joining the stock and spread screen outputs,
applying regime, horizon/event, timing, volatility, structure, and optional
ledger/account gates, and explaining missing inputs/reasons. Its ranked output
is WATCH/CONSIDER/NO TRADE; it does not place orders. Scheduled runs have no
account/ledger, so sizing remains unavailable there. Exit management and
preflight are not folded into the engine, and some analysis disciplines have
no data source.

The implemented advisory six-step flow covers: qualify stock/regime; check
horizon and available event flags; assess technical timing; assess volatility;
check structure economics; apply optional account/ledger risk and sizing. It
explains its gates and ranks candidates. The broader target also calls for a
thesis, richer horizon strategy matrix, live buying-power preflight, defined
exits, and post-trade review; those are not executed end-to-end by this
service.

**Why this rating:** `src/decision_engine.py` joins the screeners and runs in
daily workflow/local daily path. It is an advisory integration, not an
autonomous execution or full portfolio-manager system.

## Remaining work by priority

### Priority 0 — Establish trustworthy risk and validation before expanding
live use

1. **Operationalize portfolio inputs:** connect a timestamped open ledger and
   reliable per-leg/symbol market snapshot to the new Greek/stress utility;
   reject stale values and measure input coverage. Add sector/correlation
   concentration only when supported by dependable data.
2. **Validate the risk rules:** add an options-aware historical evaluation
   using real historical option quotes where available, or clearly disclosed
   price-surface assumptions. Test exit rules, slippage, fees, and regime
   filters out of sample before treating thresholds as an edge.
3. **Close data-quality risks:** dependable earnings/dividend/ex-date inputs,
   stale quote handling, contract deliverable/corporate-action checks, and
   visible uncertainty when data is missing.

### Priority 1 — Complete the decision and management loop

4. **Persist decision/outcome records:** capture engine inputs, ranked
   candidates, reasons, overrides, fills, fees, exits, and P&L so impact can
   be evaluated without survivorship or hindsight bias.
5. **Complete decision coverage:** connect account/ledger inputs through a
   controlled workflow and add explicit freshness/completeness checks; bring
   preflight and exit plans into the review record while retaining human
   order confirmation.
6. **Strategy-specific exits:** issue #50 applies the existing bull-put rules
   to fresh, locally supplied position marks, without executing orders. The
   marks are not yet sourced automatically and outcome evidence is absent.
   Complete entry-to-exit validation in #9, then define and validate management
   rules for condors, asymmetric condors, PMCCs, and new strategies. Decide
   explicitly whether the bull-put time exit remains configured at 7 DTE or
   changes to the framework's proposed 21 DTE; document and validate the choice.
7. **Journal and attribution:** analyze net results by regime, strategy,
   candidate rank, sizing method, and rule; compare with the former
   screener-only/manual process.

### Priority 2 — Add statistical decision measures after outcome data exists

8. **Calibrate valuation and expected moves:** compare Black–Scholes prices
   and implied ranges with market quotes/realized observations; only use
   pricing differences as candidate-ranking signals after documenting fit,
   inputs, and limits.
9. **Expected value and sizing:** validate win/loss distributions, costs, and
   probability calibration before considering Kelly for actual allocation;
   test against fixed fractional baselines and include estimation uncertainty.
10. **Quantitative scoring:** separate market-implied probability, observed
   historical outcomes, and model forecasts; do not conflate these measures.

### Priority 3 — Extend the opportunity lenses where reliable data is available

11. Add order-flow imbalance, sentiment/crowding, cross-asset correlation,
    and options-flow signals with explicit data provenance and missing-data
    behavior.
12. Extend execution-quality measures beyond quote friction when fill data
    becomes available; compare estimated and realized fills.
13. Add a structured catalyst calendar and distinguish event risk from
    headline context.

## Assessment limits

This is a repository implementation review as of the revision above. It does
not establish that any trading rule is profitable or optimal. Several data
capabilities depend on external feeds, and the available README identifies
limits including no historical option quotes, no fundamentals from the MCP,
and request/response rather than streaming data. Revisit the status as code,
data access, and test evidence change.
