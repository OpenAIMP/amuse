#!/usr/bin/env python3
"""
Generalized technical stock screener (watchlist-based).

Screens a watchlist of tickers on technical gates computed from one year of
daily bars, then ranks survivors by a simple composite score. This is a
ranking tool, not a market-wide discovery engine: it cannot find names you
did not give it (the MCP has no fundamentals endpoint and no market-wide
scan). Pair it with a universe filter (e.g. a thinkScript scan) upstream.

Gates are module constants and are printed in every report.
"""
import argparse
import json
import os
import math
import subprocess
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

CLI = os.environ.get("PUBLIC_MCP_CLI", "/home/hatch/workspace/skills/public-mcp/bin/public-mcp")
ACCT = os.environ.get("PUBLIC_ACCOUNT_ID", "5OI32712")

DEFAULT_NAMES = ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "AVGO",
                 "JPM", "V", "XOM", "JNJ", "PG", "HD", "BAC", "DIS"]

# ---- screening configuration (design choices, printed in every report) ----
PRICE_MIN, PRICE_MAX = 10.0, 500.0
RSI_MIN, RSI_MAX = 30.0, 70.0
REQUIRE_ABOVE_SMA50 = True
REQUIRE_ABOVE_SMA200 = True
ATR_PCT_MIN, ATR_PCT_MAX = 1.0, 6.0
VOL_RATIO_MIN = 0.9          # 20d avg volume / 60d avg volume
MAX_OFF_HIGH_PCT = 25.0      # must be within 25% below 52-week high
MIN_BARS = 200               # need a full SMA200 of history
PERIOD = "YEAR"

RUN_DATE = datetime.now(ZoneInfo("America/New_York")).date()
RUN_TS = datetime.now(ZoneInfo("America/New_York")).isoformat(timespec="seconds")


class McpError(RuntimeError):
    pass


def mcp_call(tool, args):
    try:
        proc = subprocess.run([CLI, "call", tool, json.dumps(args)],
                              capture_output=True, text=True, timeout=120)
    except subprocess.TimeoutExpired as e:
        raise McpError(f"{tool}: CLI timed out: {e}")
    if proc.returncode != 0:
        raise McpError(f"{tool}: CLI failed: {proc.stderr[:300]}")
    try:
        d = json.loads(proc.stdout)
    except json.JSONDecodeError as e:
        raise McpError(f"{tool}: CLI returned non-JSON output: {e}")
    if not isinstance(d, dict) or "content" not in d or not d["content"]:
        raise McpError(f"{tool}: unexpected response shape")
    if d.get("isError"):
        raise McpError(f"{tool}: {json.dumps(d)[:300]}")
    try:
        return json.loads(d["content"][0]["text"])
    except (json.JSONDecodeError, KeyError, TypeError, IndexError) as e:
        raise McpError(f"{tool}: unparseable content payload: {e}")


def bars_for(symbol):
    """Return list of (close, high, low, volume), validated finite/positive."""
    p = mcp_call("get_price_history",
                 {"symbol": symbol, "account_id": ACCT,
                  "period": PERIOD, "aggregation": "ONE_DAY"})
    if not isinstance(p, dict):
        raise McpError(f"get_price_history: expected object payload for {symbol}")
    raw = p.get("regularMarket", {}).get("bars", [])
    bars = []
    for b in raw:
        try:
            c, h, l, v = (float(b["close"]), float(b["high"]),
                          float(b["low"]), float(b["volume"]))
        except (KeyError, TypeError, ValueError):
            continue
        if not all(math.isfinite(x) for x in (c, h, l, v)):
            continue
        if c <= 0 or h <= 0 or l <= 0 or v < 0:
            continue
        bars.append((c, h, l, v))
    return bars


def sma(vals, n):
    return sum(vals[-n:]) / n


def rsi14(closes):
    """Wilder's RSI(14). Returns None if insufficient data."""
    if len(closes) < 15:
        return None
    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gains = [max(d, 0.0) for d in deltas]
    losses = [max(-d, 0.0) for d in deltas]
    ag = sum(gains[:14]) / 14
    al = sum(losses[:14]) / 14
    for g, l in zip(gains[14:], losses[14:]):
        ag = (ag * 13 + g) / 14
        al = (al * 13 + l) / 14
    if al == 0:
        return 100.0
    return 100.0 - 100.0 / (1.0 + ag / al)


def atr14_pct(bars, price):
    """Wilder's ATR(14) as % of price. Returns None if insufficient data."""
    if len(bars) < 15:
        return None
    trs = []
    for i in range(1, len(bars)):
        h, l, _c = bars[i][1], bars[i][2], bars[i][0]
        pc = bars[i - 1][0]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    atr = sum(trs[:14]) / 14
    for tr in trs[14:]:
        atr = (atr * 13 + tr) / 14
    return atr / price * 100.0


def evaluate(sym, bars):
    """Return (accepted, metrics, reasons). Reasons use stable categories."""
    reasons = []
    if len(bars) < MIN_BARS:
        return False, {}, ["insufficient history"]
    closes = [b[0] for b in bars]
    price = closes[-1]
    if not (PRICE_MIN <= price <= PRICE_MAX):
        reasons.append("price out of range")
    rsi = rsi14(closes)
    if rsi is None or not (RSI_MIN <= rsi <= RSI_MAX):
        reasons.append("rsi out of range")
    s50, s200 = sma(closes, 50), sma(closes, 200)
    vs50 = (price / s50 - 1) * 100
    vs200 = (price / s200 - 1) * 100
    if REQUIRE_ABOVE_SMA50 and price < s50:
        reasons.append("below 50-day SMA")
    if REQUIRE_ABOVE_SMA200 and price < s200:
        reasons.append("below 200-day SMA")
    atrp = atr14_pct(bars, price)
    if atrp is None or not (ATR_PCT_MIN <= atrp <= ATR_PCT_MAX):
        reasons.append("ATR% out of range")
    vol20 = sum(b[3] for b in bars[-20:]) / 20
    vol60 = sum(b[3] for b in bars[-60:]) / 60
    vratio = vol20 / vol60 if vol60 > 0 else 0.0
    if vratio < VOL_RATIO_MIN:
        reasons.append("volume trend weak")
    hi52 = max(b[1] for b in bars)
    off_hi = (price / hi52 - 1) * 100
    if off_hi < -MAX_OFF_HIGH_PCT:
        reasons.append("too far below 52w high")

    def ret(n):
        return (price / closes[-n - 1] - 1) * 100 if len(closes) > n else 0.0

    metrics = {
        "price": round(price, 2), "rsi14": round(rsi, 1),
        "vs_sma50_pct": round(vs50, 1), "vs_sma200_pct": round(vs200, 1),
        "atr_pct": round(atrp, 2), "vol_ratio": round(vratio, 2),
        "off_52w_high_pct": round(off_hi, 1),
        "ret_1m_pct": round(ret(21), 1), "ret_3m_pct": round(ret(63), 1),
    }
    return (not reasons), metrics, reasons


def composite(m):
    """0-30 score: ideal 0-5% above 50-day (10) + RSI 50-65 sweet spot (10)
    + volume expansion (10). Simple and explainable by design."""
    s50 = max(0.0, 10.0 - abs(m["vs_sma50_pct"] - 2.5))
    rsi = m["rsi14"]
    if 50 <= rsi <= 65:
        s_rsi = 10.0
    elif rsi < 50:
        s_rsi = max(0.0, 10.0 - (50 - rsi) * 0.5)
    else:
        s_rsi = max(0.0, 10.0 - (rsi - 65) * 0.5)
    s_vol = min(10.0, max(0.0, m["vol_ratio"] * 6.67))
    return round(s50 + s_rsi + s_vol, 1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--names", default=None,
                    help="comma-separated watchlist, e.g. AAPL,MSFT,NVDA")
    ap.add_argument("--json-out", default=None,
                    help="write machine-readable ranked results to FILE")
    args = ap.parse_args()
    names = [n.strip().upper() for n in args.names.split(",") if n.strip()] \
        if args.names else DEFAULT_NAMES

    print(f"Technical stock screen -- run {RUN_TS} (America/New_York)")
    print(f"Settings: price ${PRICE_MIN:.0f}-${PRICE_MAX:.0f}, "
          f"RSI14 {RSI_MIN:.0f}-{RSI_MAX:.0f}, "
          f"above SMA50={'yes' if REQUIRE_ABOVE_SMA50 else 'no'}, "
          f"above SMA200={'yes' if REQUIRE_ABOVE_SMA200 else 'no'}, "
          f"ATR% {ATR_PCT_MIN:.1f}-{ATR_PCT_MAX:.1f}, "
          f"vol20/60 >= {VOL_RATIO_MIN}, "
          f"within {MAX_OFF_HIGH_PCT:.0f}% of 52w high, "
          f"daily bars ({PERIOD}).")

    passing, rejected = [], {}
    for sym in names:
        try:
            bars = bars_for(sym)
        except McpError as e:
            rejected[sym] = [f"data error: {e}"]
            continue
        except Exception as e:  # never let one ticker kill the run
            rejected[sym] = [f"unexpected error: {type(e).__name__}"]
            continue
        try:
            ok, metrics, reasons = evaluate(sym, bars)
        except Exception as e:
            rejected[sym] = [f"evaluation error: {type(e).__name__}"]
            continue
        if ok:
            metrics["score"] = composite(metrics)
            metrics["symbol"] = sym
            passing.append(metrics)
        else:
            rejected[sym] = reasons

    passing.sort(key=lambda m: -m["score"])
    print(f"\n{'sym':<6}{'price':>9}{'RSI14':>7}{'vs50d%':>8}{'vs200d%':>9}"
          f"{'ATR%':>7}{'vol':>6}{'offHi%':>8}{'1m%':>7}{'3m%':>7}{'score':>7}")
    for m in passing:
        print(f"{m['symbol']:<6}{m['price']:>9.2f}{m['rsi14']:>7.1f}"
              f"{m['vs_sma50_pct']:>8.1f}{m['vs_sma200_pct']:>9.1f}"
              f"{m['atr_pct']:>7.2f}{m['vol_ratio']:>6.2f}"
              f"{m['off_52w_high_pct']:>8.1f}{m['ret_1m_pct']:>7.1f}"
              f"{m['ret_3m_pct']:>7.1f}{m['score']:>7.1f}")
    if not passing:
        print("(no names passed all gates)")
    print("\nRejections:")
    if rejected:
        for sym in names:
            if sym in rejected:
                print(f"  {sym}: {'; '.join(rejected[sym])}")
    else:
        print("  none -- every name passed")

    if args.json_out:
        with open(args.json_out, "w") as f:
            json.dump({"asof": RUN_DATE.isoformat(),
                       "settings": {
                           "price_range": [PRICE_MIN, PRICE_MAX],
                           "rsi14_range": [RSI_MIN, RSI_MAX],
                           "require_above_sma50": REQUIRE_ABOVE_SMA50,
                           "require_above_sma200": REQUIRE_ABOVE_SMA200,
                           "atr_pct_range": [ATR_PCT_MIN, ATR_PCT_MAX],
                           "vol_ratio_min": VOL_RATIO_MIN,
                           "max_off_high_pct": MAX_OFF_HIGH_PCT,
                           "period": PERIOD},
                       "passing": passing,
                       "rejected": rejected}, f, indent=1)
        print(f"\nwrote {args.json_out}", file=sys.stderr)


if __name__ == "__main__":
    main()
