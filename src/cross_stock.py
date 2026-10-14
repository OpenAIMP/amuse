#!/usr/bin/env python3
"""
Cross-underlying strategy screening: pairs trades, sector rotation, and
index-vs-constituent (dispersion) structures. Pure functions, stdlib-only,
no API access -- callers supply prices, return series and leg quotes.
Single-underlying screeners (spread_screener.py etc.) are untouched.

Conventions:
  - A leg is a dict: underlying, kind ("stock"|"call"|"put"), side (+1 long,
    -1 short), qty (shares for stock, contracts for options), and for options
    strike, expiration (YYYY-MM-DD), delta, bid, ask, open_interest.
  - Option delta is normalised by kind (calls >= 0, puts <= 0) so signed and
    unsigned feeds behave identically. Stock delta is 1.
  - Dollar delta = side * qty * multiplier * delta * underlying price.
  - Hedge ratio = beta of leg-A returns on leg-B returns (cov/var), i.e. dollars
    of B per dollar of A for a minimum-variance hedge.
  - Every rejection carries a stable reason code; nothing is silently dropped.
"""
import math
from datetime import date

import gates as _gates_mod

STRUCTURES = ("pair", "sector_rotation", "dispersion")
KINDS = ("stock", "call", "put")


def cfg(path=None):
    return _gates_mod.load(path)["cross_stock"]


def _returns(prices):
    out = []
    for a, b in zip(prices, prices[1:]):
        if a is None or b is None or a <= 0 or b <= 0:
            return None
        out.append(b / a - 1.0)
    return out


def _mean(x):
    return sum(x) / len(x)


def _cov(x, y):
    mx, my = _mean(x), _mean(y)
    return sum((a - mx) * (b - my) for a, b in zip(x, y)) / (len(x) - 1)


def aligned_returns(prices_a, prices_b):
    """Trailing-aligned simple returns, or (None, None) on bad/missing data."""
    if not prices_a or not prices_b:
        return None, None
    ra, rb = _returns(list(prices_a)), _returns(list(prices_b))
    if ra is None or rb is None:
        return None, None
    n = min(len(ra), len(rb))
    if n < 2:
        return None, None
    return ra[-n:], rb[-n:]


def correlation(ra, rb):
    """Pearson correlation of two equal-length return series; None if undefined."""
    if not ra or not rb or len(ra) != len(rb) or len(ra) < 3:
        return None
    va, vb = _cov(ra, ra), _cov(rb, rb)
    if va <= 0 or vb <= 0:
        return None
    return _cov(ra, rb) / math.sqrt(va * vb)


def hedge_ratio(ra, rb):
    """Beta of A on B (dollars of B per dollar of A); None if B has no variance."""
    if not ra or not rb or len(ra) != len(rb) or len(ra) < 3:
        return None
    vb = _cov(rb, rb)
    if vb <= 0:
        return None
    return _cov(ra, rb) / vb


def size_hedge_shares(price_a, price_b, shares_a, ratio):
    """Shares of B (rounded) hedging `shares_a` of A at dollar hedge `ratio`."""
    if not price_a or not price_b or price_b <= 0 or ratio is None:
        return None
    return round(shares_a * price_a * ratio / price_b)


def size_delta_neutral_contracts(delta_a, qty_a, delta_b, mult=100):
    """Contracts of B making net share-delta zero vs qty_a contracts of A
    (same underlying price scale assumed by caller). None if delta_b is 0."""
    if not delta_b:
        return None
    return qty_a * delta_a / delta_b


def leg_delta(leg):
    if leg["kind"] == "stock":
        return 1.0
    d = abs(float(leg["delta"]))
    return d if leg["kind"] == "call" else -d


def leg_dollar_delta(leg, price, mult=100):
    m = 1 if leg["kind"] == "stock" else mult
    return leg["side"] * leg["qty"] * m * leg_delta(leg) * price


def vertical_spread_legs(underlying, kind, side, long_strike, short_strike,
                         expiration, qty=1, long_delta=None, short_delta=None,
                         long_quote=None, short_quote=None):
    """Two legs of a vertical (debit if side=+1 -> long `long_strike`).
    Quotes are dicts with bid/ask/open_interest. side=-1 reverses both legs
    (a short vertical)."""
    mk = lambda s, k, d, q: dict(underlying=underlying, kind=kind, side=s, qty=qty,
                                 strike=k, expiration=expiration, delta=d, **(q or {}))
    return [mk(side, long_strike, long_delta, long_quote),
            mk(-side, short_strike, short_delta, short_quote)]


def _validate(structure, underlyings, legs, today):
    reasons = []
    if structure not in STRUCTURES:
        return ["invalid_structure"]
    names = {l.get("underlying") for l in legs}
    if not legs or len(names) < 2:
        reasons.append("invalid_pair:needs_two_underlyings")
    if structure == "pair" and len(names) != 2:
        reasons.append("invalid_pair:pair_requires_exactly_two_underlyings")
    if structure == "dispersion" and "index" not in {
            (underlyings.get(n) or {}).get("role") for n in names}:
        reasons.append("invalid_pair:dispersion_requires_index_underlying")
    for l in legs:
        if l.get("kind") not in KINDS or l.get("side") not in (1, -1) \
                or not isinstance(l.get("qty"), (int, float)) or l["qty"] <= 0:
            reasons.append("invalid_leg")
            continue
        if l.get("underlying") not in underlyings:
            reasons.append(f"missing_data:underlying:{l.get('underlying')}")
        if l["kind"] != "stock":
            if l.get("strike") is None or not l.get("expiration"):
                reasons.append("missing_data:strike_or_expiration")
            else:
                try:
                    if date.fromisoformat(l["expiration"]) < today:
                        reasons.append("invalid_leg:expired")
                except ValueError:
                    reasons.append("invalid_leg:bad_expiration")
            if l.get("delta") is None:
                reasons.append("missing_data:delta")
    # a vertical on one underlying must have distinct strikes
    for n in names:
        opts = [l for l in legs if l.get("underlying") == n and l.get("kind") != "stock"
                and l.get("strike") is not None]
        for k in ("call", "put"):
            ks = [(l["strike"], l["expiration"]) for l in opts if l["kind"] == k]
            if len(ks) != len(set(ks)):
                reasons.append("invalid_leg:duplicate_strike")
    return list(dict.fromkeys(reasons))


def evaluate_structure(structure, underlyings, legs, gate_cfg=None, today=None):
    """Evaluate a cross-underlying structure.

    underlyings: {name: {"price", "prices" (daily closes, oldest first),
                  "beta" (vs market, optional), "role" ("index" for dispersion)}}
    Returns a record: accepted, reasons, legs, metrics (correlation, hedge
    ratio, net/gross $delta, relative return, variance, concentration)."""
    g = gate_cfg or cfg()
    today = today or date.today()
    mult = g["contract_multiplier"]
    rec = {"structure": structure, "accepted": False, "reasons": [], "legs": [],
           "metrics": {}}
    reasons = _validate(structure, underlyings, legs, today)
    names = list(dict.fromkeys(l.get("underlying") for l in legs))
    for n in names:
        u = underlyings.get(n) or {}
        if not u.get("price") or u["price"] <= 0:
            reasons.append(f"missing_data:price:{n}")
    if reasons:
        rec["reasons"] = list(dict.fromkeys(reasons))
        return rec

    # per-leg reporting + liquidity
    dd = {n: 0.0 for n in names}
    for l in legs:
        px = underlyings[l["underlying"]]["price"]
        d = leg_dollar_delta(l, px, mult)
        dd[l["underlying"]] += d
        row = {"underlying": l["underlying"], "kind": l["kind"],
               "side": "long" if l["side"] > 0 else "short", "qty": l["qty"],
               "strike": l.get("strike"), "expiration": l.get("expiration"),
               "delta": leg_delta(l), "dollar_delta": d}
        if l["kind"] != "stock":
            bid, ask, oi = l.get("bid"), l.get("ask"), l.get("open_interest")
            if bid is None or ask is None or oi is None or ask <= 0 or bid < 0 or ask < bid:
                rec["reasons"].append("missing_data:option_quote")
            else:
                mid = (bid + ask) / 2
                if mid <= 0 or (ask - bid) / mid > g["max_spread_pct"]:
                    rec["reasons"].append("liquidity:wide_spread")
                if oi < g["min_liquidity"]:
                    rec["reasons"].append("liquidity:open_interest")
        rec["legs"].append(row)

    gross = sum(abs(v) for v in dd.values())
    net = sum(dd.values())
    m = rec["metrics"]
    m.update(net_dollar_delta=net, gross_dollar_delta=gross,
             exposure_by_underlying=dd)
    if gross <= 0:
        rec["reasons"].append("missing_data:zero_exposure")
        rec["reasons"] = list(dict.fromkeys(rec["reasons"]))
        return rec
    m["net_delta_pct"] = abs(net) / gross
    if m["net_delta_pct"] > g["max_net_delta_pct"]:
        rec["reasons"].append("net_delta:not_neutral")

    # concentration
    m["concentration_pct"] = max(abs(v) for v in dd.values()) / gross
    if m["concentration_pct"] > g["max_concentration_pct"]:
        rec["reasons"].append("concentration:exceeds_max")

    # beta exposure
    betas = {n: underlyings[n].get("beta") for n in names}
    if any(b is None for b in betas.values()):
        rec["reasons"].append("missing_data:beta")
    else:
        m["beta_exposure"] = sum(dd[n] * betas[n] for n in names)
        m["beta_exposure_pct"] = abs(m["beta_exposure"]) / gross
        if m["beta_exposure_pct"] > g["max_beta_exposure_pct"]:
            rec["reasons"].append("beta:exposure_exceeds_max")

    # return-series metrics
    _return_metrics(structure, underlyings, names, dd, g, rec)

    rec["reasons"] = list(dict.fromkeys(rec["reasons"]))
    rec["accepted"] = not rec["reasons"]
    return rec


def _return_metrics(structure, underlyings, names, dd, g, rec):
    m = rec["metrics"]
    series = {}
    for n in names:
        p = underlyings[n].get("prices")
        r = _returns(list(p)) if p else None
        if r is None or len(r) < g["min_observations"]:
            rec["reasons"].append(f"missing_data:returns:{n}")
        else:
            series[n] = r
    if len(series) != len(names):
        return
    n_obs = min(len(r) for r in series.values())
    series = {n: r[-n_obs:] for n, r in series.items()}
    m["observations"] = n_obs

    # portfolio variance of the dollar-delta exposures (daily, $^2)
    var = 0.0
    for a in names:
        for b in names:
            var += dd[a] * dd[b] * _cov(series[a], series[b])
    m["portfolio_variance"] = var
    m["portfolio_volatility"] = math.sqrt(max(var, 0.0))

    # relative return over the window: long-side minus short-side, weighted by $ exposure
    cum = {n: math.prod(1 + x for x in series[n]) - 1 for n in names}
    gross = m["gross_dollar_delta"]
    m["relative_return"] = sum(dd[n] * cum[n] for n in names) / gross * 2 \
        if gross else None

    if structure == "dispersion":
        idx = [n for n in names if underlyings[n].get("role") == "index"][0]
        others = [n for n in names if n != idx]
        cs = [correlation(series[idx], series[n]) for n in others]
        if None in cs:
            rec["reasons"].append("missing_data:correlation")
            return
        corr = _mean(cs)
        m["correlation"] = corr
        m["hedge_ratio"] = {n: hedge_ratio(series[n], series[idx]) for n in others}
    else:
        a, b = names[0], names[1]
        corr = correlation(series[a], series[b])
        if corr is None:
            rec["reasons"].append("missing_data:correlation")
            return
        m["correlation"] = corr
        m["hedge_ratio"] = hedge_ratio(series[a], series[b])
        m["actual_hedge_ratio"] = abs(dd[b]) / abs(dd[a]) if dd[a] else None
    if abs(corr) < g["min_correlation"]:
        rec["reasons"].append("correlation:below_min")


def screen_structures(candidates, gate_cfg=None, today=None):
    """candidates: list of dicts {structure, underlyings, legs}. Returns
    (accepted sorted by |net delta| then variance, rejected) -- all reported."""
    accepted, rejected = [], []
    for c in candidates:
        r = evaluate_structure(c["structure"], c["underlyings"], c["legs"],
                               gate_cfg, today)
        (accepted if r["accepted"] else rejected).append(r)
    accepted.sort(key=lambda r: (r["metrics"]["net_delta_pct"],
                                 r["metrics"]["portfolio_variance"]))
    return accepted, rejected


def format_record(rec):
    lines = [f"{rec['structure']}: {'ACCEPT' if rec['accepted'] else 'REJECT'}"]
    for l in rec["legs"]:
        px = f" {l['strike']} {l['expiration']}" if l["kind"] != "stock" else ""
        lines.append(f"  {l['side']} {l['qty']} {l['underlying']} {l['kind']}{px} "
                     f"delta={l['delta']:+.2f} $delta={l['dollar_delta']:+,.0f}")
    for k, v in rec["metrics"].items():
        if isinstance(v, float):
            lines.append(f"  {k}: {v:.4f}")
        elif isinstance(v, (int, str)):
            lines.append(f"  {k}: {v}")
    if rec["reasons"]:
        lines.append("  reasons: " + ", ".join(rec["reasons"]))
    return "\n".join(lines)
