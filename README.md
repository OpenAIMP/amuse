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
| **Screen** | Which names are worth looking at? | `stock_screener.py`, `spread_screener.py`, `premarket_screen.py`, `intraday_screen.py`, `pmcc_quality.py` — run over `watchlist.txt` or `--universe` |
| **Regime** | Bullish, bearish, or neutral — which strategy family? | Trend-structure, SMA50/200, and anchored-VWAP gates in `stock_screener.py`; the readout's regime census |
| **Timing** | Is *now* a good entry, or wait? | `%B`, RSI14, and squeeze gates in `stock_screener.py`; gap, relative volume, and developing VWAP in `premarket_screen.py`; opening-range breakouts and session VWAP in `intraday_screen.py` |
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

| Stage | `daily-watch` | `premarket-screen` / `intraday-screen` | `monthly-screen` |
|---|---|---|---|
| **Screen** | `stock_screener`, `spread_screener` | `premarket_screen`, `intraday_screen` | `pmcc_quality` |
| **Regime** | `stock_screener` — trend / SMA / anchored-VWAP gates, regime census | bias label replaces the regime read | pair-universe selection in `pmcc_quality` |
| **Timing** | `stock_screener` — %B / RSI14 / squeeze | `premarket_screen` — gap / rel-vol / developing VWAP; `intraday_screen` — ORB / session VWAP | — |
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
  (`premarket-screen`, `intraday-screen`), daily (`daily-watch`), monthly (`monthly-screen`).

**Worked example — XOM, 2026-10-11.** Indicators: RSI 64, %B 0.96 (near the
top of the band, not over), 16.8% above anchored VWAP, mixed swing structure.
Patterns: RANGE regime, timing acceptable-but-warm. Strategy: the iron condor
(28.5% return-on-risk) over the bull put (14.7%) — the regime doesn't support
directional income. Loop: Screen surfaced it → Regime said neutral → Timing
said okay → Strikes at 155/150P × 185/190C → Size and Preflight yours.
Workflow: `daily-watch` priced both; the archive keeps the report.

## Where the strategy lives
> Strategy, P&L philosophy, and operating discipline live in the [Trading Playbook](https://drive.google.com/drive/folders/1L5SorZ65H3wueSJjEUO8qAE5VumaEt6N) (Google Doc). This README documents the system technically: code, gates, workflows, and data.

For a code-backed comparison against the broader options framework, see the
[implementation status assessment](docs/implementation-status.md). It records
the review date, current coverage, material threshold differences, and the
largest remaining gaps.

## Repository layout

```
amuse/
├── src/                # all code: screeners, renderers, gates, ledger, exits, vol
│   ├── mcp_client.py   # the single MCP funnel: mcp_call + McpError (issue #36)
│   ├── market_data.py  # canonical bar dicts: daily_bars, intraday_bars, quotes (issue #36)
│   ├── indicators.py   # SMA/EMA/MACD/RSI/ATR/Bollinger/VWAP/pivots/gaps (issue #36)
│   ├── options_chain.py# OSI parsing, DTE, chain parsing, greeks (issue #36)
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
bash bin/run-local.sh premarket # pre-market screen + report
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

### Market news (hybrid: morning snapshot + live widget)

`src/fetch_news.py` pulls Google News RSS (stdlib-only, no API key) for
market-wide headlines (S&P 500, Fed) and per-ticker catalyst news:

```bash
python3 src/fetch_news.py --names NVDA,AAPL --out reports/news.json --market-out docs/news.json
```

- **Reports** get a *Catalyst watch* section (`--news reports/news.json`):
  morning headlines for the tickers in that report — check these before
  trusting any regime read.
- **The hub page** bakes the market headlines into `docs/news.json` and shows
  them in a *Market news* card. A small inline script then tries a live
  refresh on page load via the rss2json CORS proxy; if it fails, the morning
  snapshot stays with an explanatory note. The ↻ button retries manually.

The workflow step (added to daily-watch.yml before rendering):

```yaml
      - name: Fetch market news
        run: |
          python3 src/fetch_news.py --names "$WATCHLIST" \
            --out reports/news.json --market-out docs/news.json || true
```

`docs/news.json` is committed so Pages always has a fallback; `reports/news.json`
is a build artifact like the other screen outputs.

## What the system does

End-to-end capabilities (each implemented in code, not just described):

1. Screens stocks for regime and timing (RSI, %B, VWAP, ATR, pivots).
2. Prices defined-risk income structures with conservative fills.
3. Scans pre-market for gap momentum setups and intraday for opening-range breakouts.
4. Ranks PMCC pairs monthly and watches them daily for exceptions.
5. Applies exit rules (profit / stop / time / no-assignment) to open positions.
6. Tracks every paper position in a ledger with realized P&L net of fees.
7. Sizes positions from the risk rule and enforces the heat cap.
8. Publishes every run to a permanent, timestamped archive.

Concepts, competencies, the value proposition, and the value chain are documented
in the Trading Playbook (Sections 19–20).

## Screeners

| File | What it does | In scheduled flows |
|---|---|---|
| `stock_screener.py` | Technical screen with the indicator pack (below). Composite score 0–40 = base 0–30 + signals 0–10. Ends with a plain-English `READOUT` — the leader and why, rejections grouped by theme, regime census. | `daily-watch` |
| `spread_screener.py` | Income-structure selector: bull put spreads, iron condors, and defined-risk Jade Lizards (bull put spread + far-OTM call wing for bullish regimes). 21–60 DTE, short 0.10–0.20Δ, conservative **short-bid minus long-ask** fills, width auto-scales to price (`min(5, max(1, round(spot/25)))`). Ranked by return-on-risk, with its own readout. | `daily-watch` |
| `premarket_screen.py` | Pre-market gap screen: gap %, time-prorated relative volume, developing VWAP distance, ATR range position. Bias stated as bias ("gap-and-go" / "fade risk"), never prediction. | `premarket-screen` |
| `intraday_screen.py` | Intraday 15-min opening-range breakouts, session-VWAP reclaim/loss, time-prorated relative volume, conviction ranking, near-miss diagnostics. | `intraday-screen` |
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

### The screeners compared

| | Stock screen | Day-trade screen | Monthly PMCC screen |
|---|---|---|---|
| **Question** | Where is it safe to sell premium for the coming weeks? | What's moving abnormally *right now*? | Which LEAPS pairs earn income for months? |
| **Horizon** | Days to weeks | Minutes to hours | Months |
| **Data** | Daily bars, a year of history | Intraday bars, today's session | Option chains + Greeks |
| **Signals** | RSI, SMA50/200, Bollinger %B, anchored VWAP, pivots/Fibs, trend | Gap %, rel volume, developing VWAP, ATR range | Delta gates, liquidity, friction, capital, earnings |
| **Output** | Ranked 0–40 + readout narrative | Ranked by gap × volume, gap-and-go / fade bias | Pairs ranked by 30-day premium-to-debit |

### When to run each screener

| Screener | Run when | Expect | Don't expect much when |
|---|---|---|---|
| `stock_screener.py` | Anytime — it reads daily bars | Ranked regime scores (0–40) plus the plain-English readout | — |
| `spread_screener.py` | Weekday market hours, ideally morning | Priced structures (bull puts, condors, Jade Lizards) or an honest zero with rejection reasons | Nights / weekends: quotes are stale, spreads go wide, and the conservative gates reject everything |
| `premarket_screen.py` | ~9:00 AM ET on weekdays | Gap-bias list (gap %, rel volume, developing VWAP) | Any other time: no developing session, no fresh quote |
| `intraday_screen.py` | 11 AM / 2 PM ET on weekdays | Opening-range breakouts, VWAP reclaim/loss, conviction ranking | Market closed: reports "no intraday bars" |
| `pmcc_quality.py` | Monthly (the 3rd), during market hours | Ranked LEAPS pairs by 30-day premium-to-debit | Nights / weekends: same stale-chain problem as the spread screener |
| `pmcc_watch.py` | Daily | Silence, unless a qualifier appeared/dropped or a yield shifted ≥1.5 pts | — |

Manual runs use `--universe <key>` (e.g. `lev_etf`, `sp500`, `nasdaq100`) or
`--names TQQQ,SOXL` to target specific tickers; `--names` wins when both are
given. The scheduled workflows already encode the right times — see
`.github/workflows/`.

**Strategies vs patterns, per screener.** `spread_screener.py` implements the
three income *strategies* (bull put spreads, iron condors, Jade Lizards) —
those are the actual trade structures. `pmcc_quality.py` implements the PMCC
*strategy*. `stock_screener.py` implements no strategy; it implements
*patterns* (trend, squeeze, VWAP positioning) that classify regime and timing.
`premarket_screen.py` implements one pre-market *pattern* (gap + volume + VWAP →
momentum bias); `intraday_screen.py` implements the intraday ORB pattern. `pmcc_watch.py` implements monitoring, not a strategy.

**How they combine into a daily pick.** The stock screen answers *where* it's
safe to sell premium; the spread screen answers *what* to sell (priced
strikes, credits, max loss). The best trade is where they agree: a
high-return-on-risk structure on a high-regime-score name. That agreement is
made by you, reading both tables — see the overlap note below.

### Shared libraries (issue #36)

All screeners are stdlib-only and import from four shared modules — no
duplicated plumbing:

| Module | Provides | Used by |
|---|---|---|
| `mcp_client.py` | `mcp_call` + `McpError`: the single MCP funnel. Every API call in the system goes through this one function. | all screeners |
| `market_data.py` | Canonical bar dicts (`date`/`ts`, `open`, `high`, `low`, `close`, `volume`); `daily_bars`, `intraday_bars`, `quotes`, `quote` | all screeners |
| `indicators.py` | Pure indicator math: SMA, EMA, MACD, RSI, ATR, Bollinger, VWAP, anchored VWAP, fractal pivots, gaps | stock, premarket, intraday |
| `options_chain.py` | OSI parsing, DTE, `parse_chain`, `greeks` (with `signed` flag: put spreads validate delta on [-1, 1], PMCC calls on [0, 1]) | spread, pmcc |

Screen-specific logic stays in each screener (gap bias, ORB detection,
structure pricing, regime scoring). Tests patch the single funnel
(`mcp_client.mcp_call`) rather than per-screener copies.

### Overlap between the screeners

- **The spread screener does not read the stock screener's output.**
  Regime→structure agreement happens in the dashboard (tables side by side)
  and in the operating loop, not in code.
- **Shared libraries, not shared opinions.** Every screener draws MCP access,
  bars, indicators, and chain parsing from the modules above — but each file
  keeps its own screening logic, gates, and readouts.
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

### Pre-market screener (`premarket_screen.py`) — gap momentum

| Signal | Role | Gate / read |
|---|---|---|
| Gap % vs prior close | Screen | |gap| ≥ 2% |
| Relative volume (20-day avg) | Screen | ≥ 1.5× |
| Developing session VWAP | Timing / bias | Above → gap-and-go bias; below → fade risk (mirrored for gap-downs) |
| ATR14 % | Screen | 1–8% — too quiet or too wild both rejected |
| ATR-implied range position | Timing | Where price sits inside today's expected range |
| Price | Screen | ≥ $10 |

Ranked by |gap| × relative volume. This screener does not consume news; the
separate headline fetch and report card can provide context, but gap
classification remains technical-only.

### Intraday screener (`intraday_screen.py`) — opening-range breakouts

15-minute opening-range breakouts with session-VWAP reclaim/loss signals, time-prorated
relative volume (the old full-day-average comparison made the 1.5× gate unreachable midday),
conviction ranking, and near-miss diagnostics so the report never returns blank.
ORB reads 'broke out and holding' rather than breaking-this-minute; sustained VWAP
position (≥70% of session) confirms the move.

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

### Exit policy and ledger (issues #9, #10)

Exit rules, the position ledger, and sizing discipline are documented in the Trading Playbook (Section 21). Tuned values live in `gates.yaml` under `exits:` and `ledger:`.

### What the system measures today

| Metric | How it's used |
|---|---|
| Delta | Strike-selection gates (0.10–0.20 shorts, 0.80–0.95 LEAPS); net delta reported per structure |
| Gamma / Vega / Theta | Fetched and reported — not used in any gate or decision |
| Open interest / volume | Liquidity gates only (≥10 per leg, ≥25 for PMCC long legs) |
| Implied volatility | Vol framework (`vol.py`): IV Rank, IV-vs-HV, skew, term structure; consumed by `spread_screener.py`, not yet by `pmcc_quality.py` |
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
- **News headlines are not a structured catalyst feed.** Reports can show
  fetched headlines, but premarket gap classification is technical-only and
  there is no dependable earnings/dividend/catalyst calendar wired into gates.
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
| `master.yml` | Weekdays 9:45am ET | Calls `daily-watch` → `monthly-sch` → `monthly-screen` (on the 3rd) | (via the called workflows) |
| `daily-watch.yml` | Called by `master.yml`; manual via Actions tab | `stock_screener` → `spread_screener` → `pmcc_watch` → `render_report` → `render_hub` | `docs/reports/daily-<source>-<date>.html` |
| `premarket-screen.yml` | Own cron (9:00am ET weekdays); manual via Actions tab | `premarket_screen` → `render_report` → `render_hub` | `docs/reports/premarket-<source>-<date>.html` |
| `intraday-screen.yml` | Own crons (11am + 2pm ET weekdays); manual via Actions tab | `intraday_screen` → `render_report` → `render_hub` | `docs/reports/intraday-<source>-<date>.html` |
| `monthly-screen.yml` | Called by `master.yml` on the 3rd; manual via Actions tab | `pmcc_quality` → `render_report` → `render_hub` | `docs/reports/pmcc-<source>-<yyyy-mm>.html` |

`master.yml` calls the other three as reusable workflows (`workflow_call`) —
no logic is duplicated. Inputs (`names`, `universe`, `limit`) flow through
from the master run, and `secrets: inherit` passes the API key. The individual
workflows keep no schedules of their own, so nothing runs twice; their
`workflow_dispatch` triggers remain for one-off manual runs.

`daily-watch.yml` accepts `names` and `universe` inputs on manual runs;
`premarket-screen.yml` / `intraday-screen.yml` accept `names` and `limit`; `monthly-screen.yml`
accepts `names`. Run outputs are kept as workflow artifacts for 90 days.
Publish steps do `git pull --rebase` before pushing, so the three workflows
never clobber each other's commits.

Enable Pages under Settings → Pages → Deploy from branch → `main` → `/docs`;
`.nojekyll` is present so it's served as plain static HTML, no Jekyll. Each
report's footer timestamp is the freshness check.

## Companion documents

Strategy and operating documentation lives in Google Docs (single source of truth);
this README holds technical information only.

| Document | Location | Role |
|---|---|---|
| Trading Playbook (Google Doc) | Drive Trading System folder | **The** living trading document: strategy, rules, allocation, methods, lessons (22 sections) |
| Options Lab — Trading Guide & Discussion Archive | Drive Trading System folder | Append-only history of past discussions; not a reference |
| Trading System Flow (slide deck) | Drive Trading System folder | 10-slide visual overview |
| Trading Workbook | Drive Sheets | Trade journal / tracker / watchlist |
| Archive | Drive Trading System folder | Feedback-01, Feedback-02 (inputs, not live docs) |

Dashboard: https://amuse.openaimp.com — published reports only.

## Broker connectivity

Where the trading operation can reach, as of Oct 11, 2026. Checked, not assumed.

| Broker | Status | Notes |
|---|---|---|
| **Public.com** | ✅ Connected | Custom MCP connector, API-key auth. Quotes, chains, greeks, accounts, orders. The automation backbone — the key doesn't expire, so scheduled scans run untouched. |
| **Schwab** | ⚠️ Connectable with friction | OAuth 2.0 verified, connect link ready. Refresh tokens die after **7 days, hard, non-rolling** — weekly manual re-auth required. Fine for on-demand questions; hostile to autonomous monitoring. |
| **E*TRADE** | ❌ Out | OAuth 1.0a with request signing — not supported by the connector (API key or OAuth 2.0 only). Tokens expire at midnight ET daily. |
| **IBKR** | ❌ Out | OAuth 2.0 API access is FA/organizational accounts only. Individual accounts need the local Client Portal Gateway with daily re-auth. Architecturally incompatible. |
| **Moomoo** | ⚠️ Partial | Regulated US brokerage (FINRA, SIPC). No web trading terminal — browser route is dead. Official MCP server exists but no verified OAuth-MCP path through current tooling. Viable path: TradingView broker integration (live Gold-partner broker; single-leg options order panel once the user links their account). |

**Standing rule: never place, cancel, or replace an order on any connected account without explicit human confirmation.**
Screening, monitoring, and order *staging* are automated; the final submit is always human.

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
python3 src/premarket_screen.py --limit 20 --json-out /tmp/pm.json
python3 src/render_report.py --premarket /tmp/pm.json \
  --report-id premarket-sp500-2026-10-13 --source sp500 --source-detail "503 names"
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

- The MCP has no fundamentals (no P/E, market cap, earnings dates). News
  headlines can be fetched separately for reports, but premarket gap signals
  remain technical-only and earnings dates still rely on outside data.
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
