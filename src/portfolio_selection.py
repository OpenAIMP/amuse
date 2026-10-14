"""Portfolio-level trade selection with aggregate exposure limits.

Runs after individual candidate screening: takes already-qualified candidates
and greedily picks the highest-scoring, non-redundant set that keeps aggregate
Greeks, concentration, margin and correlation exposure inside configurable
limits. Candidates that fail report the first binding constraint.

Candidate fields: id, underlying, score, kind, expiration, margin (buying power
used, $), greeks {delta, gamma, theta, vega} in portfolio units (share-equivalent
delta, $ theta/day, ...), optional sector. Any limit set to None is disabled.
Baseline (e.g. from portfolio_risk.analyze_portfolio()["greeks"]) is optional.
"""
import json

GREEKS = ("delta", "gamma", "theta", "vega")

DEFAULT_LIMITS = {
    "max_abs_delta": None, "max_abs_gamma": None,
    "max_abs_theta": None, "max_abs_vega": None,
    "max_underlying_pct": None,      # fraction of buying power per underlying
    "max_sector_pct": None,          # fraction of buying power per sector
    "max_margin_pct": None,          # fraction of buying power in total
    "max_correlated_pct": None,      # fraction of buying power in a correlated cluster
    "correlation_threshold": 0.8,    # |corr| at/above which names are one cluster
    "max_positions": None,
}


def _corr(correlations, a, b):
    if a == b:
        return 1.0
    value = (correlations or {}).get((a, b))
    if value is None:
        value = (correlations or {}).get((b, a))
    if value is None:
        value = (correlations or {}).get(f"{a}|{b}", (correlations or {}).get(f"{b}|{a}", 0.0))
    return abs(float(value))


def _greeks(candidate):
    g = candidate.get("greeks") or {}
    return {k: float(g.get(k) or 0.0) for k in GREEKS}


def _exposure(selected, baseline, buying_power):
    totals = {k: float((baseline or {}).get(k) or 0.0) for k in GREEKS}
    margin, by_under, by_sector = 0.0, {}, {}
    for c in selected:
        for k, v in _greeks(c).items():
            totals[k] += v
        m = float(c["margin"])
        margin += m
        by_under[c["underlying"]] = by_under.get(c["underlying"], 0.0) + m
        sector = c.get("sector")
        if sector:
            by_sector[sector] = by_sector.get(sector, 0.0) + m
    return {"greeks": totals, "margin": margin, "margin_pct": margin / buying_power,
            "by_underlying": by_under, "by_sector": by_sector}


def _violation(name, value, limit):
    return {"constraint": name, "value": round(value, 6), "limit": limit}


def _check(candidate, selected, limits, baseline, buying_power, correlations):
    """Return the first violated constraint for adding candidate, else None."""
    if any(s["underlying"] == candidate["underlying"] and s.get("kind") == candidate.get("kind")
           and s.get("expiration") == candidate.get("expiration") for s in selected):
        return {"constraint": "redundant", "value": None, "limit": None}
    n = limits.get("max_positions")
    if n is not None and len(selected) + 1 > n:
        return _violation("max_positions", len(selected) + 1, n)
    after = _exposure(selected + [candidate], baseline, buying_power)
    for g in GREEKS:
        limit = limits.get(f"max_abs_{g}")
        if limit is not None and abs(after["greeks"][g]) > limit:
            return _violation(f"max_abs_{g}", abs(after["greeks"][g]), limit)
    checks = [("max_margin_pct", after["margin_pct"]),
              ("max_underlying_pct", after["by_underlying"][candidate["underlying"]] / buying_power)]
    if candidate.get("sector"):
        checks.append(("max_sector_pct", after["by_sector"][candidate["sector"]] / buying_power))
    thr = float(limits.get("correlation_threshold", 0.8))
    cluster = sum(float(s["margin"]) for s in selected
                  if _corr(correlations, s["underlying"], candidate["underlying"]) >= thr)
    checks.append(("max_correlated_pct", (cluster + float(candidate["margin"])) / buying_power))
    for name, value in checks:
        limit = limits.get(name)
        if limit is not None and value > limit:
            return _violation(name, value, limit)
    return None


def select_portfolio(candidates, buying_power, limits=None, baseline=None, correlations=None):
    """Greedy highest-score selection subject to aggregate limits."""
    if not buying_power or buying_power <= 0:
        raise ValueError("buying_power must be positive")
    merged = dict(DEFAULT_LIMITS)
    merged.update(limits or {})
    ordered = sorted(candidates, key=lambda c: (-float(c.get("score") or 0.0), str(c["id"])))
    selected, rejected, incremental = [], [], {}
    for c in ordered:
        if not (float(c.get("margin") or 0) > 0):
            rejected.append({"id": c["id"], "underlying": c["underlying"],
                             "binding_constraint": {"constraint": "invalid_margin",
                                                    "value": c.get("margin"), "limit": None}})
            continue
        v = _check(c, selected, merged, baseline, buying_power, correlations)
        if v:
            rejected.append({"id": c["id"], "underlying": c["underlying"], "binding_constraint": v})
            continue
        incremental[c["id"]] = {"greeks": _greeks(c), "margin": float(c["margin"]),
                                "margin_pct": round(float(c["margin"]) / buying_power, 6)}
        selected.append(c)
    exposure = _exposure(selected, baseline, buying_power)
    return {"limits": merged, "buying_power": buying_power,
            "proposed": [{"id": c["id"], "underlying": c["underlying"], "score": c.get("score"),
                          "incremental": incremental[c["id"]]} for c in selected],
            "rejected": rejected,
            "exposure": {"greeks": {k: round(v, 6) for k, v in exposure["greeks"].items()},
                         "margin": exposure["margin"],
                         "margin_pct": round(exposure["margin_pct"], 6),
                         "by_underlying": exposure["by_underlying"],
                         "by_sector": exposure["by_sector"]}}


def candidates_from_spreads(rows, sectors=None):
    """Adapt spread_screener accepted results; (kind, result) pairs -> candidates.

    Greeks beyond net_delta are used only when the result provides them.
    """
    out = []
    for kind, r in rows:
        sym = r["stock"]
        strikes = "-".join(str(r[k]) for k in ("put_short_strike", "short_strike", "call_short_strike")
                           if k in r)
        greeks = {k: r[k] for k in ("gamma", "theta", "vega") if r.get(k) is not None}
        greeks["delta"] = r.get("net_delta", 0.0) * 100
        out.append({"id": f"{sym}:{kind}:{r['expiration']}:{strikes}", "underlying": sym,
                    "kind": kind, "expiration": r["expiration"],
                    "score": r.get("return_on_risk", 0.0), "margin": r["max_loss_total"],
                    "sector": (sectors or {}).get(sym), "greeks": greeks})
    return out


def load_config(path):
    with open(path) as f:
        return json.load(f)
