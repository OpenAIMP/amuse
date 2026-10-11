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
| `render_report.py` | Turns screener JSONs into the static HTML dashboard served by GitHub Pages. |

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

## How the pieces fit together

Every run follows the same pipeline — screeners produce JSON, renderers turn
JSON into pages:

```
                         ┌─ stock_screener.py ──┐
watchlist.txt ──┬─ daily ┤  spread_screener.py ─┼─→ reports/*.json ─┬─→ render_report.py --report-id daily-<date>
(universe opt)  │        └─ pmcc_watch.py ──────┘                    │         ↓
                │                                                   └─→ render_hub.py ─→ docs/index.html (hub)
                ├─ pre-market: daytrade_screen.py → reports/*.json ─┬─→ render_report.py --report-id daytrade-<date>
                │                                                   └─→ render_hub.py ─→ docs/index.html (hub)
                └─ monthly: pmcc_quality.py ────→ reports/*.json ─┬─→ render_report.py --report-id pmcc-<yyyy-mm>
                                                                   └─→ render_hub.py ─→ docs/index.html (hub)
```

Shared pieces: `universes.py` (frozen index lists imported by every screener;
`--names` overrides `--universe`), `scan_loop.py` (runs any screener across
several universes and merges the leaderboards).

Which workflow runs what:

| Workflow | Scripts it runs, in order | Publishes |
|---|---|---|
| `daily-watch.yml` | `stock_screener` → `spread_screener` → `pmcc_watch` → `render_report --report-id daily-<date>` → `render_hub` | `docs/reports/daily-<date>.html` |
| `daytrade-screen.yml` | `daytrade_screen` → `render_report --daytrade --report-id daytrade-<date>` → `render_hub` | `docs/reports/daytrade-<date>.html` |
| `monthly-screen.yml` | `pmcc_quality` → `render_report --pmcc --report-id pmcc-<yyyy-mm>` → `render_hub` | `docs/reports/pmcc-<yyyy-mm>.html` |

The same pipeline runs locally: screen to JSON, render the report, open it —

```bash
python3 spread_screener.py --names XOM --json-out /tmp/sp.json
python3 render_report.py --spreads /tmp/sp.json --report-id daily-test
python3 render_hub.py   # only needed for the hub page
```

## Universes

`universes.py` holds frozen constituent lists (2026-10-11, from Wikipedia):
`sp500` (503), `sp100` (101), `nasdaq100` (101), `dow30` (30). Every screener
accepts `--universe <key>`; `--names` overrides it. Dotted symbols are kept
verbatim (`BRK.B` resolves; `BRK-B` does not).

On a manual workflow run, the `universe` input screens that whole index and
the dashboard shows its results. Notes:

- Each run **overwrites** `docs/index.html` — the dashboard always reflects the
  most recent run. A manual Nasdaq-100 run replaces the watchlist view until
  the next scheduled run restores it.
- The PMCC watch ignores the universe and stays on the watchlist — LEAPS
  chains over 500 names isn't practical.
- Weight: the stock screener handles `sp500` in ~20 min, but the spread
  screener pulls full chains + Greeks per name (an hour-plus on 500 names).
  `sp100`/`nasdaq100` are the sweet spot for options.

## Dashboard

`docs/index.html` is the **report archive homepage** — every report every
workflow ever produced, grouped by workflow (Daily screen / Pre-market
day-trade / Monthly PMCC), then by universe, newest first. Nothing is pruned.

```
docs/index.html                              ← archive homepage, rebuilt every run
docs/reports/daily-nasdaq100-2026-10-11.html ← one dated report (+ .meta.json sidecar)
docs/reports/daily-watchlist-2026-10-11.html
docs/reports/daytrade-sp500-2026-10-13.html
docs/reports/pmcc-watchlist-2026-10.html
```

The data pipeline inside each workflow run is:

```
Public.com API → screeners → reports/*.json → render_report.py → docs/reports/<type>-<source>-<date>.html → render_hub.py → docs/index.html → Pages
    (live)          (in Actions)     (artifacts)      (dated page + provenance)              (archive)          (served)
```

- `render_report.py --report-id <type>-<source>-<date> --source <key> --source-detail "<n> names"`
  renders one dated report plus a tiny `.meta.json` sidecar (title, one-line
  blurb, stat counts, source). Each report carries a provenance banner, e.g.
  "Source: Nasdaq-100 · 101 names · Run 2026-10-11" — the workflow derives the
  source from its `universe`/`names` inputs, defaulting to `watchlist`.
- `render_hub.py` reads all sidecars and rebuilds the archive: grouped entries
  with source chips, blurbs, and stat chips.
- Publish steps do `git pull --rebase` before pushing, so the three workflows
  never clobber each other's commits.

Enable under Settings → Pages → Deploy from branch → `main` → `/docs`;
`.nojekyll` is present so it's served as plain static HTML, no Jekyll. Each
report's footer timestamp is the freshness check.

## What runs here

| Workflow | Schedule | What it does |
|---|---|---|
| `daily-watch.yml` | Weekdays 9:35am ET | Stock screen + spread screen + PMCC exception watch; renders + publishes dashboard |
| `daytrade-screen.yml` | Weekdays 9:00am ET | Pre-market S&P 500 gap/volume/VWAP scan |
| `monthly-screen.yml` | 3rd of each month, 9:35am ET | Full PMCC pair-quality re-rank |

All three accept `names` and `universe` inputs on manual runs. Run outputs are
kept as workflow artifacts for 90 days.

## The watchlist

`watchlist.txt` is the default shared watchlist — one symbol per line. Edit it,
commit, and the next scheduled run picks it up.

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
python3 stock_screener.py --universe nasdaq100
python3 spread_screener.py --names T,VZ,XOM
python3 scan_loop.py --screener stock_screener.py --universes sp100,nasdaq100
python3 daytrade_screen.py --limit 20
```

### Producing reports locally

The same pipeline the workflows run — screen to JSON, render the dated
report, rebuild the archive homepage:

```bash
cd ~/workspace/options-lab
python3 stock_screener.py --names T,VZ,XOM --json-out /tmp/stock.json
python3 spread_screener.py --names T,VZ,XOM --json-out /tmp/spreads.json
python3 render_report.py --stock /tmp/stock.json --spreads /tmp/spreads.json \
  --report-id daily-watchlist-2026-10-11 --source watchlist --source-detail "20 names"
python3 render_hub.py
```

Then open `repo/docs/index.html` in a browser — the archive lists the report,
click through to read it. (`render_report.py` writes to `repo/docs/` locally
and `./docs/` in CI automatically; all links are relative, so it works from
`file://` and from Pages identically.)

Other report kinds:

```bash
python3 render_report.py --daytrade /tmp/dt.json \
  --report-id daytrade-sp500-2026-10-13 --source sp500 --source-detail "503 names"
python3 render_report.py --pmcc /tmp/pmcc.json \
  --report-id pmcc-watchlist-2026-10 --source watchlist --source-detail "20 names"
```

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
- A full S&P 500 screen is ~1,000 API calls and takes ~20 minutes — it's a
  scheduled job, not an interactive one.
