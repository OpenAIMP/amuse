#!/usr/bin/env python3
"""Shared market-data fetching via the MCP (issue #36).

Canonical bar representation: dicts with keys
  date/ts, open, high, low, close, volume
(open may be None when the feed omits it; callers treat a missing open
as unknown, never as zero.)

Replaces the per-screener bars_for / daily_bars_for / intraday_bars_for /
quotes_for copies. Validation rules are the union of the originals:
finite + positive prices, non-negative volume, unparseable rows skipped.
"""
import math
from datetime import datetime

import mcp_client


def _clean_ohlcv(o, h, l, c, v):
    """Validate one OHLCV row. Returns (o, h, l, c, v) or None."""
    try:
        o = float(o) if o is not None else None
        h, l, c, v = float(h), float(l), float(c), float(v)
    except (TypeError, ValueError):
        return None
    if not all(math.isfinite(x) for x in (h, l, c, v)):
        return None
    if h <= 0 or l <= 0 or c <= 0 or v < 0:
        return None
    if o is not None and (not math.isfinite(o) or o <= 0):
        o = None
    return o, h, l, c, v


def daily_bars(symbol, account_id, period="YEAR"):
    """Daily bars, oldest first.

    Returns list of {"date": date, "open": f|None, "high": f, "low": f,
    "close": f, "volume": f}.
    """
    p = mcp_client.mcp_call("get_price_history",
                 {"symbol": symbol, "account_id": account_id,
                  "period": period, "aggregation": "ONE_DAY"})
    if not isinstance(p, dict):
        raise mcp_client.McpError(f"get_price_history daily: bad payload for {symbol}")
    bars = []
    for b in p.get("regularMarket", {}).get("bars", []):
        try:
            day = datetime.fromisoformat(b["timestamp"]).date()
        except (KeyError, TypeError, ValueError):
            continue
        row = _clean_ohlcv(b.get("open"), b.get("high"), b.get("low"),
                           b.get("close"), b.get("volume"))
        if row is None:
            continue
        o, h, l, c, v = row
        bars.append({"date": day, "open": o, "high": h, "low": l,
                     "close": c, "volume": v})
    return bars


def intraday_bars(symbol, account_id, period="DAY", aggregation="FIVE_MINUTES",
                  session="REGULAR_AND_EXTENDED_HOURS"):
    """Intraday bars, oldest first. Returns (bars, expected_bars).

    Each bar: {"ts": datetime, "open": f, "high": f, "low": f, "close": f,
    "volume": f}. expected_bars comes from the payload when present.
    """
    p = mcp_client.mcp_call("get_price_history",
                 {"symbol": symbol, "account_id": account_id,
                  "period": period, "aggregation": aggregation,
                  "trading_session_toggle": session})
    if not isinstance(p, dict):
        raise mcp_client.McpError(f"get_price_history intraday: bad payload for {symbol}")
    rm = p.get("regularMarket", {})
    expected = rm.get("expectedBars")
    bars = []
    for b in rm.get("bars", []):
        try:
            ts = datetime.fromisoformat(b["timestamp"])
        except (KeyError, TypeError, ValueError):
            continue
        row = _clean_ohlcv(b.get("open"), b.get("high"), b.get("low"),
                           b.get("close"), b.get("volume"))
        if row is None:
            continue
        o, h, l, c, v = row
        if o is None:
            continue  # intraday math needs the open
        bars.append({"ts": ts, "open": o, "high": h, "low": l,
                     "close": c, "volume": v})
    return bars, expected


def quotes(symbols, account_id):
    """Batch quotes for many symbols in ONE get_quotes call.

    Returns {symbol: price}. Symbols missing from the payload are absent
    from the map (caller treats as unknown quote, never as zero).
    """
    symbols = list(symbols)
    out = {}
    q = mcp_client.mcp_call("get_quotes", {"symbols": symbols, "account_id": account_id})

    def walk(o):
        if isinstance(o, dict):
            s = o.get("instrument", {}).get("symbol")
            if s in symbols and s not in out:
                for k in ("last", "price", "mark"):
                    v = o.get(k)
                    try:
                        v = float(v)
                    except (TypeError, ValueError):
                        continue
                    if math.isfinite(v) and v > 0:
                        out[s] = v
                        break
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    walk(q)
    return out


def quote(symbol, account_id):
    """Single-symbol quote. Returns price or None."""
    return quotes([symbol], account_id).get(symbol)
