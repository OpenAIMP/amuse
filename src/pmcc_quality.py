#!/usr/bin/env python3
"""
PMCC pair-quality screener (v3).

Two stages:
  1. GATE: reject unsuitable underlyings, illiquid contracts, incompatible pairs,
     event conflicts. Every rejection carries a stable reason category and is
     reported -- nothing is silently dropped.
  2. RANK: surviving pairs by premium-to-debit (30d-normalized); execution
     friction as tiebreak.

Deliberate label choices (not sloppiness):
  - "premium_to_debit_30d" is a premium-to-capital screening ratio, NOT a return.
  - "intrinsic_only_reference" (long strike + net debit) is the long call's
    intrinsic breakeven at ITS expiry, not the position breakeven at short
    expiry (the long call retains time value then).
  - "initial_debit_at_risk" is the entry debit. Assignment handling, rolls, and
    execution change realized outcomes. An assigned short call can create a
    short-stock position; exercising the long leg sacrifices remaining extrinsic
    value -- neither is automated here.
  - Contracts are assumed to be standard 100-share deliverables. Non-standard
    deliverables are NOT validated; the multiplier assumption is printed, not
    hidden.
"""
import argparse
import json
import os
import math
import re
import sys
from datetime import date, datetime
from zoneinfo import ZoneInfo


ACCT = os.environ.get("PUBLIC_ACCOUNT_ID") or ""
if not ACCT:
    raise SystemExit("PUBLIC_ACCOUNT_ID is not set; configure it as a repo variable/secret (#23)")
NAMES = ["KO", "DIS", "MRK", "XOM", "INTC", "QCOM",
         "T", "VZ", "BAC", "PFE",
         "SBUX", "BMY", "DUK", "SO", "MET", "KMB", "GIS"]

# ---- screening configuration (design choices, printed in every report) ----
# Tunables live in gates.yaml; this block binds them to module constants.
import gates as _gates_mod
import mcp_client
from mcp_client import McpError
from market_data import quotes
from options_chain import dte, eligible_expirations
from options_chain import parse_chain
from options_chain import greeks as chain_greeks


def _apply_gates(path=None):
    global LONG_DTE_MIN, LONG_DTE_MAX, SHORT_DTE_MIN, SHORT_DTE_MAX
    global LONG_DELTA_MIN, LONG_DELTA_MAX, SHORT_DELTA_MIN, SHORT_DELTA_MAX
    global MAX_SPREAD_PCT, MIN_LONG_LIQUIDITY, MIN_SHORT_LIQUIDITY
    global MAX_CAPITAL, MAX_FRICTION
    G = _gates_mod.load(path)["pmcc"]
    LONG_DTE_MIN, LONG_DTE_MAX = G["long_dte_min"], G["long_dte_max"]
    SHORT_DTE_MIN, SHORT_DTE_MAX = G["short_dte_min"], G["short_dte_max"]
    LONG_DELTA_MIN, LONG_DELTA_MAX = G["long_delta_min"], G["long_delta_max"]
    SHORT_DELTA_MIN, SHORT_DELTA_MAX = G["short_delta_min"], G["short_delta_max"]
    MAX_SPREAD_PCT = G["max_spread_pct"]
    MIN_LONG_LIQUIDITY = G["min_long_liquidity"]
    MIN_SHORT_LIQUIDITY = G["min_short_liquidity"]
    MAX_CAPITAL = G["max_capital"]
    MAX_FRICTION = G["max_friction"]


_apply_gates()
GREEKS_BATCH = 40            # implementation setting, not a verified service limit
REJECT_EARNINGS = True       # earnings inside the short window rejects the pair
REQUIRE_EARNINGS_DATE = False  # True = unknown earnings date also rejects
EVENTS_FILE = None           # optional JSON: {"SYM": {"earnings": "YYYY-MM-DD", "exdiv": "YYYY-MM-DD"}}

RUN_DATE = datetime.now(ZoneInfo("America/New_York")).date()
RUN_TS = datetime.now(ZoneInfo("America/New_York")).isoformat(timespec="seconds")


def representative_expirations(exps):
    """Shortest, middle, longest eligible -- not every chain, not just the tail."""
    if len(exps) <= 3:
        return exps
    return [exps[0], exps[len(exps) // 2], exps[-1]]


# ---- MCP plumbing: every transport/parse failure becomes McpError ----
def pair_events(sym, short_exp, events):
    """Per-pair event evaluation. Returns (flags, rejection_reasons)."""
    expiry = date.fromisoformat(short_exp)
    ev = events.get(sym, {}) if events else {}
    flags, reasons = [], []

    earnings = ev.get("earnings")
    if not earnings:
        flags.append("earnings date unknown")
        if REQUIRE_EARNINGS_DATE:
            reasons.append("earnings date unknown")
    else:
        try:
            ed = date.fromisoformat(earnings)
            if RUN_DATE <= ed <= expiry:
                flags.append(f"earnings {earnings} in window")
                if REJECT_EARNINGS:
                    reasons.append("earnings in short window")
        except ValueError:
            flags.append("earnings date unparseable")

    exdiv = ev.get("exdiv")
    if exdiv:
        try:
            xd = date.fromisoformat(exdiv)
            if RUN_DATE <= xd <= expiry:
                flags.append(f"ex-div {exdiv} in window")
        except ValueError:
            flags.append("ex-div date unparseable")

    return flags, reasons


def evaluate_pair(spot, long_c, short_c):
    """Stable reason categories; numeric details go in diagnostics, not reasons."""
    lk, sk = long_c["strike"], short_c["strike"]
    reasons, diag = [], {}
    if not (lk < spot < sk):
        reasons.append("long not ITM / short not OTM")
    if not (dte(long_c["expiration"]) > dte(short_c["expiration"]) > 0):
        reasons.append("bad expiration relationship")
    ld, sd = long_c["delta"], short_c["delta"]
    if not (LONG_DELTA_MIN <= ld <= LONG_DELTA_MAX):
        reasons.append("long delta outside range")
        diag["long_delta"] = round(ld, 3)
    if not (SHORT_DELTA_MIN <= sd <= SHORT_DELTA_MAX):
        reasons.append("short delta outside range")
        diag["short_delta"] = round(sd, 3)
    debit = long_c["ask"] - short_c["bid"]  # conservative entry estimate
    if debit <= 0:
        reasons.append("nonpositive conservative debit")
    if debit * 100 > MAX_CAPITAL:
        reasons.append("capital over limit")
        diag["capital"] = round(debit * 100, 0)
    friction = (long_c["spread"] + short_c["spread"]) / short_c["bid"]
    if friction > MAX_FRICTION:
        reasons.append("execution friction over limit")
        diag["friction"] = round(friction, 2)
    if reasons:
        return {"accepted": False, "reasons": reasons, "diagnostics": diag}
    width = sk - lk
    short_dte = dte(short_c["expiration"])
    cushion = width - debit
    warnings = []
    if cushion < 0:
        warnings.append("entry debit exceeds strike width")
    return {
        "accepted": True,
        "long_sym": long_c["sym"], "short_sym": short_c["sym"],
        "long_strike": lk, "short_strike": sk,
        "long_exp": long_c["expiration"], "short_exp": short_c["expiration"],
        "long_dte": dte(long_c["expiration"]), "short_dte": short_dte,
        "debit_per_share": debit, "capital": debit * 100,
        "strike_width": width,
        "strike_width_minus_debit": cushion,  # diagnostic, not a gate
        "warnings": warnings,
        "intrinsic_only_reference": lk + debit,
        "long_extrinsic": long_c["ask"] - max(spot - lk, 0),
        "net_delta": ld - sd,
        "premium_to_debit_30d": 100 * short_c["bid"] / debit * 30 / short_dte,
        "friction": friction,
        "long_delta": ld, "short_delta": sd, "long_iv": long_c["iv"],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json-out", default=None)
    ap.add_argument("--names", default=None)
    ap.add_argument("--config", default=None,
                    help="path to gates.yaml (default: gates.yaml next to the script)")
    args = ap.parse_args()
    if args.config:
        _apply_gates(args.config)
    names = args.names.split(",") if args.names else NAMES

    events = {}
    if EVENTS_FILE:
        try:
            with open(EVENTS_FILE) as f:
                events = json.load(f)
        except OSError:
            print("warning: events file unreadable; event data unknown",
                  file=sys.stderr)

    print(f"PMCC pair-quality screen -- run {RUN_TS} (America/New_York)")
    print("Settings: "
          f"long DTE {LONG_DTE_MIN}-{LONG_DTE_MAX}, short DTE {SHORT_DTE_MIN}-{SHORT_DTE_MAX}, "
          f"long Δ {LONG_DELTA_MIN}-{LONG_DELTA_MAX}, short Δ {SHORT_DELTA_MIN}-{SHORT_DELTA_MAX}, "
          f"max spread {MAX_SPREAD_PCT:.0%} of mid, liquidity long>={MIN_LONG_LIQUIDITY}/short>={MIN_SHORT_LIQUIDITY}, "
          f"max capital ${MAX_CAPITAL}, max friction {MAX_FRICTION}x, "
          f"earnings-in-window={'REJECT' if REJECT_EARNINGS else 'flag'}, "
          f"unknown-earnings={'REJECT' if REQUIRE_EARNINGS_DATE else 'flag'}. "
          f"Assumes standard 100-share deliverables (not validated).")

    spot_map = quotes(names, ACCT)

    all_pairs, stock_notes = [], {}
    for sym in names:
        spot = spot_map.get(sym)
        if spot is None or not math.isfinite(spot) or spot <= 0:
            stock_notes[sym] = ["missing or invalid underlying quote"]
            continue
        try:
            raw = mcp_client.mcp_call("get_option_expirations",
                           {"symbol": sym, "account_id": ACCT})
            exps = eligible_expirations(
                sorted(set(re.findall(r"20\d\d-\d\d-\d\d", json.dumps(raw)))),
                0, LONG_DTE_MAX)
            long_exps = representative_expirations(
                [e for e in exps if LONG_DTE_MIN <= dte(e) <= LONG_DTE_MAX])
            short_exps = [e for e in exps
                          if SHORT_DTE_MIN <= dte(e) <= SHORT_DTE_MAX]
            if not long_exps or not short_exps:
                stock_notes[sym] = ["no expirations in DTE windows"]
                continue

            long_cands, diag_l = [], {}
            for exp in long_exps:
                contracts, d, _ = parse_chain(sym, exp, ACCT, MIN_LONG_LIQUIDITY,
                                   MAX_SPREAD_PCT, "calls")
                for k, v in d.items():
                    diag_l[k] = diag_l.get(k, 0) + v
                syms = [c["sym"] for c in contracts.values()
                        if spot * 0.4 <= c["strike"] <= spot * 0.85]
                g, gerr = chain_greeks(syms, ACCT, signed=False,
                                batch_size=GREEKS_BATCH)
                for c in contracts.values():
                    if c["sym"] not in g:
                        continue
                    c = dict(c)
                    c["delta"], c["iv"] = g[c["sym"]]
                    if LONG_DELTA_MIN <= c["delta"] <= LONG_DELTA_MAX:
                        long_cands.append(c)

            short_cands, diag_s = [], {}
            for exp in short_exps:
                contracts, d, _ = parse_chain(sym, exp, ACCT, MIN_SHORT_LIQUIDITY,
                                   MAX_SPREAD_PCT, "calls")
                for k, v in d.items():
                    diag_s[k] = diag_s.get(k, 0) + v
                syms = [c["sym"] for c in contracts.values()
                        if spot * 0.98 <= c["strike"] <= spot * 1.25]
                g, gerr = chain_greeks(syms, ACCT, signed=False,
                                batch_size=GREEKS_BATCH)
                for c in contracts.values():
                    if c["sym"] not in g:
                        continue
                    c = dict(c)
                    c["delta"], c["iv"] = g[c["sym"]]
                    if SHORT_DELTA_MIN <= c["delta"] <= SHORT_DELTA_MAX:
                        short_cands.append(c)

            notes = []
            if not long_cands or not short_cands:
                notes.append(f"no contracts in delta ranges "
                             f"(long {len(long_cands)}, short {len(short_cands)})")
            for src, name in ((diag_l, "long"), (diag_s, "short")):
                for k, v in sorted(src.items()):
                    if v:
                        notes.append(f"{name} contracts rejected: {k} x{v}")
            if gerr:
                notes.append(f"greeks issues: {len(gerr)} "
                             f"({gerr[0][:100]})")

            pairs, n_rej, rej_reasons = [], 0, {}
            for lc in long_cands:
                for sc in short_cands:
                    if lc["expiration"] == sc["expiration"]:
                        continue
                    flags, event_reasons = pair_events(sym, sc["expiration"],
                                                      events)
                    r = evaluate_pair(spot, lc, sc)
                    reasons = r.get("reasons", []) + event_reasons
                    if reasons:
                        n_rej += 1
                        for reason in reasons:
                            rej_reasons[reason] = rej_reasons.get(reason, 0) + 1
                        continue
                    r.update({"stock": sym, "spot": spot, "events": flags})
                    pairs.append(r)
            pairs.sort(key=lambda r: (-r["premium_to_debit_30d"], r["friction"]))
            all_pairs.extend(pairs[:3])
            notes.append(f"{len(pairs)} pairs accepted, {n_rej} rejected")
            for reason, cnt in sorted(rej_reasons.items(),
                                      key=lambda kv: (-kv[1], kv[0])):
                notes.append(f"pair rejections: {reason} x{cnt}")
            stock_notes[sym] = notes
        except McpError as e:
            stock_notes[sym] = [f"MCP error: {e}"]

    all_pairs.sort(key=lambda r: (-r["premium_to_debit_30d"], r["friction"]))
    print(f"\n{'sym':<5}{'long':<26}{'short':<24}{'debit$':>9}{'cap$':>8}"
          f"{'p/d30%':>8}{'fric':>6}{'w-d':>7}{'breach*':>9}")
    for r in all_pairs[:24]:
        warn = " !" + ";".join(r["warnings"]) if r["warnings"] else ""
        ev = " !! " + "; ".join(r["events"]) if r["events"] else ""
        print(f"{r['stock']:<5}"
              f"{r['long_exp'][2:]} {r['long_strike']:.0f}C Δ{r['long_delta']:.2f}   "
              f"{r['short_exp'][5:]} {r['short_strike']:.0f}C Δ{r['short_delta']:.2f}  "
              f"{r['debit_per_share']:>9.2f}{r['capital']:>8.0f}"
              f"{r['premium_to_debit_30d']:>8.1f}{r['friction']:>6.1f}"
              f"{r['strike_width_minus_debit']:>7.1f}"
              f"{r['intrinsic_only_reference']:>9.2f}{warn}{ev}")
    print("\n* breach = intrinsic-only reference (long strike + debit); true breakeven "
          "depends on the long call's remaining time value at short expiry.")
    print("* premium_to_debit_30d is a screening ratio, not an expected return. "
          "Debits use conservative ask/bid fills.")
    print("\nRejection notes:")
    for sym in names:
        for n in stock_notes.get(sym, ["no data"]):
            print(f"  {sym}: {n}")

    if args.json_out:
        best = {}
        for r in all_pairs:
            if r["stock"] not in best:
                best[r["stock"]] = {
                    "premium_to_debit_30d": round(r["premium_to_debit_30d"], 2),
                    "capital": round(r["capital"], 0),
                    "breach_vs_spot": round(r["intrinsic_only_reference"] / r["spot"] - 1, 4),
                    "long_sym": r["long_sym"], "short_sym": r["short_sym"],
                    "long_strike": r["long_strike"], "short_strike": r["short_strike"],
                    "events": r["events"],
                }
        with open(args.json_out, "w") as f:
            json.dump({"asof": RUN_DATE.isoformat(), "pairs": best}, f, indent=1)
        print(f"\nwrote {args.json_out}", file=sys.stderr)


if __name__ == "__main__":
    main()
