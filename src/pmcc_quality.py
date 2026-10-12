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
import subprocess
import sys
from datetime import date, datetime
from zoneinfo import ZoneInfo

CLI = os.environ.get("PUBLIC_MCP_CLI", "/home/hatch/workspace/skills/public-mcp/bin/public-mcp")
ACCT = os.environ.get("PUBLIC_ACCOUNT_ID", "5OI32712")
NAMES = ["KO", "DIS", "MRK", "XOM", "INTC", "QCOM",
         "T", "VZ", "BAC", "PFE",
         "SBUX", "BMY", "DUK", "SO", "MET", "KMB", "GIS"]

# ---- screening configuration (design choices, printed in every report) ----
# Tunables live in gates.yaml; this block binds them to module constants.
import gates as _gates_mod


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


def dte(exp):
    return (date.fromisoformat(exp) - RUN_DATE).days


def eligible_expirations(expirations, minimum, maximum):
    return sorted({e for e in expirations if minimum <= dte(e) <= maximum})


def representative_expirations(exps):
    """Shortest, middle, longest eligible -- not every chain, not just the tail."""
    if len(exps) <= 3:
        return exps
    return [exps[0], exps[len(exps) // 2], exps[-1]]


# ---- MCP plumbing: every transport/parse failure becomes McpError ----
class McpError(RuntimeError):
    pass


def mcp_call(tool, args):
    try:
        proc = subprocess.run([CLI, "call", tool, json.dumps(args)],
                              capture_output=True, text=True, timeout=120)
    except subprocess.TimeoutExpired as e:
        raise McpError(f"{tool}: CLI timed out: {e}")
    if proc.returncode != 0:
        raise McpError(f"{tool}: CLI failed: {proc.stderr[:300]}")
    try:
        d = json.loads(proc.stdout)
    except json.JSONDecodeError as e:
        raise McpError(f"{tool}: CLI returned non-JSON output: {e}")
    if not isinstance(d, dict) or "content" not in d or not d["content"]:
        raise McpError(f"{tool}: unexpected response shape")
    if d.get("isError"):
        raise McpError(f"{tool}: {json.dumps(d)[:300]}")
    try:
        return json.loads(d["content"][0]["text"])
    except (json.JSONDecodeError, KeyError, TypeError, IndexError) as e:
        raise McpError(f"{tool}: unparseable content payload: {e}")


OSI_RE = re.compile(r"^(.+?)(\d{6})([CP])(\d{8})$")


def parse_osi(osi):
    """Return (expiration_iso, is_call, strike) or raise ValueError."""
    m = OSI_RE.match(osi)
    if not m:
        raise ValueError(f"unparseable OSI: {osi}")
    yy, mm, dd = int(m.group(2)[:2]), int(m.group(2)[2:4]), int(m.group(2)[4:6])
    exp = date(2000 + yy, mm, dd).isoformat()
    return exp, m.group(3) == "C", int(m.group(4)) / 1000.0


def optional_int(value):
    if value is None:
        return None
    return int(value)


def parse_calls(sym, exp, min_liquidity):
    """Return ({osi: contract}, diagnostics). Contract keyed by full OSI symbol."""
    p = mcp_call("get_option_chain",
                 {"symbol": sym, "expiration_date": exp, "account_id": ACCT})
    if not isinstance(p, dict):
        raise McpError(f"get_option_chain: expected object payload for {sym} {exp}")
    out, diag = {}, {"bad_symbol": 0, "wrong_type_or_expiry": 0, "bad_quote": 0,
                     "wide_spread": 0, "liquidity_unknown": 0,
                     "insufficient_liquidity": 0}
    for c in p.get("calls", []):
        try:
            osi = c["instrument"]["symbol"]
            c_exp, is_call, k = parse_osi(osi)
        except (ValueError, KeyError, TypeError):
            diag["bad_symbol"] += 1
            continue
        if not is_call or c_exp != exp:
            diag["wrong_type_or_expiry"] += 1
            continue
        try:
            bid, ask = float(c["bid"] or 0), float(c["ask"] or 0)
        except (TypeError, ValueError):
            diag["bad_quote"] += 1
            continue
        if not (math.isfinite(bid) and math.isfinite(ask)) or bid <= 0 or ask < bid:
            diag["bad_quote"] += 1
            continue
        mid = (bid + ask) / 2
        if (ask - bid) / mid > MAX_SPREAD_PCT:
            diag["wide_spread"] += 1
            continue
        oi = optional_int(c.get("openInterest"))
        vol = optional_int(c.get("volume"))
        if oi is None and vol is None:
            diag["liquidity_unknown"] += 1
            continue
        if (oi or 0) < min_liquidity and (vol or 0) < min_liquidity:
            diag["insufficient_liquidity"] += 1
            continue
        out[osi] = {"sym": osi, "strike": k, "bid": bid, "ask": ask, "mid": mid,
                    "spread": ask - bid, "spread_pct": (ask - bid) / mid,
                    "expiration": exp}
    return out, diag


def greeks(syms):
    """Return (symbol -> (delta, iv), errors). Per-contract failures are logged."""
    out, errors = {}, []
    syms = list(dict.fromkeys(syms))
    for i in range(0, len(syms), GREEKS_BATCH):
        batch = syms[i:i + GREEKS_BATCH]
        try:
            g = mcp_call("get_option_greeks",
                         {"osi_symbols": batch, "account_id": ACCT})
        except (McpError, subprocess.TimeoutExpired) as exc:
            errors.append(f"greeks batch failed ({len(batch)} contracts): {exc}")
            continue
        if not isinstance(g, dict):
            errors.append(f"greeks batch returned non-object payload")
            continue
        for x in g.get("greeks", []):
            try:
                delta = float(x["greeks"]["delta"])
                iv = float(x["greeks"]["impliedVolatility"])
                if not (math.isfinite(delta) and math.isfinite(iv)
                        and 0 <= delta <= 1 and iv > 0):
                    raise ValueError(f"delta={delta} iv={iv} out of range")
                out[x["symbol"]] = (delta, iv)
            except (KeyError, TypeError, ValueError) as exc:
                errors.append(f"invalid greeks for {x.get('symbol', '?')}: {exc}")
    return out, errors


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

    spot_map = {}
    q = mcp_call("get_quotes", {"symbols": names, "account_id": ACCT})
    if not isinstance(q, (dict, list)):
        raise McpError("get_quotes: expected object or list payload")

    def qwalk(o):
        if isinstance(o, dict):
            s = o.get("instrument", {}).get("symbol")
            if s in names and "last" in o:
                try:
                    v = float(o["last"])
                    if math.isfinite(v) and v > 0:
                        spot_map[s] = v
                except (TypeError, ValueError):
                    pass
            for v in o.values():
                qwalk(v)
        elif isinstance(o, list):
            for v in o:
                qwalk(v)
    qwalk(q)

    all_pairs, stock_notes = [], {}
    for sym in names:
        spot = spot_map.get(sym)
        if spot is None or not math.isfinite(spot) or spot <= 0:
            stock_notes[sym] = ["missing or invalid underlying quote"]
            continue
        try:
            raw = mcp_call("get_option_expirations",
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
                contracts, d = parse_calls(sym, exp, MIN_LONG_LIQUIDITY)
                for k, v in d.items():
                    diag_l[k] = diag_l.get(k, 0) + v
                syms = [c["sym"] for c in contracts.values()
                        if spot * 0.4 <= c["strike"] <= spot * 0.85]
                g, gerr = greeks(syms)
                for c in contracts.values():
                    if c["sym"] not in g:
                        continue
                    c = dict(c)
                    c["delta"], c["iv"] = g[c["sym"]]
                    if LONG_DELTA_MIN <= c["delta"] <= LONG_DELTA_MAX:
                        long_cands.append(c)

            short_cands, diag_s = [], {}
            for exp in short_exps:
                contracts, d = parse_calls(sym, exp, MIN_SHORT_LIQUIDITY)
                for k, v in d.items():
                    diag_s[k] = diag_s.get(k, 0) + v
                syms = [c["sym"] for c in contracts.values()
                        if spot * 0.98 <= c["strike"] <= spot * 1.25]
                g, gerr = greeks(syms)
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
