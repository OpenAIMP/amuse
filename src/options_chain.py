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
GREEK_FIELDS = ("delta", "gamma", "theta", "vega", "rho")


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


def aggregate_greeks(legs, multiplier=1.0):
    """Aggregate signed per-option Greeks; an unavailable input stays None.

    Each leg is {"greeks": {field: value}, "quantity": signed quantity}.
    The multiplier converts per-share Greeks into share/contract exposures.
    """
    if isinstance(multiplier, bool):
        raise ValueError("multiplier must be finite and numeric")
    try:
        multiplier = float(multiplier)
    except (TypeError, ValueError):
        raise ValueError("multiplier must be finite and numeric")
    if not math.isfinite(multiplier):
        raise ValueError("multiplier must be finite and numeric")

    legs = list(legs)
    totals = {}
    for field in GREEK_FIELDS:
        total, valid = 0.0, True
        for leg in legs:
            if not isinstance(leg, dict):
                valid = False
                break
            values = leg.get("greeks")
            values = values if isinstance(values, dict) else {}
            value, quantity = values.get(field), leg.get("quantity", 1.0)
            if isinstance(value, bool) or isinstance(quantity, bool):
                valid = False
                break
            try:
                value, quantity = float(value), float(quantity)
            except (TypeError, ValueError):
                valid = False
                break
            if not (math.isfinite(value) and math.isfinite(quantity)):
                valid = False
                break
            total += value * quantity * multiplier
        totals[field] = total if valid else None
    return totals


def greeks(symbols, account_id, signed=True, batch_size=50,
           include_all=False):
    """Return ({symbol: (delta, iv)}, errors).

    Per-contract failures are logged, not raised. Delta validated on
    [-1, 1] when signed=True (put deltas may be negative) or [0, 1] when
    signed=False. Symbols are deduplicated and fetched in batches. With
    include_all=True, values are {delta, iv, gamma, theta, vega, rho}; missing
    or invalid optional Greeks are None and do not invalidate delta/IV.
    """
    out, errors = {}, []
    symbols = list(dict.fromkeys(symbols))
    if isinstance(batch_size, bool) or not isinstance(batch_size, int) or batch_size <= 0:
        raise ValueError("batch_size must be a positive integer")
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
                if not isinstance(x, dict):
                    raise ValueError("greek entry must be an object")
                symbol = x.get("symbol", "?")
                values = x.get("greeks")
                if not isinstance(values, dict):
                    raise ValueError("greeks must be an object")
                if isinstance(values.get("delta"), bool) or isinstance(
                        values.get("impliedVolatility"), bool):
                    raise ValueError("delta and IV must be numeric")
                delta = float(values["delta"])
                iv = float(values["impliedVolatility"])
                if not (math.isfinite(delta) and math.isfinite(iv)
                        and lo <= delta <= hi and iv > 0):
                    raise ValueError(f"delta={delta} iv={iv} out of range")
                optional = {}
                for field in GREEK_FIELDS[1:]:
                    raw = values.get(field)
                    if raw is None:
                        optional[field] = None
                    elif isinstance(raw, bool):
                        optional[field] = None
                        errors.append(f"invalid {field} for {symbol}: must be numeric")
                    else:
                        try:
                            value = float(raw)
                            if not math.isfinite(value):
                                raise ValueError(f"{field} must be finite")
                            optional[field] = value
                        except (TypeError, ValueError) as exc:
                            optional[field] = None
                            errors.append(f"invalid {field} for {symbol}: {exc}")
                out[symbol] = ({"delta": delta, "iv": iv, **optional}
                               if include_all else (delta, iv))
            except (KeyError, TypeError, ValueError) as exc:
                symbol = x.get("symbol", "?") if isinstance(x, dict) else "?"
                errors.append(f"invalid greeks for {symbol}: {exc}")
    return out, errors
