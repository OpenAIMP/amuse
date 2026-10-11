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

No stage overrules another. A perfect regime with %B at 1.1 waits at timing.
A great setup with earnings inside the window dies at preflight. Probabilities
come from option delta (market-implied), never from indicators.

## Screeners

| File | What it does |
|---|---|
| `stock_screener.py` | Technical screen with the indicator pack (below). Composite score 0–40 = base 0–30 + signals 0–10. Ends with a plain-English `READOUT` — the leader and why, rejections grouped by theme, regime census. |
| `spread_screener.py` | Bull put spreads + iron condors: 21–60 DTE, short 0.10–0.20Δ, conservative **short-bid minus long-ask** fills, width auto-scales to price (`min(5, max(1, round(spot/25)))`). Ranked by return-on-risk, with its own readout. |
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

`docs/index.html` is a static snapshot, regenerated fresh on every run — the
page itself fetches nothing. The data pipeline inside each workflow run is:

```
Public.com API → screener scripts → reports/*.json → render_report.py → docs/index.html → Pages
    (live)            (in Actions)       (artifacts)        (in Actions)        (committed)    (served)
```

**Which workflow produces it:** `daily-watch.yml`. Its last two steps run
`render_report.py` on the run's JSON outputs and commit the result to `docs/`,
so the page always shows that morning's data (check the footer timestamp for
freshness). Enable it under Settings → Pages → Deploy from branch → `main` →
`/docs`; `.nojekyll` is present so it's served as plain static HTML, no Jekyll.

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
