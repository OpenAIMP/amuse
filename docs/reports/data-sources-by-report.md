# Data Sources by Report — What Feeds What, and What Happens When Data Is Missing

**Generated:** 2026-10-15
**Repo:** OpenAIMP/amuse (main)

---

## Quick Answer: Does the screener use news as input?

**No.** News is display-only. It appears in the "Catalyst watch" section of the rendered HTML report, but it does not influence any screening decision, score, gate, or recommendation. The screeners (`stock_screener.py`, `spread_screener.py`) and the decision engine (`decision_engine.py`) never read news data.

If news is unavailable, the Catalyst section renders empty. Nothing else changes.

---

## Data Flow Overview

```
Public.com MCP API (via bin/public-mcp)
  ├── get_price_history  → daily/intraday bars
  ├── get_quotes         → current prices
  ├── get_option_chain   → option contracts + Greeks
  └── get_option_expirations → available expirations
          │
          ▼
  ┌───────────────┐  ┌────────────────┐  ┌──────────────┐
  │ stock_screener │  │ spread_screener │  │ pmcc_watch   │
  └───────┬───────┘  └───────┬────────┘  └──────────────┘
          │                  │
          ▼                  ▼
  ┌─────────────────────────────────┐
  │ decision_engine.py (6 gates)    │
  └──────────────┬──────────────────┘
                 │
                 ▼
  ┌─────────────────────────────────┐
  │ render_report.py → HTML report  │
  │  (+ fetch_news.py → Catalyst    │
  │     section, display-only)      │
  └─────────────────────────────────┘
```

---

## Per-Report Data Sources

### 1. Daily Watch Report (`daily-watchlist-*.html`)

| Data | Source | Used By | Required? |
|------|--------|---------|-----------|
| Daily price bars (1yr) | MCP `get_price_history` | `stock_screener.py` — RSI, SMA, ATR, Bollinger, VWAP, pivots, trend | **Yes** — no bars = "incomplete data" |
| Current quotes | MCP `get_quotes` (batched) | `spread_screener.py` — spot price for strike selection | **Yes** — no quote = symbol skipped |
| Option chains | MCP `get_option_chain` | `spread_screener.py` — bid/ask, Greeks, OI, volume | **Yes** — no chain = no structures |
| Option expirations | MCP `get_option_expirations` | `spread_screener.py` — DTE filtering | **Yes** |
| Earnings dates | `src/earnings_dates.json` (curated) | `spread_screener.py` — earnings-in-window reject | No — unknown = flagged, not rejected |
| IV history | `state/iv_history.jsonl` (accumulated) | `spread_screener.py` — vol assessment (IV Rank) | No — missing = "NO_READ", veto-only gate |
| Portfolio risk | `reports/portfolio-risk.json` | `render_report.py` — portfolio section | No — missing = "not supplied" |
| News headlines | Google News RSS via `fetch_news.py` | `render_report.py` — Catalyst watch section | No — missing = empty section |
| Prior decisions | `reports/decision.json` | `render_report.py` — decision reasoning | No — missing = section skipped |

### 2. Leverage ETF Report (`daily-lev_etf-*.html`)

Same data sources as Daily Watch, but with `--universe lev_etf` (29 names). No decision engine step — structures are listed with verdicts but no TRADE/NO-TRADE recommendation.

### 3. Premarket Report (`premarket-watchlist-*.html`)

| Data | Source | Used By | Required? |
|------|--------|---------|-----------|
| Daily bars | MCP `get_price_history` | `premarket_screen.py` — prior close, ATR, avg volume | **Yes** |
| Intraday bars | MCP `get_price_history` (5-min) | `premarket_screen.py` — gap %, premarket volume | **Yes** — no bars = "no intraday bars" |
| Current quotes | MCP `get_quotes` or quote_map | `premarket_screen.py` — current price for gap calc | **Yes** — no quote = "no quote" |

**Note:** Premarket explicitly does NOT use news. From `premarket_screen.py`: *"the MCP has no news/catalyst feed, so gaps driven by news cannot be classified — treat every gap here as technical-only."*

### 4. Intraday Report (`intraday-nasdaq100-*.html`)

| Data | Source | Used By | Required? |
|------|--------|---------|-----------|
| Intraday bars (15-min) | MCP `get_price_history` | `intraday_screen.py` — opening range, VWAP, breakouts | **Yes** |
| Daily bars | MCP `get_price_history` | `intraday_screen.py` — ATR, context | **Yes** |

### 5. Monthly PMCC Report

| Data | Source | Used By | Required? |
|------|--------|---------|-----------|
| Option chains (LEAPS) | MCP `get_option_chain` | `pmcc.py` — long call selection | **Yes** |
| Option chains (monthlies) | MCP `get_option_chain` | `pmcc.py` — short call selection | **Yes** |
| Stock fundamentals | MCP `get_quotes` + daily bars | `pmcc.py` — underlying quality | **Yes** |

---

## What Happens When Data Is Unavailable

### MCP API Failures (401, timeout, etc.)

| Failure | Behavior |
|---------|----------|
| `get_quotes` fails | Symbol marked "incomplete data", skipped from spread screening |
| `get_price_history` fails | Symbol marked "incomplete data", skipped from stock screening |
| `get_option_chain` fails | No structures generated for that symbol; logged as rejection note |
| All symbols fail | Report renders with 0 qualified, all "incomplete data"; workflow still exits 0 (success) |
| `PUBLIC_API_KEY` invalid (401) | Every MCP call fails; entire screen produces empty results (seen 2026-10-14 with leverage-screen.yml) |

**Critical:** The workflows do NOT fail on data errors. They complete "successfully" with empty results. An empty report is not distinguished from a legitimately empty screen unless you check the "incomplete data" count.

### News Unavailable

| Scenario | Behavior |
|----------|----------|
| Google News RSS timeout | `fetch_news.py` swallows per-feed; returns empty list for that feed |
| All feeds fail | `reports/news.json` has empty tickers dict; Catalyst section renders empty |
| `fetch_news.py` not run | `render_report.py --news` gets no file; section skipped gracefully |
| **Impact on decisions** | **Zero.** News never feeds into any gate, score, or recommendation. |

The docstring in `fetch_news.py` is explicit: *"Failures are swallowed per-feed (an empty list), never fatal — the renderers degrade gracefully."*

### Earnings Dates Unknown

| Scenario | Behavior |
|----------|----------|
| Symbol not in `earnings_dates.json` | Spread is flagged "earnings date unknown" but NOT rejected |
| Symbol has earnings in window (21-60 DTE) | Spread is **rejected** (hard gate) |
| **Rationale** | Fail-open on unknown (can't prove a negative), fail-closed on known conflict |

### IV History Missing

| Scenario | Behavior |
|----------|----------|
| `state/iv_history.jsonl` missing or < 30 snapshots | Vol assessment returns "NO_READ" |
| Vol gate decision | Veto-only: STAND_DOWN removes structures; SELL_PREMIUM/NO_READ pass through |
| **Impact** | Cannot *create* candidates, only *remove* them. Missing IV history never blocks a trade. |

### Portfolio Risk Missing

If `reports/portfolio-risk.json` doesn't exist, the report shows "Portfolio risk not supplied." No impact on screening.

---

## Data Freshness Notes

- **Quotes and chains** are real-time during market hours, stale after close/weekends
- **After-hours runs** return zero spread candidates (the 25%-of-mid liquidity gate rejects stale quotes)
- **IV history** accumulates one snapshot per daily run; needs 30 for full IV Rank (still warming up as of 2026-10-12)
- **News** is fetched at render time from Google News RSS (no API key, no auth)
- **Earnings dates** are manually curated in `src/earnings_dates.json` — not auto-updated
