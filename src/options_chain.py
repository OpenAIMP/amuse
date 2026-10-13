#!/usr/bin/env python3
"""Shared option-chain plumbing (issue #36).

Consolidates the per-screener copies from spread_screener.py and
pmcc_quality.py. The two implementations were nearly identical; the unified
versions preserve both behaviors:
- parse_osi: strike rounded to 3 decimals (spread_screener's version)
- greeks: `signed` flag selects delta validation range
  (signed=True → [-1, 1] for put spreads; signed=False → [0, 1] for PMCC calls)
"""
import math
import re
from datetime import date

import mcp_client

OSI_RE = re.compile(r"^(.+?)(\d{6})([CP])(\d{8})$")


def parse_osi(osi):
    """Parse an OCC option symbol. Returns (expiration_iso, is_call, strike).

    Raises ValueError on malformed symbols. Strike rounded to 3 decimals.
    """
    m = OSI_RE.match(osi)
    if not m:
        raise ValueError(f"unparseable OSI: {osi}")
    yy, mm, dd = int(m.group(2)[:2]), int(m.group(2)[2:4]), int(m.group(2)[4:6])
    exp = date(2000 + yy, mm, dd).isoformat()
    return exp, m.group(3) == "C", round(int(m.group(4)) / 1000.0, 3)


def optional_int(value):
    """Parse an optional integer field. None on missing/unparseable."""
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def dte(exp):
    """Days to expiration. Accepts a date or an ISO date string.

    Negative if expired. Reference is today's date (the originals used
    an ET-today RUN_DATE; the difference only matters around midnight).
    """
    if isinstance(exp, str):
        exp = date.fromisoformat(exp)
    return (exp - date.today()).days


def eligible_expirations(expirations, minimum, maximum):
    """Sorted unique expirations with minimum <= dte <= maximum."""
    return sorted({e for e in expirations if minimum <= dte(e) <= maximum})


def parse_chain(sym, exp, account_id, min_liquidity, max_spread_pct,
               want="calls"):
    """Return ({osi: contract}, diagnostics, [rejected]). want in {"puts", "calls"}.

    Contract keyed by full OSI symbol; type and expiration validated from the
    symbol itself. Bid/ask preserved; no midpoints stored for decisions.
    Liquidity, spread-width, and quote sanity gates applied here.

    The rejected list (issue #38) carries every contract that failed a gate,
    with its raw quote data and the specific gate name — nothing is silently
    dropped from the report.
    """
    assert want in ("puts", "calls")
    p = mcp_client.mcp_call("get_option_chain",
                 {"symbol": sym, "expiration_date": exp,
                  "account_id": account_id})
    if not isinstance(p, dict):
        raise mcp_client.McpError(f"get_option_chain: expected object payload for {sym} {exp}")
    want_call = (want == "calls")
    out, diag = {}, {"bad_symbol": 0, "wrong_type_or_expiry": 0,
                     "bad_quote": 0, "wide_spread": 0,
                     "liquidity_unknown": 0, "insufficient_liquidity": 0}
    rejected = []

    def _reject(gate, osi=None, strike=None, bid=None, ask=None,
                oi=None, vol=None):
        diag[gate] += 1
        rejected.append({"gate": gate, "sym": osi, "strike": strike,
                         "bid": bid, "ask": ask,
                         "open_interest": oi, "volume": vol,
                         "expiration": exp,
                         "type": "call" if want_call else "put"})

    for c in p.get(want, []):
        try:
            osi = c["instrument"]["symbol"]
            c_exp, is_call, k = parse_osi(osi)
        except (ValueError, KeyError, TypeError):
            _reject("bad_symbol")
            continue
        if is_call != want_call or c_exp != exp:
            _reject("wrong_type_or_expiry", osi, k)
            continue
        try:
            bid, ask = float(c["bid"] or 0), float(c["ask"] or 0)
        except (TypeError, ValueError):
            _reject("bad_quote", osi, k)
            continue
        if not (math.isfinite(bid) and math.isfinite(ask)) or bid <= 0 or ask < bid:
            _reject("bad_quote", osi, k, bid, ask)
            continue
        mid = (bid + ask) / 2
        if (ask - bid) / mid > max_spread_pct:
            _reject("wide_spread", osi, k, bid, ask)
            continue
        oi = optional_int(c.get("openInterest"))
        vol = optional_int(c.get("volume"))
        if oi is None and vol is None:
            _reject("liquidity_unknown", osi, k, bid, ask)
            continue
        if (oi or 0) < min_liquidity and (vol or 0) < min_liquidity:
            _reject("insufficient_liquidity", osi, k, bid, ask, oi, vol)
            continue
        out[osi] = {"sym": osi, "strike": k, "bid": bid, "ask": ask,
                    "mid": mid, "spread": ask - bid,
                    "spread_pct": (ask - bid) / mid, "expiration": exp,
                    "open_interest": oi, "volume": vol}
    return out, diag, rejected


def greeks(symbols, account_id, signed=True, batch_size=50,
           include_risk_metrics=False):
    """Return ({symbol: (delta, iv)}, errors).

    Per-contract failures are logged, not raised. Delta validated on
    [-1, 1] when signed=True (put deltas may be negative) or [0, 1] when
    signed=False. Symbols are deduplicated and fetched in batches.
    """
    out, errors = {}, []
    symbols = list(dict.fromkeys(symbols))
    lo, hi = (-1.0, 1.0) if signed else (0.0, 1.0)
    for i in range(0, len(symbols), batch_size):
        batch = symbols[i:i + batch_size]
        try:
            g = mcp_client.mcp_call("get_option_greeks",
                         {"osi_symbols": batch, "account_id": account_id})
        except mcp_client.McpError as exc:
            errors.append(f"greeks batch failed ({len(batch)} contracts): {exc}")
            continue
        if not isinstance(g, dict):
            errors.append("greeks batch returned non-object payload")
            continue
        for x in g.get("greeks", []):
            try:
                delta = float(x["greeks"]["delta"])
                iv = float(x["greeks"]["impliedVolatility"])
                if not (math.isfinite(delta) and math.isfinite(iv)
                        and lo <= delta <= hi and iv > 0):
                    raise ValueError(f"delta={delta} iv={iv} out of range")
                result = (delta, iv)
                if include_risk_metrics:
                    metrics = []
                    for key in ("theta", "vega"):
                        try:
                            value = float(x["greeks"][key])
                            metrics.append(value if math.isfinite(value) else None)
                        except (KeyError, TypeError, ValueError):
                            metrics.append(None)
                    result += tuple(metrics)
                out[x["symbol"]] = result
            except (KeyError, TypeError, ValueError) as exc:
                errors.append(f"invalid greeks for {x.get('symbol', '?')}: {exc}")
    return out, errors
