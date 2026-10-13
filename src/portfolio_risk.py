"""Aggregate open-ledger Greeks and model-based multi-scenario P&L."""
import argparse
import json
import math
from datetime import date

from options_math import black_scholes

SCENARIOS = {
    "base": (0.0, 1.0), "down_10_vol_down_50": (-0.10, 0.50),
    "down_10_vol_up_50": (-0.10, 1.50), "up_10_vol_down_50": (0.10, 0.50),
    "up_10_vol_up_50": (0.10, 1.50),
}


def analyze_portfolio(ledger, market, asof=None):
    """Analyze ledger positions using market={rate, underlyings:{SYM:{spot,iv}}}.

    Ledger legs need side/type/strike/expiry; optional quantity and iv override
    the underlying context. Missing market data are reported, never zero-filled.
    """
    asof = date.fromisoformat(asof or market.get("asof") or date.today().isoformat())
    rate = float(market.get("risk_free_rate", 0.0))
    underlyings = market.get("underlyings", {})
    totals = {k: 0.0 for k in ("delta", "gamma", "theta", "vega", "rho")}
    base_value = 0.0
    gaps, scenario_values = [], {k: 0.0 for k in SCENARIOS}
    legs_priced = 0
    for pos in ledger.get("positions", []):
        if pos.get("status") != "open":
            continue
        sym = pos.get("underlying", "?")
        ctx = underlyings.get(sym)
        if not ctx or not ctx.get("spot") or not ctx.get("iv"):
            gaps.append(f"{sym}: missing spot or IV")
            continue
        for leg in pos.get("legs", []):
            try:
                expiry = date.fromisoformat(leg["expiry"])
                t = max(0, (expiry - asof).days) / 365.0
                spot, iv = float(ctx["spot"]), float(leg.get("iv", ctx["iv"]))
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
    return {"asof": asof.isoformat(), "legs_priced": legs_priced,
            "complete": not gaps, "data_gaps": gaps,
            "greeks": {k: round(v, 6) for k, v in totals.items()},
            "greek_units": {"delta": "share-equivalent", "gamma": "delta per $1",
                            "theta": "$ per calendar day", "vega": "$ per 1.00 IV (divide by 100 for 1 vol point)",
                            "rho": "$ per 1.00 rate (divide by 100 for 1 rate point)"},
            "model_base_value": round(base_value, 2),
            "scenarios": scenarios,
            "method_note": "European Black-Scholes marks; scenario P&L is theoretical and excludes fees, skew, early exercise, and execution costs."}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--ledger", required=True)
    ap.add_argument("--market", required=True, help="JSON market context with rate/asof/underlyings")
    ap.add_argument("--out")
    args = ap.parse_args()
    with open(args.ledger) as f:
        ledger = json.load(f)
    with open(args.market) as f:
        market = json.load(f)
    result = analyze_portfolio(ledger, market)
    rendered = json.dumps(result, indent=2)
    if args.out:
        with open(args.out, "w") as f:
            f.write(rendered + "\n")
    print(rendered)


if __name__ == "__main__":
    main()
