# Options Lab

Stock and options screeners that pull live market data through Public.com's
hosted MCP server — built around one idea: **no indicator places a trade.**
Every signal answers exactly one question, and a trade only happens when they
all agree.

## The operating loop

```
Screen → Regime → Timing → Strikes → Size → Preflight
```

| Stage | Question it answers | What answers it |
|---|---|---|
| **Screen** | Which names are worth looking at? | The screeners, over `watchlist.txt` or an index universe |
| **Regime** | Bullish, bearish, or neutral — which strategy family? | Trend structure (HH/HL), SMA50/200, anchored VWAP |
| **Timing** | Is *now* a good entry, or wait? | %B, RSI14, Bollinger squeeze |
| **Strikes** | Where does the structure go? | Fib retracements, swing pivots — short strikes sit behind real structure |
| **Size** | How much can this lose? | 1–2% max loss per trade, total heat under 40% |
| **Preflight** | Anything that kills the trade? | Buying power, earnings/events, fees — then human confirmation |

No stage overrules another. A perfect regime with %B at 1.0 waits at timing.
A great setup with earnings inside the window dies at preflight. Probabilities
come from option delta (market-implied), never from indicators.

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

## Screeners

| File | What it does |
|---|---|
| `stock_screener.py` | Technical screen with the indicator pack (below). Composite score 0–40 = base 0–30 + signals 0–10. Ends with a plain-English `READOUT` — the leader and why, rejections grouped by theme, regime census. |
| `spread_screener.py` | Income-structure selector: bull put spreads, iron condors, and defined-risk Jade Lizards (bull put spread + far-OTM call wing for bullish regimes). 21–60 DTE, short 0.10–0.20Δ, conservative **short-bid minus long-ask** fills, width auto-scales to price (`min(5, max(1, round(spot/25)))`). Ranked by return-on-risk, with its own readout. |
| `daytrade_screen.py` | Pre-market day-trading screen over the S&P 500: gap %, relative volume, developing VWAP distance, ATR range position. Bias stated as bias ("gap-and-go" / "fade risk"), never prediction. |
| `pmcc_quality.py` | PMCC pair-quality: 0.80–0.95Δ LEAPS (270–800 DTE) × 0.15–0.35Δ short calls (21–60 DTE), evaluated as pairs with liquidity, friction, capital, and earnings gates. |
| `pmcc_watch.py` | Daily exception monitor: diffs today's screen vs cached state, reports only new qualifiers, dropouts, or 1.5+ pt yield shifts. |
| `scan_loop.py` | Runs any screener across multiple index universes and merges into one cross-universe leaderboard. |
| `semis.py` | Semiconductor momentum screen (earlier study). |
| `render_report.py` | Renders dated report pages (plus `.meta.json` sidecars) from screener JSONs. |
| `render_hub.py` | Rebuilds `docs/index.html` — the report archive homepage — from all sidecars. |

## The indicator pack (`stock_screener.py`)

| Indicator | Role | Key reads |
|---|---|---|
| Bollinger Bands (20×2.0) | Timing | %B > 1.0 = extended, don't chase (hard reject); squeeze (125-day bandwidth min) = wait or size down |
| Anchored VWAP (52-week low) | Regime | Below it = institutional money underwater (hard reject for bullish income) |
| Session VWAP | Timing | Last completed session; distance reported, never a reject on missing data |
| Fractal pivots (n=5) + Fib 38.2/50/61.8% | Strikes | Short strikes go below the 61.8% retracement or last swing low |
| HH/HL trend structure | Regime | Downtrend = rejection; only uptrends get full bullish treatment |

Deliberately **not** automated: Elliott Wave counting — too subjective; pivots
and Fibs capture the objective machinery underneath it.

Unknown data is always a flag, never a rejection. Rejections carry stable
reason categories and are all printed — nothing is silently dropped.

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

| Workflow | Schedule | Scripts it runs, in order | Publishes |
|---|---|---|---|
| `daily-watch.yml` | Weekdays 9:35am ET | `stock_screener` → `spread_screener` → `pmcc_watch` → `render_report` → `render_hub` | `docs/reports/daily-<source>-<date>.html` |
| `daytrade-screen.yml` | Weekdays 9:00am ET | `daytrade_screen` → `render_report` → `render_hub` | `docs/reports/daytrade-<source>-<date>.html` |
| `monthly-screen.yml` | 3rd of each month, 9:35am ET | `pmcc_quality` → `render_report` → `render_hub` | `docs/reports/pmcc-<source>-<yyyy-mm>.html` |

`daily-watch.yml` accepts `names` and `universe` inputs on manual runs;
`daytrade-screen.yml` accepts `names` and `limit`; `monthly-screen.yml`
accepts `names`. Run outputs are kept as workflow artifacts for 90 days.
Publish steps do `git pull --rebase` before pushing, so the three workflows
never clobber each other's commits.

Enable Pages under Settings → Pages → Deploy from branch → `main` → `/docs`;
`.nojekyll` is present so it's served as plain static HTML, no Jekyll. Each
report's footer timestamp is the freshness check.

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
cd ~/workspace/options-lab

# 1. Screen → JSON (--names overrides --universe)
python3 stock_screener.py --names T,VZ,XOM --json-out /tmp/stock.json
python3 spread_screener.py --names T,VZ,XOM --json-out /tmp/spreads.json

# 2. Render the dated report
python3 render_report.py --stock /tmp/stock.json --spreads /tmp/spreads.json \
  --report-id daily-custom-2026-10-11 --source custom --source-detail "3 names"

# 3. Rebuild the archive, then open repo/docs/index.html in a browser
python3 render_hub.py
```

Variations — other universes, other report kinds:

```bash
python3 stock_screener.py --universe nasdaq100 --json-out /tmp/stock.json
python3 scan_loop.py --screener stock_screener.py --universes sp100,nasdaq100
python3 daytrade_screen.py --limit 20 --json-out /tmp/dt.json
python3 render_report.py --daytrade /tmp/dt.json \
  --report-id daytrade-sp500-2026-10-13 --source sp500 --source-detail "503 names"
python3 pmcc_quality.py --names T,VZ,XOM --json-out /tmp/pmcc.json
python3 render_report.py --pmcc /tmp/pmcc.json \
  --report-id pmcc-custom-2026-10 --source custom --source-detail "3 names"
```

`render_report.py` writes to `repo/docs/` locally and `./docs/` in CI; all
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

## Honest limitations

- The MCP has no fundamentals (no P/E, market cap, earnings dates) and no
  news/catalyst feed — gaps are technical-only; earnings come from outside data.
- Request/response API, not streaming: scheduled scans, not tick-level real-time.
- A full S&P 500 stock screen is ~1,000 API calls and takes ~20 minutes; the
  spread screener on 500 names takes an hour-plus — these are scheduled jobs,
  not interactive ones.
