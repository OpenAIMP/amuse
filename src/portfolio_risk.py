"""Aggregate open-ledger Greeks and model-based multi-scenario P&L."""
import argparse
import json
import math
from datetime import date, datetime, timezone

from options_math import black_scholes

SCENARIOS = {
    "base": (0.0, 1.0), "down_10_vol_down_50": (-0.10, 0.50),
    "down_10_vol_up_50": (-0.10, 1.50), "up_10_vol_down_50": (0.10, 0.50),
    "up_10_vol_up_50": (0.10, 1.50),
}


def _utc(value):
    """Parse an offset-aware ISO timestamp and normalize to UTC."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError("timestamp is required")
    parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp must include a UTC offset")
    return parsed.astimezone(timezone.utc)


def _number(value, field, positive=False, nonnegative=False):
    if isinstance(value, bool):
        raise ValueError(f"{field} must be numeric")
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{field} must be numeric")
    if not math.isfinite(number):
        raise ValueError(f"{field} must be finite")
    if positive and number <= 0:
        raise ValueError(f"{field} must be positive")
    if nonnegative and number < 0:
        raise ValueError(f"{field} must be nonnegative")
    return number


def _freshness(name, timestamp, now, max_age_seconds, checks):
    try:
        observed = _utc(timestamp)
    except (TypeError, ValueError) as e:
        checks[name] = {"status": "MISSING_OR_INVALID", "detail": str(e)}
        return None
    age = (now - observed).total_seconds()
    if age < -60:
        checks[name] = {"status": "FUTURE_TIMESTAMP", "age_seconds": round(age, 1)}
        return None
    if age > max_age_seconds:
        checks[name] = {"status": "STALE", "age_seconds": round(age, 1)}
        return None
    checks[name] = {"status": "FRESH", "age_seconds": round(max(0.0, age), 1)}
    return observed


def _validated_market(market, now, max_age_minutes):
    """Validate v1 snapshot metadata and produce fresh numeric contexts only."""
    checks, gaps, clean = {}, [], {}
    max_age_seconds = max_age_minutes * 60
    source = market.get("source") if isinstance(market, dict) else None
    source_valid = isinstance(source, str) and bool(source.strip())
    if not source_valid:
        gaps.append("market snapshot source is missing")
    captured = _freshness("snapshot_asof", market.get("asof") if isinstance(market, dict) else None,
                          now, max_age_seconds, checks)
    try:
        if isinstance(market.get("schema_version"), bool) or market.get("schema_version") != 1:
            raise ValueError("schema_version must be 1")
        rate = _number(market.get("risk_free_rate"), "risk_free_rate")
        if abs(rate) > 1:
            raise ValueError("risk_free_rate must be between -1 and 1")
    except (AttributeError, ValueError) as e:
        rate = None
        gaps.append(str(e))
    rate_time = _freshness("risk_free_rate_asof", market.get("risk_free_rate_asof") if isinstance(market, dict) else None,
                           now, max_age_seconds, checks)
    if captured is None:
        gaps.append("snapshot asof is missing, invalid, future-dated, or stale")
    if rate_time is None:
        gaps.append("risk_free_rate_asof is missing, invalid, future-dated, or stale")
    if rate is None:
        gaps.append("risk-free rate is unavailable")
    global_ok = bool(source_valid and captured and rate_time and rate is not None)
    contexts = market.get("underlyings", {}) if isinstance(market, dict) else {}
    if not isinstance(contexts, dict):
        contexts = {}
        gaps.append("underlyings must be a symbol-to-market-context object")
    for sym, ctx in contexts.items():
        if not isinstance(ctx, dict):
            gaps.append(f"{sym}: market context must be an object")
            continue
        spot_ok = _freshness(f"{sym}.spot", ctx.get("spot_asof"), now, max_age_seconds, checks)
        iv_ok = _freshness(f"{sym}.iv", ctx.get("iv_asof"), now, max_age_seconds, checks)
        if spot_ok is None or iv_ok is None:
            gaps.append(f"{sym}: spot/IV timestamp missing, invalid, future-dated, or stale")
            continue
        try:
            spot = _number(ctx.get("spot"), f"{sym}.spot", positive=True)
            iv = _number(ctx.get("iv"), f"{sym}.iv", positive=True)
            if iv > 5:
                raise ValueError(f"{sym}.iv must be <= 5.0 (500%)")
            dividend = _number(ctx.get("dividend_yield", 0.0), f"{sym}.dividend_yield")
            if abs(dividend) > 1:
                raise ValueError(f"{sym}.dividend_yield must be between -1 and 1")
            clean[sym] = {"spot": spot, "iv": iv, "dividend_yield": dividend}
        except ValueError as e:
            gaps.append(str(e))
    if not global_ok:
        clean = {}
    return {"asof": captured, "risk_free_rate": rate if global_ok else None,
            "underlyings": clean, "source": source,
            "checks": checks, "gaps": gaps}


def analyze_portfolio(ledger, market, asof=None, max_age_minutes=30, now=None):
    """Analyze open positions against a timestamped v1 market snapshot.

    Snapshot schema: schema_version=1, source, UTC `asof`, `risk_free_rate`,
    UTC `risk_free_rate_asof`, and underlyings keyed by symbol with numeric
    spot/iv plus UTC `spot_asof` and `iv_asof`. Optional dividend_yield is
    annual decimal. Each market observation must be no older than the configured
    freshness window. Positions requiring stale or missing inputs are excluded
    and counted as gaps; partial totals are explicitly marked incomplete.
    """
    if not math.isfinite(max_age_minutes) or max_age_minutes <= 0:
        raise ValueError("max_age_minutes must be positive")
    now = _utc(now) if isinstance(now, str) else (now or datetime.now(timezone.utc))
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    now = now.astimezone(timezone.utc)
    checked = _validated_market(market, now, max_age_minutes)
    valuation_time = _utc(asof) if asof else checked["asof"]
    valuation_date = valuation_time.date() if valuation_time else now.date()
    rate = checked["risk_free_rate"] if checked["risk_free_rate"] is not None else 0.0
    underlyings = checked["underlyings"]
    totals = {k: 0.0 for k in ("delta", "gamma", "theta", "vega", "rho")}
    base_value = 0.0
    gaps, scenario_values = list(checked["gaps"]), {k: 0.0 for k in SCENARIOS}
    open_legs = sum(len(p.get("legs", [])) for p in ledger.get("positions", [])
                    if p.get("status") == "open")
    legs_priced = 0
    for pos in ledger.get("positions", []):
        if pos.get("status") != "open":
            continue
        sym = pos.get("underlying", "?")
        ctx = underlyings.get(sym)
        if not ctx or not ctx.get("spot") or not ctx.get("iv"):
            if not any(g.startswith(f"{sym}:") for g in gaps):
                gaps.append(f"{sym}: fresh spot or IV is unavailable")
            continue
        for leg in pos.get("legs", []):
            try:
                expiry = date.fromisoformat(leg["expiry"])
                t = max(0, (expiry - valuation_date).days) / 365.0
                spot, iv = float(ctx["spot"]), float(ctx["iv"])
                strike, kind = float(leg["strike"]), leg["type"].lower()
                if kind not in ("call", "put"):
                    raise ValueError("type must be call or put")
                sign = 1 if leg.get("side", "short").lower() in ("long", "buy", "+1", "1") else -1
                qty = int(pos.get("contracts", 1)) * int(leg.get("quantity", 1)) * int(pos.get("multiplier", 100)) * sign
                div = float(ctx.get("dividend_yield", 0.0))
                greek = black_scholes(spot, strike, t, rate, iv, kind, div)
                base_value += greek["price"] * qty
                for key in totals:
                    totals[key] += greek[key] * qty
                legs_priced += 1
                for name, (spot_shift, vol_mult) in SCENARIOS.items():
                    shifted = black_scholes(spot * (1 + spot_shift), strike, t,
                                            rate, max(0.0001, iv * vol_mult), kind, div)
                    scenario_values[name] += shifted["price"] * qty
            except (KeyError, TypeError, ValueError, OverflowError) as e:
                gaps.append(f"{sym}: invalid/incomplete leg ({e})")
    scenarios = {name: {"portfolio_value": round(value, 2),
                        "pnl_vs_base": round(value - scenario_values["base"], 2)}
                 for name, value in scenario_values.items()}
    ledger_asof = ledger.get("updated_at")
    try:
        parsed_ledger_time = _utc(ledger_asof)
        if (parsed_ledger_time - now).total_seconds() > 60:
            raise ValueError("ledger timestamp is in the future")
        ledger_time = parsed_ledger_time.isoformat().replace("+00:00", "Z")
        ledger_timestamp_status = "PRESENT"
    except (TypeError, ValueError):
        ledger_time, ledger_timestamp_status = None, "MISSING_OR_INVALID"
        if open_legs:
            gaps.append("ledger updated_at is missing or invalid")
    coverage = (legs_priced / open_legs) if open_legs else 1.0
    no_legs_priced = open_legs > 0 and legs_priced == 0
    reported_greeks = (None if no_legs_priced else
                       {k: round(v, 6) for k, v in totals.items()})
    reported_scenarios = ({name: {"portfolio_value": None, "pnl_vs_base": None}
                           for name in SCENARIOS} if no_legs_priced else scenarios)
    return {"asof": valuation_time.isoformat().replace("+00:00", "Z"),
            "market_snapshot": {"schema_version": market.get("schema_version") if isinstance(market, dict) else None,
                                "source": checked["source"],
                                "max_age_minutes": max_age_minutes,
                                "checks": checked["checks"]},
            "ledger_updated_at": ledger_time,
            "ledger_timestamp_status": ledger_timestamp_status,
            "open_legs": open_legs, "legs_priced": legs_priced,
            "leg_coverage": round(coverage, 4),
            "complete": not gaps and legs_priced == open_legs,
            "data_gaps": gaps,
            "greeks": reported_greeks,
            "greek_units": {"delta": "share-equivalent", "gamma": "delta per $1",
                            "theta": "$ per calendar day", "vega": "$ per 1.00 IV (divide by 100 for 1 vol point)",
                            "rho": "$ per 1.00 rate (divide by 100 for 1 rate point)"},
            "model_base_value": None if no_legs_priced else round(base_value, 2),
            "scenarios": reported_scenarios,
            "method_note": "European Black-Scholes marks; scenario P&L is theoretical and excludes fees, skew, early exercise, and execution costs. Incomplete results contain only the portion of the book priced from fresh inputs; do not treat partial totals as current whole-book exposure."}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--ledger", required=True)
    ap.add_argument("--market", required=True, help="JSON market context with rate/asof/underlyings")
    ap.add_argument("--max-age-minutes", type=float, default=30.0,
                    help="maximum age for snapshot and market observations (default: 30)")
    ap.add_argument("--out")
    args = ap.parse_args()
    with open(args.ledger) as f:
        ledger = json.load(f)
    with open(args.market) as f:
        market = json.load(f)
    result = analyze_portfolio(ledger, market, max_age_minutes=args.max_age_minutes)
    rendered = json.dumps(result, indent=2)
    if args.out:
        with open(args.out, "w") as f:
            f.write(rendered + "\n")
    print(rendered)


if __name__ == "__main__":
    main()
