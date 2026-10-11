#!/usr/bin/env python3
"""
Options spread screener: bull put spreads + iron condors + asymmetric iron condors
(defined-risk variant).

Two stages (same discipline as pmcc_quality.py v3):
  1. GATE: reject bad quotes, illiquid contracts, incompatible legs, and event
     conflicts. Every rejection carries a stable reason category and is
     reported -- nothing is silently dropped.
  2. RANK: survivors by return on risk (credit / max loss); tighter markets
     break ties.

Deliberate label choices (not sloppiness):
  - "return on risk" (credit / max loss) is a screening ratio, NOT an expected
    or realized return.
  - All pricing is conservative: credit = short bid - long ask, per spread
    (per wing for condors). Midpoints are never used for decisions.
  - Contracts are assumed to be standard 100-share deliverables. Non-standard
    deliverables are NOT validated; the assumption is printed, not hidden.
  - Put deltas may arrive signed (negative) or unsigned depending on the data
    source; selection uses abs(delta) and is robust to either convention.
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
NAMES = ["T", "VZ", "BAC", "PFE", "KO", "MRK", "BMY", "SBUX", "DIS", "XOM"]

# ---- screening configuration (design choices, printed in every report) ----
SPREAD_DTE_MIN, SPREAD_DTE_MAX = 21, 60
SHORT_DELTA_MIN, SHORT_DELTA_MAX = 0.10, 0.20
SPREAD_WIDTH = 5              # strike width in dollars (configurable via --width)
MAX_SPREAD_PCT = 0.25         # reject contracts whose bid/ask spread > 25% of mid
MIN_LIQUIDITY = 10            # OI or volume floor per leg
MAX_SPREAD_LOSS = 1000        # max loss gate per spread ($)
MAX_FRICTION = 3.0            # combined leg spreads / net credit: reject above
CALL_DISTANCE_MIN = 0.08     # asym condor skew: call-wing short strike >= 8% above spot
GREEKS_BATCH = 40             # implementation setting, not a verified service limit
REJECT_EARNINGS = True        # earnings inside the spread window rejects it
REQUIRE_EARNINGS_DATE = False  # True = unknown earnings date also rejects
EVENTS_FILE = None            # optional JSON: {"SYM": {"earnings": "YYYY-MM-DD", "exdiv": "YYYY-MM-DD"}}

RUN_DATE = datetime.now(ZoneInfo("America/New_York")).date()
RUN_TS = datetime.now(ZoneInfo("America/New_York")).isoformat(timespec="seconds")


def dte(exp):
    return (date.fromisoformat(exp) - RUN_DATE).days


def eligible_expirations(expirations, minimum, maximum):
    return sorted({e for e in expirations if minimum <= dte(e) <= maximum})


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
    return exp, m.group(3) == "C", round(int(m.group(4)) / 1000.0, 3)


def optional_int(value):
    if value is None:
        return None
    return int(value)


def parse_options(sym, exp, min_liquidity, want):
    """Return ({osi: contract}, diagnostics). want in {"puts","calls"}.

    Contract keyed by full OSI symbol; type and expiration validated from the
    symbol itself. Bid/ask preserved; no midpoints stored for decisions.
    """
    assert want in ("puts", "calls")
    p = mcp_call("get_option_chain",
                 {"symbol": sym, "expiration_date": exp, "account_id": ACCT})
    if not isinstance(p, dict):
        raise McpError(f"get_option_chain: expected object payload for {sym} {exp}")
    want_call = (want == "calls")
    out, diag = {}, {"bad_symbol": 0, "wrong_type_or_expiry": 0, "bad_quote": 0,
                     "wide_spread": 0, "liquidity_unknown": 0,
                     "insufficient_liquidity": 0}
    for c in p.get(want, []):
        try:
            osi = c["instrument"]["symbol"]
            c_exp, is_call, k = parse_osi(osi)
        except (ValueError, KeyError, TypeError):
            diag["bad_symbol"] += 1
            continue
        if is_call != want_call or c_exp != exp:
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
    """Return (symbol -> (delta, iv), errors). Per-contract failures are logged.

    Delta validated on [-1, 1] (not [0, 1]) because put deltas may be signed.
    """
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
            errors.append("greeks batch returned non-object payload")
            continue
        for x in g.get("greeks", []):
            try:
                delta = float(x["greeks"]["delta"])
                iv = float(x["greeks"]["impliedVolatility"])
                if not (math.isfinite(delta) and math.isfinite(iv)
                        and -1 <= delta <= 1 and iv > 0):
                    raise ValueError(f"delta={delta} iv={iv} out of range")
                out[x["symbol"]] = (delta, iv)
            except (KeyError, TypeError, ValueError) as exc:
                errors.append(f"invalid greeks for {x.get('symbol', '?')}: {exc}")
    return out, errors


def spread_events(sym, exp, events):
    """Per-spread event evaluation. Returns (flags, rejection_reasons)."""
    expiry = date.fromisoformat(exp)
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


def evaluate_vertical(spot, short_c, long_c, width, kind):
    """Evaluate one vertical spread. kind in {"bull_put", "bear_call"}.

    Conservative credit = short bid - long ask. Stable reason categories;
    numeric details go in diagnostics, not reasons.
    """
    reasons, diag = [], {}
    sk, lk = short_c["strike"], long_c["strike"]
    if kind == "bull_put":
        if not (sk < spot):
            reasons.append("short put not OTM")
        if round(lk, 3) != round(sk - width, 3):
            reasons.append("long leg not at width")
    else:  # bear_call
        if not (sk > spot):
            reasons.append("short call not OTM")
        if round(lk, 3) != round(sk + width, 3):
            reasons.append("long leg not at width")
    sd = abs(short_c["delta"])
    if not (SHORT_DELTA_MIN <= sd <= SHORT_DELTA_MAX):
        reasons.append("short delta outside range")
        diag["short_delta"] = round(sd, 3)
    credit = short_c["bid"] - long_c["ask"]
    if credit <= 0:
        reasons.append("nonpositive net credit")
    max_loss = (width - credit) * 100 if credit > 0 else float("inf")
    if max_loss > MAX_SPREAD_LOSS:
        reasons.append("max loss over limit")
        diag["max_loss"] = round(max_loss, 0)
    friction = ((short_c["spread"] + long_c["spread"]) / credit
                if credit > 0 else float("inf"))
    if friction > MAX_FRICTION:
        reasons.append("execution friction over limit")
        diag["friction"] = round(friction, 2)
    if reasons:
        return {"accepted": False, "reasons": reasons, "diagnostics": diag}
    if kind == "bull_put":
        breakeven = sk - credit
    else:
        breakeven = sk + credit
    net_delta = long_c.get("delta", 0.0) - short_c["delta"]  # long minus short
    return {
        "accepted": True,
        "kind": kind,
        "short_sym": short_c["sym"], "long_sym": long_c["sym"],
        "short_strike": sk, "long_strike": lk,
        "expiration": short_c["expiration"],
        "dte": dte(short_c["expiration"]),
        "width": width,
        "short_delta": short_c["delta"],
        "credit_per_share": credit,
        "credit_total": credit * 100,
        "max_loss_total": max_loss,
        "breakeven": breakeven,
        "return_on_risk": credit / (width - credit),
        "friction": friction,
        "net_delta": net_delta,
        "leg_spread_sum": short_c["spread"] + long_c["spread"],
    }


def evaluate_condor(spot, put_wing, call_wing, width):
    """Combine two accepted wings into an iron condor. Same expiration required."""
    reasons = []
    if put_wing["expiration"] != call_wing["expiration"]:
        reasons.append("wings on different expirations")
        return {"accepted": False, "reasons": reasons, "diagnostics": {}}
    if not (put_wing["short_strike"] < call_wing["short_strike"]):
        reasons.append("wings overlap or inverted")
    total_credit = put_wing["credit_per_share"] + call_wing["credit_per_share"]
    max_loss = (width - total_credit) * 100
    if max_loss > MAX_SPREAD_LOSS:
        reasons.append("condor max loss over limit")
    friction = ((put_wing["leg_spread_sum"] + call_wing["leg_spread_sum"])
                / total_credit)
    if friction > MAX_FRICTION:
        reasons.append("condor friction over limit")
    if reasons:
        return {"accepted": False, "reasons": reasons,
                "diagnostics": {"max_loss": round(max_loss, 0)}}
    return {
        "accepted": True,
        "kind": "iron_condor",
        "expiration": put_wing["expiration"],
        "dte": put_wing["dte"],
        "put_short_strike": put_wing["short_strike"],
        "put_long_strike": put_wing["long_strike"],
        "call_short_strike": call_wing["short_strike"],
        "call_long_strike": call_wing["long_strike"],
        "put_wing_credit": put_wing["credit_total"],
        "call_wing_credit": call_wing["credit_total"],
        "credit_total": total_credit * 100,
        "max_loss_total": max_loss,
        "breakeven_put": put_wing["short_strike"] - total_credit,
        "breakeven_call": call_wing["short_strike"] + total_credit,
        "return_on_risk": total_credit / (width - total_credit),
        "friction": friction,
        "net_delta": put_wing["net_delta"] + call_wing["net_delta"],
        "width": width,
    }


def evaluate_asym_condor(spot, put_wing, call_wing, width):
    """Combine an accepted put wing and call wing into an asymmetric iron
    condor. Same expiration required.

    Naming note (Feedback-01): this was previously called a "defined-risk
    Jade Lizard". That name is wrong. A canonical Jade Lizard (TastyTrade)
    pairs a SHORT PUT with a SHORT CALL SPREAD -- its short put is naked,
    which violates this system's spreads-only rule, and its "no upside
    risk" property requires total credit to exceed the call-spread width.
    What we implement here is a bull put spread (short 0.10-0.20 delta put,
    long put one width below) PLUS a bear call spread (short 0.10-0.20 delta
    call, long call one width above). With the usual non-overlapping strike
    ordering and a common expiration, that is an iron-condor-type structure;
    the asymmetry comes from the skew gate -- the call wing must sit at
    least CALL_DISTANCE_MIN above spot, farther OTM than a symmetric
    condor's call wing ("bullish regime, accept a small upside tail for
    more credit" posture). Because both wings are spreads, max loss is
    capped on both sides: the worse wing's (width - total credit). Exact
    legs are stored on every candidate; the label is only a label.
    """
    reasons = []
    if put_wing["expiration"] != call_wing["expiration"]:
        reasons.append("wings on different expirations")
        return {"accepted": False, "reasons": reasons, "diagnostics": {}}
    if not (put_wing["short_strike"] < call_wing["short_strike"]):
        reasons.append("wings overlap or inverted")
    if call_wing["short_strike"] < spot * (1 + CALL_DISTANCE_MIN):
        reasons.append("call wing too close")
    total_credit = put_wing["credit_per_share"] + call_wing["credit_per_share"]
    # Defined-risk: both wings can't lose at once, so max loss is the worse
    # wing's (width - total credit). Wings share `width` here; written in the
    # general two-wing form for honesty.
    put_wing_loss = (put_wing["width"] - total_credit) * 100
    call_wing_loss = (call_wing["width"] - total_credit) * 100
    max_loss = max(put_wing_loss, call_wing_loss)
    if max_loss > MAX_SPREAD_LOSS:
        reasons.append("asym condor max loss over limit")
    friction = ((put_wing["leg_spread_sum"] + call_wing["leg_spread_sum"])
                / total_credit)
    if friction > MAX_FRICTION:
        reasons.append("asym condor friction over limit")
    if reasons:
        return {"accepted": False, "reasons": reasons,
                "diagnostics": {"max_loss": round(max_loss, 0)}}
    breakeven_put = put_wing["short_strike"] - total_credit
    breakeven_call = call_wing["short_strike"] + total_credit
    return {
        "accepted": True,
        "kind": "asym_condor",
        "expiration": put_wing["expiration"],
        "dte": put_wing["dte"],
        "put_short_strike": put_wing["short_strike"],
        "put_long_strike": put_wing["long_strike"],
        "call_short_strike": call_wing["short_strike"],
        "call_long_strike": call_wing["long_strike"],
        "put_wing_credit": put_wing["credit_total"],
        "call_wing_credit": call_wing["credit_total"],
        "credit_total": total_credit * 100,
        "max_loss_total": max_loss,
        "breakeven_put": breakeven_put,
        "breakeven_call": breakeven_call,
        "upside_distance_pct": (breakeven_call / spot - 1) * 100,
        "return_on_risk": total_credit / (width - total_credit),
        "friction": friction,
        "net_delta": put_wing["net_delta"] + call_wing["net_delta"],
        "width": width,
    }


def narrate_spreads(bull_puts, condors, asym_condors, rej_all):
    """Plain-English readout. Every claim comes from computed values.

    Returns a list of lines; top 3 opportunities per strategy, or the
    hardest-hit gates when nothing qualified.
    """
    lines = []

    def ev_text(r):
        ev = r.get("events") or []
        return "; ".join(ev) if ev else "no event flags"

    def top_rejections(d, n=3):
        return sorted(d.items(), key=lambda kv: (-kv[1], kv[0]))[:n]

    if bull_puts:
        lines.append("Top bull put spreads:")
        for r in bull_puts[:3]:
            below = (1 - r["short_strike"] / r["spot"]) * 100
            lines.append(
                f"- {r['stock']} {r['expiration']} "
                f"{r['short_strike']:.0f}/{r['long_strike']:.0f}P: "
                f"RoR {r['return_on_risk']*100:.1f}% at {r['dte']} DTE, "
                f"short strike {below:.0f}% below spot; {ev_text(r)}.")
    else:
        top = top_rejections(rej_all.get("bull_put", {}))
        if top:
            lines.append("No bull put spreads qualified — gates hit hardest: "
                         + ", ".join(f"{k} x{v}" for k, v in top) + ".")
        else:
            lines.append("No bull put spreads qualified.")

    if condors:
        lines.append("Top iron condors:")
        for r in condors[:3]:
            put_below = (1 - r["put_short_strike"] / r["spot"]) * 100
            call_above = (r["call_short_strike"] / r["spot"] - 1) * 100
            lines.append(
                f"- {r['stock']} {r['expiration']} "
                f"{r['put_short_strike']:.0f}/{r['put_long_strike']:.0f}P x "
                f"{r['call_short_strike']:.0f}/{r['call_long_strike']:.0f}C: "
                f"RoR {r['return_on_risk']*100:.1f}% at {r['dte']} DTE, "
                f"wings {put_below:.0f}% below / {call_above:.0f}% above "
                f"spot; {ev_text(r)}.")
    else:
        top = top_rejections(rej_all.get("iron_condor", {}))
        if top:
            lines.append("No iron condors qualified — gates hit hardest: "
                         + ", ".join(f"{k} x{v}" for k, v in top) + ".")
        else:
            lines.append("No iron condors qualified.")

    if asym_condors:
        lines.append("Top asymmetric iron condors:")
        for r in asym_condors[:3]:
            put_below = (1 - r["put_short_strike"] / r["spot"]) * 100
            call_above = (r["call_short_strike"] / r["spot"] - 1) * 100
            lines.append(
                f"- {r['stock']} {r['expiration']} "
                f"{r['put_short_strike']:.0f}/{r['put_long_strike']:.0f}P + "
                f"{r['call_short_strike']:.0f}/{r['call_long_strike']:.0f}C: "
                f"RoR {r['return_on_risk']*100:.1f}% at {r['dte']} DTE, "
                f"put wing {put_below:.0f}% below spot, call wing "
                f"{call_above:.0f}% above spot; {ev_text(r)}.")
    else:
        top = top_rejections(rej_all.get("asym_condor", {}))
        if top:
            lines.append("No asymmetric iron condors qualified — gates hit hardest: "
                         + ", ".join(f"{k} x{v}" for k, v in top) + ".")
        else:
            lines.append("No asymmetric iron condors qualified.")
    return lines


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json-out", default=None)
    ap.add_argument("--names", default=None)
    ap.add_argument("--universe", default=None,
                        help="index universe from universes.py: sp500, sp100, nasdaq100, dow30 (--names wins)")
    ap.add_argument("--events", default=None)
    ap.add_argument("--width", type=float, default=None,
                        help="strike width in dollars; default auto-scales to price: "
                             "min(5, max(1, round(spot/25)))")
    args = ap.parse_args()
    if args.names:
        names = args.names.split(",")
        universe_tag = "custom"
    elif args.universe:
        from universes import UNIVERSES
        key = args.universe.strip().lower()
        if key not in UNIVERSES:
            raise SystemExit(f"unknown universe {key!r}; choose from {sorted(UNIVERSES)}")
        names = list(UNIVERSES[key])
        universe_tag = key
    else:
        names = NAMES
        universe_tag = "default"
    print(f"Universe: {universe_tag} ({len(names)} names)")
    width_arg = args.width
    events_file = args.events or EVENTS_FILE

    events = {}
    if events_file:
        try:
            with open(events_file) as f:
                events = json.load(f)
        except OSError:
            print("warning: events file unreadable; event data unknown",
                  file=sys.stderr)

    print(f"Options spread screener -- run {RUN_TS} (America/New_York)")
    print("Settings: "
          f"DTE {SPREAD_DTE_MIN}-{SPREAD_DTE_MAX}, short Δ {SHORT_DELTA_MIN}-{SHORT_DELTA_MAX} (abs), "
          f"width {'$' + repr(width_arg) if width_arg else 'auto (price-scaled 1-5)'}, max spread {MAX_SPREAD_PCT:.0%} of mid, "
          f"liquidity >= {MIN_LIQUIDITY} OI/volume per leg, "
          f"max loss ${MAX_SPREAD_LOSS}/spread, max friction {MAX_FRICTION}x, "
          f"asym condor call distance >= {CALL_DISTANCE_MIN:.0%} above spot, "
          f"earnings-in-window={'REJECT' if REJECT_EARNINGS else 'flag'}, "
          f"unknown-earnings={'REJECT' if REQUIRE_EARNINGS_DATE else 'flag'}, "
          f"credit = short bid - long ask (conservative). "
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

    bull_puts, condors, asym_condors = [], [], []
    stock_notes = {}
    rej_all = {"bull_put": {}, "bear_call": {}, "iron_condor": {},
               "asym_condor": {}}
    for sym in names:
        spot = spot_map.get(sym)
        if spot is None or not math.isfinite(spot) or spot <= 0:
            stock_notes[sym] = ["missing or invalid underlying quote"]
            continue
        # Width auto-scales to price: a $5 width on a $44 stock forces the
        # long leg into unquotable delta ~0.03 territory. Scale keeps both
        # legs in liquid strikes.
        width = width_arg if width_arg is not None \
            else min(5.0, max(1.0, round(spot / 25)))
        try:
            raw = mcp_call("get_option_expirations",
                           {"symbol": sym, "account_id": ACCT})
            exps = eligible_expirations(
                sorted(set(re.findall(r"20\d\d-\d\d-\d\d", json.dumps(raw)))),
                SPREAD_DTE_MIN, SPREAD_DTE_MAX)
            if not exps:
                stock_notes[sym] = ["no expirations in DTE window"]
                continue

            # One chain call per expiration; parse puts and calls separately.
            puts_by_exp, calls_by_exp = {}, {}
            diag_p, diag_c = {}, {}
            for exp in exps:
                pc, dp = parse_options(sym, exp, MIN_LIQUIDITY, "puts")
                cc, dc = parse_options(sym, exp, MIN_LIQUIDITY, "calls")
                puts_by_exp[exp], calls_by_exp[exp] = pc, cc
                for k, v in dp.items():
                    diag_p[k] = diag_p.get(k, 0) + v
                for k, v in dc.items():
                    diag_c[k] = diag_c.get(k, 0) + v

            # Greeks for strike-plausible candidates only (limits batch size).
            put_syms = [c["sym"] for pc in puts_by_exp.values()
                        for c in pc.values()
                        if spot * 0.60 <= c["strike"] < spot]
            call_syms = [c["sym"] for cc in calls_by_exp.values()
                         for c in cc.values()
                         if spot < c["strike"] <= spot * 1.40]
            g, gerr = greeks(put_syms + call_syms)
            for pc in puts_by_exp.values():
                for c in pc.values():
                    if c["sym"] in g:
                        c["delta"], c["iv"] = g[c["sym"]]
            for cc in calls_by_exp.values():
                for c in cc.values():
                    if c["sym"] in g:
                        c["delta"], c["iv"] = g[c["sym"]]

            notes = []
            for src, name in ((diag_p, "put"), (diag_c, "call")):
                for k, v in sorted(src.items()):
                    if v:
                        notes.append(f"{name} contracts rejected: {k} x{v}")
            if gerr:
                notes.append(f"greeks issues: {len(gerr)} ({gerr[0][:100]})")

            # Candidate short legs: delta-gated, OTM.
            short_puts, short_calls = [], []
            for pc in puts_by_exp.values():
                for c in pc.values():
                    if "delta" not in c:
                        continue
                    if (SHORT_DELTA_MIN <= abs(c["delta"]) <= SHORT_DELTA_MAX
                            and c["strike"] < spot):
                        short_puts.append(c)
            for cc in calls_by_exp.values():
                for c in cc.values():
                    if "delta" not in c:
                        continue
                    if (SHORT_DELTA_MIN <= abs(c["delta"]) <= SHORT_DELTA_MAX
                            and c["strike"] > spot):
                        short_calls.append(c)
            notes.append(f"{len(short_puts)} put / {len(short_calls)} call "
                         f"short-leg candidates in delta range")

            # Index long legs by (expiration, strike) for exact-width pairing.
            puts_by_strike, calls_by_strike = {}, {}
            for pc in puts_by_exp.values():
                for c in pc.values():
                    puts_by_strike[(c["expiration"], c["strike"])] = c
            for cc in calls_by_exp.values():
                for c in cc.values():
                    calls_by_strike[(c["expiration"], c["strike"])] = c

            bp_rej, bc_rej, ic_rej, ac_rej = {}, {}, {}, {}
            bp_n_rej = bc_n_rej = ic_n_rej = jl_n_rej = 0
            bp_accepted, bc_accepted = [], []

            for s in short_puts:
                target = round(s["strike"] - width, 3)
                l = puts_by_strike.get((s["expiration"], target))
                if l is None:
                    bp_n_rej += 1
                    bp_rej["long leg missing at width"] = \
                        bp_rej.get("long leg missing at width", 0) + 1
                    continue
                flags, event_reasons = spread_events(sym, s["expiration"], events)
                r = evaluate_vertical(spot, s, l, width, "bull_put")
                reasons = r.get("reasons", []) + event_reasons
                if reasons:
                    bp_n_rej += 1
                    for reason in reasons:
                        bp_rej[reason] = bp_rej.get(reason, 0) + 1
                    continue
                r.update({"stock": sym, "spot": spot, "events": flags})
                bp_accepted.append(r)

            for s in short_calls:
                target = round(s["strike"] + width, 3)
                l = calls_by_strike.get((s["expiration"], target))
                if l is None:
                    bc_n_rej += 1
                    bc_rej["long leg missing at width"] = \
                        bc_rej.get("long leg missing at width", 0) + 1
                    continue
                flags, event_reasons = spread_events(sym, s["expiration"], events)
                r = evaluate_vertical(spot, s, l, width, "bear_call")
                reasons = r.get("reasons", []) + event_reasons
                if reasons:
                    bc_n_rej += 1
                    for reason in reasons:
                        bc_rej[reason] = bc_rej.get(reason, 0) + 1
                    continue
                r.update({"stock": sym, "spot": spot, "events": flags})
                bc_accepted.append(r)

            # Iron condors: cross accepted wings on the same expiration.
            ic_accepted = []
            for pw in bp_accepted:
                for cw in bc_accepted:
                    if pw["expiration"] != cw["expiration"]:
                        continue
                    flags, event_reasons = spread_events(
                        sym, pw["expiration"], events)
                    r = evaluate_condor(spot, pw, cw, width)
                    reasons = r.get("reasons", []) + event_reasons
                    if reasons:
                        ic_n_rej += 1
                        for reason in reasons:
                            ic_rej[reason] = ic_rej.get(reason, 0) + 1
                        continue
                    r.update({"stock": sym, "spot": spot, "events": flags})
                    ic_accepted.append(r)

            # asymmetric iron condors (defined-risk): accepted put wing + accepted call
            # wing with the call wing skewed far OTM (asym condor character).
            ac_accepted = []
            for pw in bp_accepted:
                for cw in bc_accepted:
                    if pw["expiration"] != cw["expiration"]:
                        continue
                    flags, event_reasons = spread_events(
                        sym, pw["expiration"], events)
                    r = evaluate_asym_condor(spot, pw, cw, width)
                    reasons = r.get("reasons", []) + event_reasons
                    if reasons:
                        jl_n_rej += 1
                        for reason in reasons:
                            ac_rej[reason] = ac_rej.get(reason, 0) + 1
                        continue
                    r.update({"stock": sym, "spot": spot, "events": flags})
                    ac_accepted.append(r)

            bp_accepted.sort(key=lambda r: (-r["return_on_risk"], r["friction"]))
            bc_accepted.sort(key=lambda r: (-r["return_on_risk"], r["friction"]))
            ic_accepted.sort(key=lambda r: (-r["return_on_risk"], r["friction"]))
            ac_accepted.sort(key=lambda r: (-r["return_on_risk"], r["friction"]))
            bull_puts.extend(bp_accepted[:3])
            condors.extend(ic_accepted[:3])
            asym_condors.extend(ac_accepted[:3])

            notes.append(f"bull puts: {len(bp_accepted)} accepted, "
                         f"{bp_n_rej} rejected")
            for reason, cnt in sorted(bp_rej.items(), key=lambda kv: (-kv[1], kv[0])):
                notes.append(f"  bull-put rejections: {reason} x{cnt}")
            notes.append(f"bear-call wings: {len(bc_accepted)} accepted, "
                         f"{bc_n_rej} rejected")
            for reason, cnt in sorted(bc_rej.items(), key=lambda kv: (-kv[1], kv[0])):
                notes.append(f"  bear-call rejections: {reason} x{cnt}")
            notes.append(f"iron condors: {len(ic_accepted)} accepted, "
                         f"{ic_n_rej} rejected")
            for reason, cnt in sorted(ic_rej.items(), key=lambda kv: (-kv[1], kv[0])):
                notes.append(f"  condor rejections: {reason} x{cnt}")
            notes.append(f"asym condors: {len(ac_accepted)} accepted, "
                         f"{jl_n_rej} rejected")
            for reason, cnt in sorted(ac_rej.items(), key=lambda kv: (-kv[1], kv[0])):
                notes.append(f"  asym condor rejections: {reason} x{cnt}")
            for src, key in ((bp_rej, "bull_put"), (bc_rej, "bear_call"),
                             (ic_rej, "iron_condor"), (ac_rej, "asym_condor")):
                for k, v in src.items():
                    rej_all[key][k] = rej_all[key].get(k, 0) + v
            stock_notes[sym] = notes
        except McpError as e:
            stock_notes[sym] = [f"MCP error: {e}"]

    bull_puts.sort(key=lambda r: (-r["return_on_risk"], r["friction"]))
    condors.sort(key=lambda r: (-r["return_on_risk"], r["friction"]))
    asym_condors.sort(key=lambda r: (-r["return_on_risk"], r["friction"]))

    print("\n=== BULL PUT SPREADS (ranked by return on risk) ===")
    print(f"{'sym':<5}{'exp':<12}{'strikes':<10}{'DTE':>4}{'Δsh':>6}"
          f"{'credit$':>9}{'maxloss$':>10}{'breakeven':>11}{'RoR%':>7}{'fric':>6}")
    for r in bull_puts[:24]:
        ev = " !! " + "; ".join(r["events"]) if r["events"] else ""
        print(f"{r['stock']:<5}{r['expiration']:<12}"
              f"{r['short_strike']:.0f}/{r['long_strike']:.0f}P{'':<4}"
              f"{r['dte']:>4}{abs(r['short_delta']):>6.2f}"
              f"{r['credit_total']:>9.0f}{r['max_loss_total']:>10.0f}"
              f"{r['breakeven']:>11.2f}{r['return_on_risk']*100:>7.1f}"
              f"{r['friction']:>6.1f}{ev}")

    print("\n=== IRON CONDORS (ranked by return on risk) ===")
    print(f"{'sym':<5}{'exp':<12}{'put wing':<11}{'call wing':<11}{'DTE':>4}"
          f"{'credit$':>9}{'maxloss$':>10}{'be_put':>9}{'be_call':>9}{'RoR%':>7}")
    for r in condors[:24]:
        ev = " !! " + "; ".join(r["events"]) if r["events"] else ""
        print(f"{r['stock']:<5}{r['expiration']:<12}"
              f"{r['put_short_strike']:.0f}/{r['put_long_strike']:.0f}P{'':<3}"
              f"{r['call_short_strike']:.0f}/{r['call_long_strike']:.0f}C{'':<2}"
              f"{r['dte']:>4}"
              f"{r['credit_total']:>9.0f}{r['max_loss_total']:>10.0f}"
              f"{r['breakeven_put']:>9.2f}{r['breakeven_call']:>9.2f}"
              f"{r['return_on_risk']*100:>7.1f}{ev}")

    print("\n=== ASYMMETRIC IRON CONDORS (ranked by return on risk) ===")
    print(f"{'sym':<5}{'exp':<12}{'put wing':<11}{'call wing':<11}{'DTE':>4}"
          f"{'credit$':>9}{'maxloss$':>10}{'be_put':>9}{'be_call':>9}"
          f"{'up%':>6}{'RoR%':>7}")
    for r in asym_condors[:24]:
        ev = " !! " + "; ".join(r["events"]) if r["events"] else ""
        print(f"{r['stock']:<5}{r['expiration']:<12}"
              f"{r['put_short_strike']:.0f}/{r['put_long_strike']:.0f}P{'':<3}"
              f"{r['call_short_strike']:.0f}/{r['call_long_strike']:.0f}C{'':<2}"
              f"{r['dte']:>4}"
              f"{r['credit_total']:>9.0f}{r['max_loss_total']:>10.0f}"
              f"{r['breakeven_put']:>9.2f}{r['breakeven_call']:>9.2f}"
              f"{r['upside_distance_pct']:>6.1f}"
              f"{r['return_on_risk']*100:>7.1f}{ev}")

    print("\n* return on risk = credit / max loss: a screening ratio, not an "
          "expected return. Credits use conservative short-bid minus long-ask fills.")
    print("\nRejection notes:")
    for sym in names:
        for n in stock_notes.get(sym, ["no data"]):
            print(f"  {sym}: {n}")

    print("\n=== READOUT ===")
    readout = []
    try:
        readout = narrate_spreads(bull_puts, condors, asym_condors, rej_all)
        for line in readout:
            print(line)
    except Exception:
        print("readout unavailable")

    if args.json_out:
        best = {"bull_puts": {}, "iron_condors": {}, "asym_condors": {}}
        for r in bull_puts:
            if r["stock"] not in best["bull_puts"]:
                best["bull_puts"][r["stock"]] = {
                    "expiration": r["expiration"],
                    "short_strike": r["short_strike"],
                    "long_strike": r["long_strike"],
                    "credit_total": round(r["credit_total"], 0),
                    "max_loss_total": round(r["max_loss_total"], 0),
                    "breakeven": round(r["breakeven"], 2),
                    "return_on_risk": round(r["return_on_risk"], 4),
                    "events": r["events"],
                }
        for r in condors:
            if r["stock"] not in best["iron_condors"]:
                best["iron_condors"][r["stock"]] = {
                    "expiration": r["expiration"],
                    "put_wing": [r["put_short_strike"], r["put_long_strike"]],
                    "call_wing": [r["call_short_strike"], r["call_long_strike"]],
                    "credit_total": round(r["credit_total"], 0),
                    "max_loss_total": round(r["max_loss_total"], 0),
                    "breakeven_put": round(r["breakeven_put"], 2),
                    "breakeven_call": round(r["breakeven_call"], 2),
                    "return_on_risk": round(r["return_on_risk"], 4),
                    "events": r["events"],
                }
        for r in asym_condors:
            if r["stock"] not in best["asym_condors"]:
                best["asym_condors"][r["stock"]] = {
                    "expiration": r["expiration"],
                    "put_wing": [r["put_short_strike"], r["put_long_strike"]],
                    "call_wing": [r["call_short_strike"], r["call_long_strike"]],
                    "credit_total": round(r["credit_total"], 0),
                    "max_loss_total": round(r["max_loss_total"], 0),
                    "breakeven_put": round(r["breakeven_put"], 2),
                    "breakeven_call": round(r["breakeven_call"], 2),
                    "upside_distance_pct": round(r["upside_distance_pct"], 1),
                    "return_on_risk": round(r["return_on_risk"], 4),
                    "events": r["events"],
                }
        with open(args.json_out, "w") as f:
            json.dump({"asof": RUN_DATE.isoformat(), "results": best,
                       "readout": readout}, f, indent=1)
        print(f"\nwrote {args.json_out}", file=sys.stderr)


if __name__ == "__main__":
    main()
