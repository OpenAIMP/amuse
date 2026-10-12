# Options Lab

Stock and options screeners that pull live market data through Public.com's
hosted MCP server — built around one idea: **no indicator places a trade.**
Every signal answers exactly one question, and a trade only happens when they
all agree.

## The operating loop

```
Screen → Regime → Timing → Strikes → Size → Preflight
```

| Stage | Question it answers | Where it lives in the code |
|---|---|---|
| **Screen** | Which names are worth looking at? | `stock_screener.py`, `spread_screener.py`, `daytrade_screen.py`, `pmcc_quality.py` — run over `watchlist.txt` or `--universe` |
| **Regime** | Bullish, bearish, or neutral — which strategy family? | Trend-structure, SMA50/200, and anchored-VWAP gates in `stock_screener.py`; the readout's regime census |
| **Timing** | Is *now* a good entry, or wait? | `%B`, RSI14, and squeeze gates in `stock_screener.py`; gap, relative volume, and developing VWAP in `daytrade_screen.py` |
| **Strikes** | Where does the structure go? | Fib/pivot levels reported by `stock_screener.py`; delta-based short-strike selection in `spread_screener.py` (0.10–0.20Δ) and `pmcc_quality.py` (0.15–0.35Δ) |
| **Size** | How much can this lose? | Every structure reports max loss (`spread_screener.py`, `pmcc_quality.py`); you apply the 1–2% rule |
| **Preflight** | Anything that kills the trade? | Earnings/event gates fail closed in the screeners; buying power, fees, and your confirmation are human |

No stage overrules another. A perfect regime with %B at 1.0 waits at timing.
A great setup with earnings inside the window dies at preflight. Probabilities
come from option delta (market-implied), never from indicators.

### Lineage: stage → workflow → file

One matrix for the whole system — which stages each workflow implements, and
which files implement them. (`render_report.py` / `render_hub.py` are
pipeline, not loop stages: they publish whatever the loop produced.)

| Stage | `daily-watch` | `daytrade-screen` | `monthly-screen` |
|---|---|---|---|
| **Screen** | `stock_screener`, `spread_screener` | `daytrade_screen` | `pmcc_quality` |
| **Regime** | `stock_screener` — trend / SMA / anchored-VWAP gates, regime census | bias label replaces the regime read | pair-universe selection in `pmcc_quality` |
| **Timing** | `stock_screener` — %B / RSI14 / squeeze | `daytrade_screen` — gap / rel-vol / developing VWAP | — |
| **Strikes** | `spread_screener` — 0.10–0.20Δ short strikes | — | `pmcc_quality` — 0.15–0.35Δ short calls |
| **Size** | max loss per structure reported — you apply the 1–2% rule | — | max loss per pair reported — you apply the 1–2% rule |
| **Preflight** | event gates fail closed — you confirm | — | event gates fail closed — you confirm |

Read it two ways: down a column to see everything one workflow does;
across a row to see every file and workflow that implements a stage. Size
and Preflight are human stages in every flow — the code hands you max loss
and event flags; you check buying power and fees, and confirm.

### How it coheres: indicators → patterns → strategies → loop → workflows

Five layers, each built from the one below:

```
Indicators → Patterns → Strategies → Operating loop → Workflows
 (measure)   (interpret)  (structure)   (decide in order)   (run on schedule)
```

- **Indicators** measure: RSI, %B, VWAP distance, ATR, delta, DTE, gap %,
  relative volume.
- **Patterns** interpret the measurements: UP / RANGE / DOWN regime from
  trend + VWAP; "extended, don't chase" from %B > 1.0; "wait" from a squeeze;
  gap-and-go vs fade from gap direction + VWAP side.
- **Strategies** are *guided* by patterns — the screeners price every
  structure independently, and you select using the pattern read:

| Pattern | Strategy to favor | Why |
|---|---|---|
| UP trend, healthy timing | Bull put spread | Directional income with the trend |
| UP trend, strong momentum | Jade Lizard | Bullish tilt; the call wing finances the put spread |
| Range, no conviction | Iron condor | Income from staying inside the wings |
| UP trend, want duration | PMCC | LEAPS-based income over months |
| Pre-market gap + volume | Day-trade momentum | Same-day move, in and out |

- **The operating loop** sequences the decision: Screen finds, Regime +
  Timing qualify, Strikes place, Size + Preflight protect.
- **The workflows** run the loop on three clocks: intraday
  (`daytrade-screen`), daily (`daily-watch`), monthly (`monthly-screen`).

**Worked example — XOM, 2026-10-11.** Indicators: RSI 64, %B 0.96 (near the
top of the band, not over), 16.8% above anchored VWAP, mixed swing structure.
Patterns: RANGE regime, timing acceptable-but-warm. Strategy: the iron condor
(28.5% return-on-risk) over the bull put (14.7%) — the regime doesn't support
directional income. Loop: Screen surfaced it → Regime said neutral → Timing
said okay → Strikes at 155/150P × 185/190C → Size and Preflight yours.
Workflow: `daily-watch` priced both; the archive keeps the report.

## How this helps make money

The screeners don't generate profit — they enforce the process that does.
Premium-selling P&L is arithmetic: `win rate × average credit − loss rate ×
average loss`. The system attacks both sides:

- **Fewer losers.** The regime filter keeps you from selling puts into
  downtrends; the %B gate keeps you from chasing extended names; the event
  gate keeps earnings from detonating a short-premium position. Most retail
  options losses are unforced errors — the screeners veto them before sizing
  is even discussed.
- **Bigger, safer credits.** Conservative fills (short bid minus long ask, never
  midpoints) mean the credits you see are collectible. Strike placement behind
  Fib/pivot structure means the market has to break something real before your
  short strike is threatened. Defined risk on every structure means no single
  trade can breach the 1–2% rule.
- **Repetition.** The edge compounds by running daily: weekday screens, the
  PMCC exception watch, the pre-market scan. Small high-probability credits,
  collected consistently, logged in the journal, reviewed monthly.

What the system never does: place orders, predict direction, or promise
profit. A quiet screen (no qualifiers) is a correct output, not a malfunction
— cash is a position.

## Why and how to use it

**Why.** You want a rules-based way to find defined-risk options income
without staring at screens or trading on gut feel. The system does the heavy
analytical work on schedule — screening hundreds of names, pricing structures
with honest fills, and telling you in plain English what passed and what
didn't — so your job narrows to judgment: selection, sizing, confirmation.

**How, day to day.**

1. Morning: open the archive homepage, read the latest daily report. The
   readout gives you the regime and the top structures in one pass.
2. Shortlist where the two tables agree: a high-regime-score name carrying a
   high-return-on-risk structure.
3. Apply the 1–2% sizing rule to the reported max loss, check the event
   flags, confirm buying power — then it's your call.
4. Monthly: read the PMCC report for longer-horizon positions; log every
   decision in the Trading Workbook.

**Questions it answers.**

- Which names have a regime that supports selling premium?
- What defined-risk structures are priced right now — credit, max loss,
  breakeven?
- What's moving abnormally this morning?
- Which LEAPS pairs are worth holding for months?
- What changed since yesterday?
- Why did *nothing* qualify today?

**Questions it doesn't answer.**

- Will this trade make money? Probabilities are market-implied, not forecasts.
- How many contracts? `ledger.py` sizes from the 2%-max-loss rule — but you
  still confirm before anything is real.
- When do I exit? Bull put spreads now have a defined exit policy (below);
  other structures still need theirs.
- Is my book within risk limits? `ledger.py` enforces the 35% heat cap on
  paper positions; live-book tracking is still on you.
- What will the market do tomorrow? Nothing here predicts — ever.

## Repository layout

```
amuse/
├── src/                # all code: screeners, renderers, gates, ledger, exits, vol
│   ├── universes/      # index constituent lists (sp500/sp100/nasdaq100/dow30/russell2000)
│   ├── gates.yaml      # every tunable threshold (no code changes to retune)
│   └── watchlist.txt   # the 20-name universe for the daily + monthly screens
├── tests/              # stdlib unittest suite (python3 tests/test_*.py)
├── docs/               # GitHub Pages site: index, archive, reports/
├── bin/                # public-mcp shim (CI) + run-local.sh (local pipeline)
├── .github/workflows/  # master + screen workflows + universe refresh
├── Dockerfile / docker-compose.yml / .env.example
└── README.md
```

## Running it locally

**Without Docker** (needs Python 3.12 and a Public.com API key):

```bash
export PUBLIC_API_KEY=...
bash bin/run-local.sh test      # unit suite
bash bin/run-local.sh daytrade  # pre-market screen + report
bash bin/run-local.sh daily     # stock + spread screens + report
bash bin/run-local.sh monthly   # PMCC screen + report
bash bin/run-local.sh all       # everything, then rebuild the hub
open docs/index.html
```

**With Docker** (same commands, isolated):

```bash
cp .env.example .env   # then set PUBLIC_API_KEY inside
docker compose build              # first time only; stdlib-only, no pip
docker compose run --rm test      # unit suite
docker compose run --rm all       # everything, then rebuild the hub
# or run anything ad hoc:
docker compose run --rm app python3 src/stock_screener.py --names NVDA,AMD
open docs/index.html
```

Reports land in `docs/` either way (mounted from the host), so open
`docs/index.html` when done. The key never enters the image — it is read
from `.env` at run time only. Never commit `.env`. `bin/run-local.sh` is
the same pipeline the compose services call, so Docker and non-Docker runs
stay identical by construction.

### Clickable symbols

Every ticker in the reports is a link: clicking goes straight to its
Google Finance quote. The ▾ dropdown next to each symbol opens a clicklist
of research destinations — Yahoo Finance, Nasdaq, MarketWatch, CNBC,
Public (your broker), TradingView, Finviz, Fintel (institutional
ownership), WhaleWisdom (13F filings), Seeking Alpha, Zacks (rank +
earnings calendar), and SEC EDGAR filings. To add or remove a destination,
edit the `QUOTE_LINKS` table at the top of `src/render_report.py` — one
line per site, `{s}` for the uppercase symbol, `{sl}` for lowercase.

## How value is created

### Concepts

The domain ideas the system is built on. Each one is implemented somewhere,
not just described:

- **Defined risk** — every structure has a known max loss before it is shown
  to you. No naked legs, ever.
- **Net credit** — premium collected up front; the trade wins if the structure
  decays or the underlying stays put.
- **Delta as market-implied probability** — short strikes at 0.10–0.20Δ use
  the market's estimate, never a forecast.
- **Return on risk** — credit ÷ max loss; how structures are ranked.
- **Friction** — (bid/ask spreads) ÷ credit. Wide markets eat the edge, so it
  is capped at 3×.
- **Regime / timing / strikes** — the operating loop's separation of concerns:
  where it is safe, when to enter, how to structure.
- **Expectancy** — win rate × average win − loss rate × average loss, net of
  fees. The only number that decides whether this is income-generating
  (issue #12).
- **Heat** — total max loss across open positions, capped at 35% of account.

### Capabilities

What the system does, end to end:

1. Screens stocks for regime and timing (RSI, %B, VWAP, ATR, pivots).
2. Prices defined-risk income structures with conservative fills.
3. Scans pre-market for day-trade momentum setups.
4. Ranks PMCC pairs monthly and watches them daily for exceptions.
5. Applies exit rules (profit / stop / time / no-assignment) to open positions.
6. Tracks every paper position in a ledger with realized P&L net of fees.
7. Sizes positions from the 2% rule and enforces the heat cap.
8. Publishes every run to a permanent, timestamped archive.

### Competencies — what it is good at

- **Veto-based selection.** Most of the value comes from rejecting bad trades
  (downtrend, extended, earnings inside the window), not from picking winners.
- **Honest fills.** Short-bid-minus-long-ask: the credits shown are collectible.
- **Reproducibility.** Every threshold in `gates.yaml`; every run archived with
  its inputs. Any result can be re-derived.
- **No prediction.** Bias labels and probabilities are market-implied; the
  system never forecasts direction.

### Value proposition

For a trader learning to run an options book like a portfolio manager: it
replaces gut feel with a repeatable daily process — screen, filter, price,
size, exit, review — where every step is defined, tested, and logged. The
product is not picks; it is the discipline.

### Value chain

Raw market data → **screen** (find) → **regime/timing gates** (qualify) →
**structure pricing** (price) → **exit policy** (manage) → **ledger**
(track) → **sizing/heat** (protect) → **archive/review** (learn).

Each stage adds value only if the previous one held: pricing means nothing
without the regime veto; exits mean nothing without the ledger measuring
them; the ledger means nothing without out-of-sample proof (issue #11). The
chain is only as strong as its weakest documented link — which is why code,
config, docs, and tests change together.

## Screeners

| File | What it does | In scheduled flows |
|---|---|---|
| `stock_screener.py` | Technical screen with the indicator pack (below). Composite score 0–40 = base 0–30 + signals 0–10. Ends with a plain-English `READOUT` — the leader and why, rejections grouped by theme, regime census. | `daily-watch` |
| `spread_screener.py` | Income-structure selector: bull put spreads, iron condors, and defined-risk Jade Lizards (bull put spread + far-OTM call wing for bullish regimes). 21–60 DTE, short 0.10–0.20Δ, conservative **short-bid minus long-ask** fills, width auto-scales to price (`min(5, max(1, round(spot/25)))`). Ranked by return-on-risk, with its own readout. | `daily-watch` |
| `daytrade_screen.py` | Pre-market day-trading screen over the S&P 500: gap %, relative volume, developing VWAP distance, ATR range position. Bias stated as bias ("gap-and-go" / "fade risk"), never prediction. | `daytrade-screen` |
| `pmcc_quality.py` | PMCC pair-quality: 0.80–0.95Δ LEAPS (270–800 DTE) × 0.15–0.35Δ short calls (21–60 DTE), evaluated as pairs with liquidity, friction, capital, and earnings gates. | `monthly-screen` |
| `pmcc_watch.py` | Daily exception monitor: diffs today's screen vs cached state, reports only new qualifiers, dropouts, or 1.5+ pt yield shifts. | `daily-watch` |
| `render_report.py` | Renders dated report pages (plus `.meta.json` sidecars) from screener JSONs. | all three |
| `render_hub.py` | Rebuilds `docs/index.html` — the report archive homepage — from all sidecars. | all three |
| `scan_loop.py` | Runs any screener across multiple index universes and merges into one cross-universe leaderboard. | manual only |
| `semis.py` | Semiconductor momentum screen (early study, superseded). | retired |
| `pmcc.py`, `pmcc_value.py`, `pmcc_etf.py` | Early one-off PMCC pricers and studies (superseded by `pmcc_quality.py`). | retired |

`scan_loop.py` stays manual: the daily workflow's `universe` input covers the
scheduled case, and a full multi-universe sweep in CI would be hours of API
calls. `semis.py` is kept for reference only.

### The screeners compared — what each one does for your P&L

| | Stock screen | Day-trade screen | Monthly PMCC screen |
|---|---|---|---|
| **Question** | Where is it safe to sell premium for the coming weeks? | What's moving abnormally *right now*? | Which LEAPS pairs earn income for months? |
| **Horizon** | Days to weeks | Minutes to hours | Months |
| **Data** | Daily bars, a year of history | Intraday bars, today's session | Option chains + Greeks |
| **Signals** | RSI, SMA50/200, Bollinger %B, anchored VWAP, pivots/Fibs, trend | Gap %, rel volume, developing VWAP, ATR range | Delta gates, liquidity, friction, capital, earnings |
| **Output** | Ranked 0–40 + readout narrative | Ranked by gap × volume, gap-and-go / fade bias | Pairs ranked by 30-day premium-to-debit |
| **How it makes money** | Avoids losers: premium only where regime agrees — the veto list is worth as much as the leaderboard | Catches abnormal morning moves for same-day trades | Durable income: a few pairs generating monthly premium with less daily attention |

**Strategies vs patterns, per screener.** `spread_screener.py` implements the
three income *strategies* (bull put spreads, iron condors, Jade Lizards) —
those are the actual trade structures. `pmcc_quality.py` implements the PMCC
*strategy*. `stock_screener.py` implements no strategy; it implements
*patterns* (trend, squeeze, VWAP positioning) that classify regime and timing.
`daytrade_screen.py` implements one intraday *pattern* (gap + volume + VWAP →
momentum bias). `pmcc_watch.py` implements monitoring, not a strategy.

**How they combine into a daily pick.** The stock screen answers *where* it's
safe to sell premium; the spread screen answers *what* to sell (priced
strikes, credits, max loss). The best trade is where they agree: a
high-return-on-risk structure on a high-regime-score name. That agreement is
made by you, reading both tables — see the overlap note below.

### Overlap between the screeners

- **The spread screener does not read the stock screener's output.** Verified:
  every screener imports stdlib only — no cross-imports, no shared modules.
  Regime→structure agreement happens in the dashboard (tables side by side)
  and in the operating loop, not in code.
- **Shared gate architecture, not shared code.** Every screener uses the same
  pattern — categorized rejections, conservative fills, plain-English readout,
  JSON output — but each file implements it independently.
- **VWAP and ATR are computed twice.** `stock_screener` (session VWAP from
  15-minute bars, ATR14% from daily bars) and `daytrade_screen` (developing
  VWAP, intraday ATR) use the same indicators on different bar sets for
  different horizons — intentionally not deduplicated.
- **Short-premium selection overlaps** between `spread_screener` (0.10–0.20Δ
  shorts, 21–60 DTE, liquidity/friction/earnings gates) and `pmcc_quality`
  (0.15–0.35Δ shorts, 21–60 DTE, same gate families) — one philosophy, two
  structures.

### Beyond screeners

Reporting (`render_report.py`, `render_hub.py`), frozen data
(`universes.py`), orchestration (`scan_loop.py`), and monitoring
(`pmcc_watch.py`) round out the system. Position tracking and sizing live in
`ledger.py` (paper only). Not built: a backtester, a trade journal, and
anything that touches orders — Size and Preflight stay human.

## Signal packs

### Stock screener (`stock_screener.py`) — swing regime and timing

| Indicator | Role | Key reads |
|---|---|---|
| Bollinger Bands (20×2.0) | Timing | %B > 1.0 = extended, don't chase (hard reject); squeeze (125-day bandwidth min) = wait or size down |
| Anchored VWAP (52-week low) | Regime | Below it = institutional money underwater (hard reject for bullish income) |
| Session VWAP | Timing | Last completed session; distance reported, never a reject on missing data |
| Fractal pivots (n=5) + Fib 38.2/50/61.8% | Strikes | Short strikes go below the 61.8% retracement or last swing low |
| HH/HL trend structure | Regime | Downtrend = rejection; only uptrends get full bullish treatment |
| Gap (open vs prior close) | Tape | ±2%+ = gap up/down (overnight news — check catalyst); smaller = no gap |
| Momentum (RSI state) | Tape | Oversold <30, overbought >70, else neutral. State label, not a signal |
| Value (52-week range %) | Tape | ≤25% beaten-down / ≥75% priced-at-top. Chart position, NOT fundamental value |
| Bias (6-vote composite) | Regime | price>SMA50, price>SMA200, SMA50>SMA200, MACD>0, RSI>50, pivot UP. 4+ = bullish, ≤2 = bearish |

Deliberately **not** automated: Elliott Wave counting — too subjective; pivots
and Fibs capture the objective machinery underneath it.

The Gap/Momentum/Value/Bias columns are *readouts*, not gates — they describe
the tape but never reject a name. Value is explicitly a technical 52-week-range
proxy: the data feed has no fundamentals (no earnings, P/E, or balance-sheet
data), so it must never be read as intrinsic-value analysis.

### Day-trade screener (`daytrade_screen.py`) — intraday momentum

| Signal | Role | Gate / read |
|---|---|---|
| Gap % vs prior close | Screen | |gap| ≥ 2% |
| Relative volume (20-day avg) | Screen | ≥ 1.5× |
| Developing session VWAP | Timing / bias | Above → gap-and-go bias; below → fade risk (mirrored for gap-downs) |
| ATR14 % | Screen | 1–8% — too quiet or too wild both rejected |
| ATR-implied range position | Timing | Where price sits inside today's expected range |
| Price | Screen | ≥ $10 |

Ranked by |gap| × relative volume. No news/catalyst feed — gaps are
technical-only.

### Structure pricers (`spread_screener.py`, `pmcc_quality.py`) — defined-risk gates

| Gate | `spread_screener.py` | `pmcc_quality.py` |
|---|---|---|
| Short-leg delta | 0.10–0.20 | 0.15–0.35 (short calls) |
| Long leg | One width beyond the short strike (width auto-scales with price) | 0.80–0.95Δ LEAPS |
| DTE | 21–60 | 21–60 short / 270–800 long |
| Fills | Conservative: short bid − long ask | Conservative: long ask − short bid |
| Bid/ask spread | ≤ 25% of mid per leg | ≤ 25% of mid per leg |
| Liquidity | OI or volume ≥ 10 per leg | OI/vol ≥ 25 long leg, ≥ 10 short leg |
| Capital at risk | Max loss ≤ $1,000 per structure | ≤ $10,000 per pair |
| Friction | Combined leg spreads ÷ credit ≤ 3.0 | (Long spread + short spread) ÷ short bid ≤ 3.0 |
| Earnings | Inside the window → reject (unknown date = flag) | Inside the short window → reject |

Jade Lizard adds one skew gate: the call wing must sit ≥ 8% above spot —
farther OTM than a symmetric condor's, the "bullish regime" posture. Spreads
rank by return-on-risk; PMCC pairs rank by 30-day premium-to-debit.

Across all screeners: unknown data is a flag, never a rejection. Rejections
carry stable reason categories and are all printed — nothing is silently
dropped.

## Universes and the watchlist

`watchlist.txt` is the default shared watchlist — one symbol per line. Edit it,
commit, and the next scheduled run picks it up.

`universes.py` holds frozen constituent lists (2026-10-11, from Wikipedia):
`sp500` (503), `sp100` (101), `nasdaq100` (101), `dow30` (30). Every screener
accepts `--universe <key>`; `--names` overrides it. Dotted symbols are kept
verbatim (`BRK.B` resolves; `BRK-B` does not).

Notes for manual runs:

- Only `daily-watch.yml` has a `universe` input. The report records which
  source produced it (`daily-nasdaq100-2026-10-11`, banner on the page), so
  runs are never ambiguous.
- The PMCC watch ignores the universe and stays on the watchlist — LEAPS
  chains over 500 names isn't practical.
- Weight: the stock screener handles `sp500` in ~20 min, but the spread
  screener pulls full chains + Greeks per name (an hour-plus on 500 names).
  `sp100`/`nasdaq100` are the sweet spot for options.

## Volatility regime — cheap vs expensive (issue #7)

The system was structurally always a premium seller: it never asked whether
premium was worth selling. `vol.py` adds that read, sitting between Regime
and Timing in the loop — and `spread_screener.py` now consumes it: every
underlying with candidate structures gets the read attached, and
`STAND_DOWN` names have their structures vetoed (counted, not silently
dropped).

**What it measures:**

- **IV vs HV** — current implied vol (30-day ATM from chain Greeks) against
  20/60-day realized vol from daily bars. IV > HV means options price more
  movement than recently happened: richer premium, edge to the seller.
- **IV Rank** — percentile of current IV within its trailing history.
- **25-delta skew** — put IV minus call IV; the market's price for crash
  protection.
- **Term structure** — far-expiry IV minus near-expiry IV; backwardation flags
  a priced-in near-term event.

**Decision rules** (tuned in `gates.yaml` under `vol:`):

- IV rank > 50 **and** IV > HV → **SELL_PREMIUM**: vol is rich, edge to sellers.
- IV rank < 25 → **STAND_DOWN**: premium too cheap; no long-premium
  structures exist yet, so the correct trade is none.
- Anything else, or insufficient data → **NO_READ**: other gates decide.

**Honest limitation:** the MCP has no historical-IV endpoint, so IV rank
cannot look back a year on day one. `vol.py` builds the history forward:
each run appends a per-underlying IV snapshot (`record_snapshot`), and the
rank is trusted only after 30 snapshots (`min_iv_history`). Until then the
read is IV-vs-HV plus skew/term-structure — useful, but not a full rank.

## Risk management

### Exit policy — bull put spreads (issue #9)

Entries without exits is half a system. The first strategy with a complete
policy is the bull put spread, implemented as pure logic in `exits.py` and
tuned in `gates.yaml` under `exits:`:

- **Take profit:** close when the buy-back costs 50% of the credit (keep half).
- **Stop loss:** close when the buy-back costs 2× the credit — a fraction of
  the spread's max loss, never the full width.
- **Time exit:** never hold past 7 DTE; close or roll before gamma run-up.
- **No assignment:** short leg ITM inside 2 DTE → close the spread, never take
  the shares.

Priority: assignment risk > time exit > profit target > stop loss > hold.
These are starting values to be validated out-of-sample (issue #11), not
proven optima. Other structures still need their policies.

### Position ledger and sizing (issue #10)

`ledger.py` records every position with its fill assumptions and closes it
with a reason, computing realized P&L net of fees. Before opening, two gates:

- **Per-trade:** one spread's max loss ≤ 2% of account (→ contracts).
- **Heat cap:** total open max loss ≤ 35% of account.

Tuned in `gates.yaml` under `ledger:` (`max_loss_pct`, `heat_cap_pct`,
`fee_per_contract`). `test_ledger.py` includes end-to-end lifecycle tests:
entry → exit signal → ledger close → realized P&L, using the real gate values.

### What the system measures today

| Metric | How it's used |
|---|---|
| Delta | Strike-selection gates (0.10–0.20 shorts, 0.80–0.95 LEAPS); net delta reported per structure |
| Gamma / Vega / Theta | Fetched and reported — not used in any gate or decision |
| Open interest / volume | Liquidity gates only (≥10 per leg, ≥25 for PMCC long legs) |
| Implied volatility | Vol framework (`vol.py`): IV Rank, IV-vs-HV, skew, term structure; not yet wired into screener gates |
| Max loss / credit / breakeven | Gates (≤$1,000 per spread, ≤$10,000 per PMCC pair) + reported; structures ranked by return-on-risk |
| Realized volatility | ATR% as a stock-screen gate; formal 20/60-day HV in `vol.py` |

Risk is managed today through **defined-risk structures only** (no naked
legs), conservative fills, liquidity/friction/earnings gates, and the human
1–2% sizing rule and 30–40% heat cap. What the code enforces ends at the
structure level; the book level is human.

### Gaps to fix

- **Vol framework wired into the spread screener (issue #7).** Each underlying
  with candidate structures gets a cheap-vs-expensive read (IV Rank, IV-vs-HV,
  25-delta skew, term structure); `STAND_DOWN` names have their structures
  vetoed and counted, `SELL_PREMIUM`/`NO_READ` pass through with the read
  attached. `--no-vol` skips it; `--iv-history` points at the snapshot file.
  Not yet in `pmcc_quality.py`.
- **No long-premium structures.** A complete system needs debit strategies
  for low-vol regimes; today the only honest answer to cheap premium is cash.
- **No portfolio Greeks.** Per-structure Greeks are fetched but never
  aggregated — no net delta/gamma/vega/theta across the book, no scenario
  P&L (±10% underlying, ±50% vol), no concentration view.
- **Gamma/Vega/Theta don't drive decisions.** They're reported, not gating.

### MCP data limitations

What the Public MCP gives us: real-time quotes, historical OHLCV bars,
full option chains per expiry, per-contract Greeks (delta, gamma, theta,
vega, rho, IV), multi-leg strategy quotes, and order preflight. What it
does not give us — and how the system copes:

- **No historical IV or Greeks.** Only point-in-time. IV Rank builds forward
  from per-run snapshots (`vol.record_snapshot`), trusted after 30
  observations — no year-one rank.
- **No historical option quotes.** We cannot replay what a spread actually
  traded for last year. The #11 backtester must synthesize historical
  option prices (from HV and vol-surface assumptions) — a known modeling
  risk, to be disclosed with the results.
- **No fundamentals.** No market cap, P/E, dividend yield, or earnings
  dates. Event gates run on flags ("date unknown"), not dates — see the
  catalyst calendar roadmap item.
- **No dividend / ex-div calendar.** Short-call assignment risk over ex-div
  (PMCC) cannot be screened automatically; the manual events file is the
  only input.
- **No corporate-action feed.** Splits and symbol changes arrive unannounced;
  OSI symbols are validated per chain fetch, not monitored.
- **No intraday option data.** The day-trade lane is equity-only; there are
  no intraday option quotes or Greeks for exit timing.
- **No market-wide discovery.** All screening is watchlist-driven; the
  thinkScript scan is the stage-one discovery outside this repo.
- **No news/catalyst feed.** Gaps are technical-only.
- **Request/response, not streaming.** No tick-level Greeks or intraday risk
  updates; everything is a scheduled snapshot.
- **Quote staleness.** Closed-market quotes come back bad/wide — the reason
  weekend spread screens correctly return zero candidates.
- **Unverified service limits.** The Greeks batch size (40) and chain-call
  pacing are our choices, not published limits; heavy universes (S&P 500
  chains) take an hour-plus.

Several of these are already on the [roadmap](#roadmap) (backtester, live heat
tracker, catalyst calendar); the vol-valuation layer and portfolio Greeks
are added there too. Paper sizing and heat caps are implemented in
`ledger.py` (issues #9/#10).

## Pipeline and dashboard

Every run follows the same pipeline — screeners produce JSON, renderers turn
JSON into pages, and nothing is ever pruned:

```
Public.com API → screeners → reports/*.json → render_report.py → docs/reports/<type>-<source>-<date>.html → render_hub.py → docs/index.html → Pages
    (live)          (in Actions)     (artifacts)      (dated page + provenance)                   (archive)          (served)
```

`docs/index.html` is the **report archive homepage**: every report every
workflow ever produced, grouped by workflow (Daily screen / Pre-market
day-trade / Monthly PMCC), then by universe, newest first. Each report carries
a provenance banner — e.g. "Source: Nasdaq-100 · 101 names · Run 2026-10-11".
The archive is published at **https://amuse.openaimp.com** — a custom domain
on the GitHub Pages site, configured by the repo's `CNAME` file (Pages serves
`/docs`).

| Workflow | Schedule | Scripts it runs, in order | Publishes |
|---|---|---|---|
| `master.yml` | Weekdays 9:45am ET | Calls `daytrade-screen` → `daily-watch` → `monthly-screen` (on the 3rd) | (via the called workflows) |
| `daily-watch.yml` | Called by `master.yml`; manual via Actions tab | `stock_screener` → `spread_screener` → `pmcc_watch` → `render_report` → `render_hub` | `docs/reports/daily-<source>-<date>.html` |
| `daytrade-screen.yml` | Called by `master.yml`; manual via Actions tab | `daytrade_screen` → `render_report` → `render_hub` | `docs/reports/daytrade-<source>-<date>.html` |
| `monthly-screen.yml` | Called by `master.yml` on the 3rd; manual via Actions tab | `pmcc_quality` → `render_report` → `render_hub` | `docs/reports/pmcc-<source>-<yyyy-mm>.html` |

`master.yml` calls the other three as reusable workflows (`workflow_call`) —
no logic is duplicated. Inputs (`names`, `universe`, `limit`) flow through
from the master run, and `secrets: inherit` passes the API key. The individual
workflows keep no schedules of their own, so nothing runs twice; their
`workflow_dispatch` triggers remain for one-off manual runs.

`daily-watch.yml` accepts `names` and `universe` inputs on manual runs;
`daytrade-screen.yml` accepts `names` and `limit`; `monthly-screen.yml`
accepts `names`. Run outputs are kept as workflow artifacts for 90 days.
Publish steps do `git pull --rebase` before pushing, so the three workflows
never clobber each other's commits.

Enable Pages under Settings → Pages → Deploy from branch → `main` → `/docs`;
`.nojekyll` is present so it's served as plain static HTML, no Jekyll. Each
report's footer timestamp is the freshness check.

## Companion documents

The [Trading System](https://drive.google.com/drive/folders/1L5SorZ65H3wueSJjEUO8qAE5VumaEt6N)
Google Drive folder holds everything around the code:

| Folder | Contents |
|---|---|
| Docs | Trading Playbook (living document; the `.docx` is the working copy), Trading System Flow slide deck, plus the original method notes: `options-book-playbook.md`, `pmcc-screening-method.md`, `broker-connectivity.md`, `starter-allocation-framework.md` |
| Sheets | Trading Workbook — the trade journal / tracker / watchlist |
| Reports | Archived screener run outputs (also kept as 90-day workflow artifacts) |
| Code | Options Lab - PMCC Screener (early scripts + notes) |

## Setup

1. Repository secret `PUBLIC_API_KEY` (Settings → Secrets and variables →
   Actions): your Public.com API key. The only required setup.
2. Optional repository variable `PUBLIC_ACCOUNT_ID`: defaults to `5OI32712`.
3. `bin/public-mcp` is the Actions-compatible MCP client (same CLI interface as
   the local one; reads the key from env instead of a vault).

## Running locally

```bash
export PUBLIC_MCP_CLI="$PWD/bin/public-mcp"
export PUBLIC_API_KEY="your-key"          # or point PUBLIC_MCP_CLI at a vault-backed CLI
# 1. Screen → JSON (--names overrides --universe)
python3 src/stock_screener.py --names T,VZ,XOM --json-out /tmp/stock.json
python3 src/spread_screener.py --names T,VZ,XOM --json-out /tmp/spreads.json

# 2. Render the dated report
python3 src/render_report.py --stock /tmp/stock.json --spreads /tmp/spreads.json \
  --report-id daily-custom-2026-10-11 --source custom --source-detail "3 names"

# 3. Rebuild the archive, then open repo/docs/index.html in a browser
python3 src/render_hub.py
```

Variations — other universes, other report kinds:

```bash
python3 src/stock_screener.py --universe nasdaq100 --json-out /tmp/stock.json
python3 src/stock_screener.py --screener stock_screener.py --universes sp100,nasdaq100
python3 src/daytrade_screen.py --limit 20 --json-out /tmp/dt.json
python3 src/render_report.py --daytrade /tmp/dt.json \
  --report-id daytrade-sp500-2026-10-13 --source sp500 --source-detail "503 names"
python3 src/pmcc_quality.py --names T,VZ,XOM --json-out /tmp/pmcc.json
python3 src/render_report.py --pmcc /tmp/pmcc.json \
  --report-id pmcc-custom-2026-10 --source custom --source-detail "3 names"
```

`render_report.py` resolves `docs/` from the repo root; all
links are relative, so the pages work from `file://` and from Pages
identically.

Sunday caveat: the stock screen works any day, but the spread screen needs
live option quotes — on weekends market makers pull quotes and the liquidity
gate rejects everything, so the spread tables come up empty. Weekday runs get
the full tables.

## Key conventions

- Debits/credits estimated conservatively: **long ask − short bid**, never midpoints.
- `premium_to_debit_30d` and return-on-risk are screening ratios, not expected returns.
- Contracts assumed standard 100-share deliverables (not validated).
- **These scripts screen and monitor only. They never place orders.**

### Tuning the gates

Every threshold lives in **`gates.yaml`** — delta bands, DTE windows, spread
widths, liquidity floors, max-loss caps, friction caps, gap/volume/ATR cutoffs,
RSI/SMA/Bollinger/pivot lookbacks. Edit values there, not code; each screener
also accepts `--config PATH` for a different file. Missing keys fall back to
built-in defaults, so a partial file can't break a run. Looser gates produce
more candidates, not more edge — see the honest limitations below.

## Honest limitations

- The MCP has no fundamentals (no P/E, market cap, earnings dates) and no
  news/catalyst feed — gaps are technical-only; earnings come from outside data.
- Request/response API, not streaming: scheduled scans, not tick-level real-time.
- A full S&P 500 stock screen is ~1,000 API calls and takes ~20 minutes; the
  spread screener on 500 names takes an hour-plus — these are scheduled jobs,
  not interactive ones.

## Roadmap

What a portfolio manager would add, in order:

**Before real money**
- **Backtester** — validate the indicator pack, delta gates, and RoR ranking
  on history; none of it has been tested yet.
- **Adopt FOSS libraries for the research layer** — the screeners stay
  stdlib-only (transparency is the point), but do not reinvent the parts
  that are hard to get right:
  - **Backtesting** doesn't exist yet. Don't build it — evaluate **Optopsy**
    (options-specific, delta-selected strategies) or **LEAN** (full
    event-driven engine), per the feedback doc.
  - **Pricing/Greeks/IV solvers** — when you need your own (e.g. historical
    vol analysis), use **py_vollib** or **mibian**, not hand-rolled
    Black-Scholes. The reference standard is **QuantLib**.
  - **Volatility estimation** (for the IV-vs-HV layer) — the **arch**
    package (GARCH etc.).
  - **Performance attribution** (for the journal layer) — **quantstats** /
    **empyrical** (Sharpe, drawdowns, tear sheets).
  - **Data** — **OpenBB** if you outgrow single-provider MCP data.
  Greeks/IV currently come from the broker with no independent check.
- **Vol-valuation layer** — done for the spread screener (issue #7): IV Rank,
  IV-vs-HV, skew, term structure per underlying, wired between Regime and
  Timing with a STAND_DOWN veto. Not yet in `pmcc_quality.py`.
- **Long-premium structures** — debit strategies for cheap-vol regimes, or an
  explicit stand-down policy.
- **Catalyst calendar** — replace "earnings date unknown" flags with real
  dates wired into the event gates.

**Running the book**
- **Heat/exposure tracker** — paper positions tracked against the 35% heat
  cap in `ledger.py` (issue #10); live-book tracking and sector correlation
  limits still manual.
- **Portfolio Greeks + scenarios** — aggregate net delta/gamma/vega/theta
  across the book; scenario P&L (±10% underlying, ±50% vol).
- **Exit rules** — done for bull put spreads (issue #9): 50% profit target,
  2×-credit stop, 7-DTE time exit, no assignment. Other structures still
  need theirs.
- **Journal + attribution** — which layer (regime read vs structure) made or
  lost money, so the system learns.

**Robustness**
- **Regime filter on the spread screener** — tag or filter structures by the
  name's regime score; that joint is manual today.
- **Universe refresh** — the frozen constituent lists are dated 2026-10-11
  and will stale on index reconstitutions.
