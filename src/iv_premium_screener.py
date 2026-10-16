#!/usr/bin/env python3
"""
High-IV premium selling screener.

Finds put-selling opportunities where:
- Short strike >= 60% of current price (not too far OTM — captures real premium)
- Expirations in 1-2-3 month windows (30, 60, 90 DTE)
- Ranked by implied volatility (highest first) for richest premium

This answers: "where can I sell puts with good premium at reasonable strikes?"

Usage:
    python3 src/iv_premium_screener.py --universe lev_etf
    python3 src/iv_premium_screener.py --names TQQQ,SOXL --min-strike-pct 0.6
    python3 src/iv_premium_screener.py --universe nasdaq100 --json

Stdlib-only. Requires PUBLIC_ACCOUNT_ID.
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import mcp_client
from market_data import quote as get_quote
from options_chain import (
    eligible_expirations, parse_chain, parse_osi, dte,
)
from options_math import black_scholes


def implied_volatility(put_call, S, K, T, r, market_price, tol=1e-4,
                       max_iter=100):
    """
    Solve for implied volatility via bisection.

    Returns IV as a decimal (e.g. 0.25 = 25%), or None if no solution.
    """
    if T <= 0 or market_price <= 0 or S <= 0 or K <= 0:
        return None

    def price_at(vol):
        try:
            result = black_scholes(
                S, K, T, r, vol, option_type=put_call)
            return result["price"]
        except (ValueError, ZeroDivisionError):
            return 0.0

    # Intrinsic value bounds the search
    lo, hi = 0.001, 5.0
    p_lo, p_hi = price_at(lo), price_at(hi)
    if market_price < p_lo or market_price > p_hi:
        return None

    for _ in range(max_iter):
        mid = (lo + hi) / 2
        p_mid = price_at(mid)
        if abs(p_mid - market_price) < tol:
            return mid
        if p_mid < market_price:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2

ACCT = os.environ.get("PUBLIC_ACCOUNT_ID")
if not ACCT:
    raise SystemExit(
        "PUBLIC_ACCOUNT_ID is not set; set the environment variable "
        "locally or configure the GitHub Actions repository secret (#23)"
    )

# DTE windows for 1, 2, 3 months
DTE_WINDOWS = {
    "1M": (21, 45),
    "2M": (46, 75),
    "3M": (76, 110),
}


def get_expirations(sym):
    """Get all available expirations for a symbol."""
    try:
        p = mcp_client.mcp_call(
            "get_option_expirations",
            {"symbol": sym, "account_id": ACCT})
    except mcp_client.McpError:
        return []
    if isinstance(p, dict):
        return p.get("expirations", []) or []
    return []


def screen_symbol(sym, min_strike_pct=0.60, min_liquidity=10,
                  max_spread_pct=0.25):
    """
    Screen one symbol for high-IV put selling opportunities.

    Returns list of dicts, one per (expiration, strike) candidate,
    sorted by IV descending.
    """
    # Get spot price
    try:
        q = get_quote(sym, ACCT)
        spot = float(q.get("last") or q.get("bid") or 0)
        if spot <= 0:
            return [], f"no valid quote for {sym}"
    except Exception as e:
        return [], f"quote error for {sym}: {e}"

    min_strike = spot * min_strike_pct
    expirations = get_expirations(sym)
    if not expirations:
        return [], f"no expirations for {sym}"

    candidates = []

    for window_name, (dte_min, dte_max) in DTE_WINDOWS.items():
        eligible = eligible_expirations(expirations, dte_min, dte_max)
        if not eligible:
            continue
        # Use the expiration closest to the middle of the window
        target_dte = (dte_min + dte_max) // 2
        exp = min(eligible, key=lambda e: abs(dte(e) - target_dte))
        actual_dte = dte(exp)

        try:
            chain, diag, rejected = parse_chain(
                sym, exp, ACCT, min_liquidity, max_spread_pct, want="puts")
        except mcp_client.McpError as e:
            continue

        for osi, contract in chain.items():
            try:
                _, _, strike = parse_osi(osi)
            except (ValueError, TypeError):
                continue

            # Strike must be >= 60% of spot (not too far OTM)
            if strike < min_strike:
                continue
            # Strike should be OTM or slightly ITM (not deep ITM)
            if strike > spot * 1.05:
                continue

            bid = contract.get("bid", 0) or 0
            ask = contract.get("ask", 0) or 0
            if bid <= 0:
                continue

            # Conservative fill: use bid
            premium = bid
            strike_pct = strike / spot

            # Calculate IV from the put price
            try:
                iv = implied_volatility(
                    put_call="put", S=spot, K=strike,
                    T=actual_dte / 365.0, r=0.045,
                    market_price=(bid + ask) / 2)
            except Exception:
                iv = None

            # Premium as % of strike (return if expires worthless)
            premium_pct = (premium / strike * 100) if strike > 0 else 0

            # Annualized return if expires worthless
            ann_ret = (premium_pct / actual_dte * 365) if actual_dte > 0 else 0

            candidates.append({
                "symbol": sym,
                "window": window_name,
                "expiration": exp,
                "dte": actual_dte,
                "strike": round(strike, 2),
                "strike_pct": round(strike_pct * 100, 1),
                "spot": round(spot, 2),
                "bid": round(bid, 2),
                "ask": round(ask, 2),
                "premium_pct": round(premium_pct, 2),
                "annualized_ret": round(ann_ret, 1),
                "iv": round(iv * 100, 1) if iv else None,
                "open_interest": contract.get("open_interest"),
                "volume": contract.get("volume"),
            })

    # Sort by IV descending (highest premium first)
    candidates.sort(
        key=lambda c: (c["iv"] or 0, c["premium_pct"]), reverse=True)
    return candidates, None


def main(argv):
    parser = argparse.ArgumentParser(
        description="High-IV premium selling screener"
    )
    parser.add_argument("--universe", default=None,
                        help="Universe name (e.g. lev_etf)")
    parser.add_argument("--names", default=None,
                        help="Comma-separated symbols (overrides --universe)")
    parser.add_argument("--min-strike-pct", type=float, default=0.60,
                        help="Min strike as fraction of spot (default: 0.60)")
    parser.add_argument("--top", type=int, default=20,
                        help="Top N candidates to show (default: 20)")
    parser.add_argument("--json", action="store_true",
                        help="Output JSON instead of table")
    args = parser.parse_args(argv)

    # Resolve symbols
    if args.names:
        symbols = [s.strip().upper() for s in args.names.split(",")]
    elif args.universe:
        upath = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "universes", f"{args.universe}.txt")
        with open(upath) as f:
            symbols = [l.strip().upper() for l in f
                       if l.strip() and not l.startswith("#")]
    else:
        parser.error("Provide --universe or --names")

    all_candidates = []
    errors = {}
    for sym in symbols:
        cands, err = screen_symbol(sym, min_strike_pct=args.min_strike_pct)
        if err:
            errors[sym] = err
        all_candidates.extend(cands)

    # Global sort by IV
    all_candidates.sort(
        key=lambda c: (c["iv"] or 0, c["premium_pct"]), reverse=True)
    top = all_candidates[:args.top]

    if args.json:
        print(json.dumps({
            "candidates": top,
            "total_found": len(all_candidates),
            "symbols_screened": len(symbols),
            "errors": errors,
            "min_strike_pct": args.min_strike_pct,
        }, indent=2, default=str))
    else:
        print(f"\nHigh-IV Put Selling — Top {len(top)} "
              f"(strike >= {args.min_strike_pct:.0%} of spot)")
        print("=" * 100)
        print(f"{'Sym':<6} {'Win':<4} {'Exp':<12} {'DTE':<4} "
              f"{'Strike':<8} {'%Spot':<6} {'Bid':<6} "
              f"{'IV%':<6} {'Prem%':<6} {'Ann%':<6}")
        print("-" * 100)
        for c in top:
            iv_str = f"{c['iv']:.1f}" if c['iv'] else "—"
            print(f"{c['symbol']:<6} {c['window']:<4} {c['expiration']:<12} "
                  f"{c['dte']:<4} {c['strike']:<8.2f} {c['strike_pct']:<6.1f} "
                  f"{c['bid']:<6.2f} {iv_str:<6} "
                  f"{c['premium_pct']:<6.2f} {c['annualized_ret']:<6.1f}")
        if errors:
            print(f"\n⚠️ Errors: {len(errors)} symbols skipped")
        print("\nNot investment advice. IV is a model estimate.")

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
