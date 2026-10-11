#!/usr/bin/env python3
"""Bullish-semis momentum screen: 1m/3m returns, distance from 6m high, vs 50-day, volume trend."""
import json
import os, subprocess, sys

CLI = os.environ.get("PUBLIC_MCP_CLI", "/home/hatch/workspace/skills/public-mcp/bin/public-mcp")
SYMBOLS = ["NVDA", "AMD", "AVGO", "TSM", "MU", "LRCX", "AMAT", "QCOM", "ARM", "INTC", "KLAC", "ASML"]

def call(tool, args):
    out = subprocess.run([CLI, "call", tool, json.dumps(args)],
                         capture_output=True, text=True, timeout=120)
    if out.returncode != 0:
        raise RuntimeError(f"{tool} failed: {out.stderr[:300]}")
    d = json.loads(out.stdout)
    if d.get("isError"):
        raise RuntimeError(f"{tool} error: {json.dumps(d)[:300]}")
    return d

def bars_for(symbol):
    d = call("get_price_history", {"symbol": symbol, "period": "HALF_YEAR", "aggregation": "ONE_DAY"})
    payload = json.loads(d["content"][0]["text"])
    bars = payload["regularMarket"]["bars"]
    return [(float(b["close"]), float(b["high"]), float(b["low"]), float(b["volume"])) for b in bars]

rows = []
for sym in SYMBOLS:
    try:
        bars = bars_for(sym)
    except Exception as e:
        print(f"SKIP {sym}: {e}", file=sys.stderr)
        continue
    closes = [b[0] for b in bars]
    highs = [b[1] for b in bars]
    cur = closes[-1]
    def ret(n):
        return (cur / closes[-n-1] - 1) * 100 if len(closes) > n else float("nan")
    r1m, r3m = ret(21), ret(63)
    hi6 = max(highs)
    off_hi = (cur / hi6 - 1) * 100
    sma50 = sum(closes[-50:]) / min(50, len(closes))
    above50 = (cur / sma50 - 1) * 100
    vol20 = sum(b[3] for b in bars[-20:]) / 20
    vol60 = sum(b[3] for b in bars[-60:]) / 60
    vol_ratio = vol20 / vol60 if vol60 else float("nan")
    score = r1m + 0.5 * r3m + 0.5 * above50 + 0.3 * off_hi
    rows.append(dict(sym=sym, price=cur, r1m=r1m, r3m=r3m, off_hi=off_hi,
                     above50=above50, vol_ratio=vol_ratio, score=score))

rows.sort(key=lambda r: r["score"], reverse=True)
print(f"{'sym':<6}{'price':>10}{'1m%':>8}{'3m%':>8}{'off6mHi%':>10}{'vs50d%':>9}{'vol20/60':>9}{'score':>8}")
for r in rows:
    print(f"{r['sym']:<6}{r['price']:>10.2f}{r['r1m']:>8.1f}{r['r3m']:>8.1f}"
          f"{r['off_hi']:>10.1f}{r['above50']:>9.1f}{r['vol_ratio']:>9.2f}{r['score']:>8.1f}")
