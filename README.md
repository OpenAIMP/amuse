# Options Lab — screeners that run on GitHub Actions

Stock and options screeners that pull live market data through Public.com's
hosted MCP server. Runs here on a schedule; runs identically on any machine
with Python 3.10+ and a Public.com API key.

## What runs here

| Workflow | Schedule | What it does |
|---|---|---|
| `daily-watch.yml` | Weekdays 9:35am ET | Technical stock screen + PMCC exception watch. Reports only material changes. |
| `monthly-screen.yml` | 3rd of each month, 9:35am ET | Full PMCC pair-quality re-rank with JSON + text report. |

Both can also be triggered manually from the Actions tab (workflow_dispatch).
Run outputs are kept as workflow artifacts for 90 days.

## Scripts

| File | What it does |
|---|---|
| `pmcc_quality.py` | Pair-quality PMCC screener: 0.80–0.95Δ LEAPS (270–800 DTE) × 0.15–0.35Δ short calls (21–60 DTE), evaluated as pairs with liquidity, friction, capital, and earnings gates. Ranks by 30-day premium-to-debit. |
| `pmcc_watch.py` | Daily exception monitor: diffs today's screen vs saved state, reports only new qualifiers, dropouts, or 1.5+ pt yield shifts. |
| `stock_screener.py` | Technical stock screener: RSI14, SMA50/200, ATR%, volume trend, distance from 52w high — configurable gates, composite ranking. |
| `spread_screener.py` | Bull put spread + iron condor selector with the same gate architecture as the PMCC screener. |
| `semis.py` | Semiconductor momentum screen. |
| `pmcc.py`, `pmcc_value.py`, `pmcc_etf.py` | Earlier one-off pricers and studies. |

## The watchlist

`watchlist.txt` is the single shared watchlist — one symbol per line. Every
screener in the daily workflow runs against it. Edit the file, commit, and the
next scheduled run picks it up. For a one-off screen of different names, use
the Actions tab → Daily screen watch → Run workflow → paste names into the
`names` input. Locally: `python3 spread_screener.py --names T,VZ,XOM`.

## Setup

1. Create a **repository secret** named `PUBLIC_API_KEY` (Settings → Secrets and
   variables → Actions → New repository secret) containing your Public.com API key.
2. Optionally set a repository **variable** `PUBLIC_ACCOUNT_ID` (same page, Variables
   tab). Defaults to `5OI32712`.
3. That's it — the workflows do the rest.

## Running locally

```bash
export PUBLIC_API_KEY="your-key"          # or use the vault-backed CLI below
export PUBLIC_MCP_CLI="$PWD/bin/public-mcp"
export PUBLIC_ACCOUNT_ID="5OI32712"       # optional
python3 pmcc_quality.py
python3 stock_screener.py --names T,VZ
python3 pmcc_watch.py
```

Without `PUBLIC_API_KEY`, the scripts fall back to `PUBLIC_MCP_CLI` pointing at
a vault-authenticated CLI (the default path is the local dev machine's).

## Key conventions

- Debits estimated conservatively: **long ask − short bid**, never midpoints.
- `premium_to_debit_30d` is a screening ratio, not an expected return.
- Contracts assumed standard 100-share deliverables (not validated).
- **These scripts screen and monitor only. They never place orders.**

