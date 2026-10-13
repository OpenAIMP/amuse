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
import concurrent.futures
import json
import os
import math
import re
import sys
from datetime import date, datetime
from zoneinfo import ZoneInfo


ACCT = os.environ.get("PUBLIC_ACCOUNT_ID") or ""
if not ACCT:
    raise SystemExit("PUBLIC_ACCOUNT_ID is not set; set the environment variable locally or configure the GitHub Actions repository secret (#23)")
NAMES = ["T", "VZ", "BAC", "PFE", "KO", "MRK", "BMY", "SBUX", "DIS", "XOM"]

# ---- screening configuration (design choices, printed in every report) ----
# Tunables live in gates.yaml; this block binds them to module constants.
import gates as _gates_mod
import mcp_client
from mcp_client import McpError
from market_data import daily_bars, quotes
from options_chain import dte, eligible_expirations
from options_chain import parse_chain
from options_chain import greeks as chain_greeks
from screening_common import evaluation_record, qualification_counts
import vol as _vol


def _apply_gates(path=None):
    global SPREAD_DTE_MIN, SPREAD_DTE_MAX, SHORT_DELTA_MIN, SHORT_DELTA_MAX
    global SPREAD_WIDTH, MAX_SPREAD_PCT, MIN_LIQUIDITY, MAX_SPREAD_LOSS
    global MAX_FRICTION, CALL_DISTANCE_MIN, WIDTH_MIN, WIDTH_MAX, WIDTH_DIVISOR
    global VOL_CFG
    G = _gates_mod.load(path)["spreads"]
    SPREAD_DTE_MIN, SPREAD_DTE_MAX = G["dte_min"], G["dte_max"]
    SHORT_DELTA_MIN, SHORT_DELTA_MAX = G["short_delta_min"], G["short_delta_max"]
    SPREAD_WIDTH = 5              # strike width in dollars (configurable via --width)
    MAX_SPREAD_PCT = G["max_spread_pct"]
    MIN_LIQUIDITY = G["min_liquidity"]
    MAX_SPREAD_LOSS = G["max_loss"]
    MAX_FRICTION = G["max_friction"]
    CALL_DISTANCE_MIN = G["call_distance_min"]
    WIDTH_MIN, WIDTH_MAX, WIDTH_DIVISOR = G["width_min"], G["width_max"], G["width_divisor"]
    VOL_CFG = _gates_mod.load(path)["vol"]


_apply_gates()
GREEKS_BATCH = 40             # implementation setting, not a verified service limit
REJECT_EARNINGS = True        # earnings inside the spread window rejects it
REQUIRE_EARNINGS_DATE = False  # True = unknown earnings date also rejects
import os as _os
_EVENTS_DEFAULT = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "earnings_dates.json")
EVENTS_FILE = _EVENTS_DEFAULT if _os.path.exists(_EVENTS_DEFAULT) else None  # curated earnings dates (#33)

RUN_DATE = datetime.now(ZoneInfo("America/New_York")).date()
RUN_TS = datetime.now(ZoneInfo("America/New_York")).isoformat(timespec="seconds")


def vol_read_for(sym, spot, puts_by_exp, calls_by_exp, exps, iv_history_path):
    """Cheap-vs-expensive read for one underlying (issue #7).

    Uses the already-fetched chains/Greeks plus one get_price_history call
    for HV. Records an IV snapshot so IV Rank builds forward. Never raises
    for bad data -- returns a NO_READ assessment instead.
    """
    try:
        return _vol_read_inner(sym, spot, puts_by_exp, calls_by_exp, exps,
                               iv_history_path)
    except Exception as e:
        return {"iv": None, "hv": None, "iv_rank": None, "iv_vs_hv": None,
                "skew_25d": None, "term_structure": None,
                "decision": _vol.NO_READ,
                "reason": f"vol assessment failed: {e}"}


def _vol_read_inner(sym, spot, puts_by_exp, calls_by_exp, exps, iv_history_path):
    # HV from one year of daily bars.
    try:
        closes = [b["close"] for b in daily_bars(sym, ACCT, "YEAR")]
    except Exception:
        closes = []
    hv20 = _vol.realized_vol(closes, VOL_CFG["hv_short"]) if closes else None
    hv60 = _vol.realized_vol(closes, VOL_CFG["hv_long"]) if closes else None

    all_puts = [c for pc in puts_by_exp.values() for c in pc.values()
                if c.get("iv")]
    all_calls = [c for cc in calls_by_exp.values() for c in cc.values()
                 if c.get("iv")]

    def atm_iv(contracts):
        if not contracts:
            return None
        return min(contracts, key=lambda x: abs(x["strike"] - spot))["iv"]

    # 30-day IV: average of ATM put/call IV at the expiry nearest 30 DTE.
    iv30 = None
    if exps:
        e30 = min(exps, key=lambda e: abs(dte(e) - 30))
        sleeve = ([c for c in all_puts if c["expiration"] == e30]
                  + [c for c in all_calls if c["expiration"] == e30])
        # atm of puts and calls separately, then average
        p_iv = atm_iv([c for c in all_puts if c["expiration"] == e30])
        c_iv = atm_iv([c for c in all_calls if c["expiration"] == e30])
        ivs = [v for v in (p_iv, c_iv) if v]
        iv30 = sum(ivs) / len(ivs) if ivs else None

    # 25-delta skew from the full fetched set.
    def near_delta(contracts, target):
        cands = [c for c in contracts if c.get("delta") is not None]
        if not cands:
            return None
        return min(cands,
                   key=lambda x: abs(abs(x["delta"]) - target))["iv"]

    put25 = near_delta(all_puts, 0.25)
    call25 = near_delta(all_calls, 0.25)

    # Term structure: ATM put IV at nearest vs farthest expiry in window.
    iv_near = iv_far = None
    if exps:
        e_near = min(exps, key=dte)
        e_far = max(exps, key=dte)
        iv_near = atm_iv([c for c in all_puts if c["expiration"] == e_near])
        iv_far = atm_iv([c for c in all_puts if c["expiration"] == e_far])

    history = _vol.load_history(iv_history_path, sym)
    read = _vol.assess(iv30, hv20, history, put25, call25,
                       iv_near, iv_far, VOL_CFG)
    read["hv20"], read["hv60"] = hv20, hv60
    if iv30:
        try:
            _vol.record_snapshot(iv_history_path, sym, iv30)
        except OSError:
            pass
    return read


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
    # probability estimates: P(short expires OTM) ≈ 1 - |delta|
    _pwin = max(0.0, min(1.0, 1 - abs(short_c["delta"])))
    _cd = credit * 100
    # bull put: best = above breakeven; worst = below long strike
    # bear call: best = below breakeven; worst = above long strike
    _is_put = kind == "bull_put_spread"
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
        "win_prob_est": round(_pwin, 3),
        "expected_value": round(_pwin * _cd - (1 - _pwin) * max_loss, 0),
        "loss_multiple": round(max_loss / _cd, 2) if _cd > 0 else None,
        "lucrative": lucrative_label(round(_pwin, 3),
                                     round(_pwin * _cd - (1 - _pwin) * max_loss, 0),
                                     round(max_loss / _cd, 2) if _cd > 0 else None),
        "best_case_range": ([round(breakeven, 2), "and up"] if _is_put
                            else ["and down", round(breakeven, 2)]),
        "worst_case_price": round(lk, 2),
    }


def lucrative_label(win_prob, ev, loss_mult):
    """Classify a spread as lucrative or not (#28).

    Lucrative = high win probability AND positive expectancy AND
    sane loss multiple. This is a screen, not a guarantee.
    """
    if win_prob is None or ev is None:
        return "Unknown"
    lm = loss_mult if loss_mult else 99
    if win_prob >= 0.70 and ev > 0 and lm <= 3.0:
        return "Lucrative"
    if win_prob >= 0.60 and ev > 0 and lm <= 4.0:
        return "Solid"
    if ev is not None and ev <= 0:
        return "Negative EV"
    if lm > 4.0:
        return "High risk"
    return "Marginal"


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
        # --- probability estimates (#28): delta-based, labeled as estimates ---
        # P(short leg expires OTM) ≈ 1 - |delta|; joint assumes independence
        "put_short_delta": put_wing["short_delta"],
        "call_short_delta": call_wing["short_delta"],
    }
    # win probability and expected value from the short-leg deltas
    # P(short leg expires OTM) ≈ 1 - |delta|; joint assumes independence.
    # These are ESTIMATES, not market facts -- see the hub guide.
    pd = abs(put_wing["short_delta"])
    cd = abs(call_wing["short_delta"])
    p_win = max(0.0, min(1.0, (1 - pd) * (1 - cd)))
    credit_dollars = total_credit * 100
    result = {
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
        "put_short_delta": put_wing["short_delta"],
        "call_short_delta": call_wing["short_delta"],
        "win_prob_est": round(p_win, 3),
        "expected_value": round(p_win * credit_dollars - (1 - p_win) * max_loss, 0),
        "loss_multiple": round(max_loss / credit_dollars, 2) if credit_dollars > 0 else None,
        "lucrative": lucrative_label(round(p_win, 3),
                                     round(p_win * credit_dollars - (1 - p_win) * max_loss, 0),
                                     round(max_loss / credit_dollars, 2) if credit_dollars > 0 else None),
        # price ranges for the explainer
        "best_case_range": [round(put_wing["short_strike"] - total_credit, 2),
                            round(call_wing["short_strike"] + total_credit, 2)],
        "worst_case_put": round(put_wing["long_strike"], 2),
        "worst_case_call": round(call_wing["long_strike"], 2),
    }
    return result


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
        "put_short_delta": put_wing["short_delta"],
        "call_short_delta": call_wing["short_delta"],
        "win_prob_est": round(max(0.0, min(1.0, (1 - abs(put_wing["short_delta"])) * (1 - abs(call_wing["short_delta"])))), 3),
        "expected_value": round(max(0.0, min(1.0, (1 - abs(put_wing["short_delta"])) * (1 - abs(call_wing["short_delta"])))) * total_credit * 100 - (1 - max(0.0, min(1.0, (1 - abs(put_wing["short_delta"])) * (1 - abs(call_wing["short_delta"]))))) * max_loss, 0),
        "loss_multiple": round(max_loss / (total_credit * 100), 2) if total_credit > 0 else None,
        "lucrative": lucrative_label(
            round(max(0.0, min(1.0, (1 - abs(put_wing["short_delta"])) * (1 - abs(call_wing["short_delta"])))), 3),
            round(max(0.0, min(1.0, (1 - abs(put_wing["short_delta"])) * (1 - abs(call_wing["short_delta"])))) * total_credit * 100 - (1 - max(0.0, min(1.0, (1 - abs(put_wing["short_delta"])) * (1 - abs(call_wing["short_delta"]))))) * max_loss, 0),
            round(max_loss / (total_credit * 100), 2) if total_credit > 0 else None),
        "best_case_range": [round(breakeven_put, 2), round(breakeven_call, 2)],
        "worst_case_put": round(put_wing["long_strike"], 2),
        "worst_case_call": round(call_wing["long_strike"], 2),
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


def screen_spreads_sym(sym, spot_map, width_arg, events, iv_hist_path, no_vol):
    """Price all structures for one underlying. Returns a result dict.

    Pure per-symbol work; safe to run in a thread pool (issue #14).
    Keys: bp/ic/ac (top-3 accepted structure lists), notes (list),
    rejs ({kind: {reason: count}}), vol_veto (int), error (None or str),
    considered (issue #38: every evaluated structure with qualification),
    chain (issue #38: every retrieved contract with its gate status).
    """
    out = {"bp": [], "ic": [], "ac": [], "notes": [],
           "rejs": {"bull_put": {}, "bear_call": {}, "iron_condor": {},
                    "asym_condor": {}},
           "vol_veto": 0, "error": None}
    spot = spot_map.get(sym)
    if spot is None or not math.isfinite(spot) or spot <= 0:
        out["notes"] = ["missing or invalid underlying quote"]
        return out
    # Width auto-scales to price: a $5 width on a $44 stock forces the
    # long leg into unquotable delta ~0.03 territory. Scale keeps both
    # legs in liquid strikes.
    width = width_arg if width_arg is not None \
        else min(WIDTH_MAX, max(WIDTH_MIN, round(spot / WIDTH_DIVISOR)))
    try:
        raw = mcp_client.mcp_call("get_option_expirations",
                       {"symbol": sym, "account_id": ACCT})
        exps = eligible_expirations(
            sorted(set(re.findall(r"20\d\d-\d\d-\d\d", json.dumps(raw)))),
            SPREAD_DTE_MIN, SPREAD_DTE_MAX)
        if not exps:
            out["notes"] = ["no expirations in DTE window"]
            return out

        # One chain call per expiration; parse puts and calls separately.
        puts_by_exp, calls_by_exp = {}, {}
        diag_p, diag_c = {}, {}
        chain_rejected = []
        for exp in exps:
            pc, dp, rp = parse_chain(sym, exp, ACCT, MIN_LIQUIDITY,
                                 MAX_SPREAD_PCT, "puts")
            cc, dc, rc = parse_chain(sym, exp, ACCT, MIN_LIQUIDITY,
                                 MAX_SPREAD_PCT, "calls")
            puts_by_exp[exp], calls_by_exp[exp] = pc, cc
            chain_rejected.extend(rp)
            chain_rejected.extend(rc)
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
        g, gerr = chain_greeks(put_syms + call_syms, ACCT,
                               signed=True, batch_size=GREEKS_BATCH)
        for pc in puts_by_exp.values():
            for c in pc.values():
                if c["sym"] in g:
                    c["delta"], c["iv"] = g[c["sym"]]
        for cc in calls_by_exp.values():
            for c in cc.values():
                if c["sym"] in g:
                    c["delta"], c["iv"] = g[c["sym"]]
        # Preserve valid as well as rejected contracts for the report audit.
        for side, by_exp in (("put", puts_by_exp), ("call", calls_by_exp)):
            for contracts in by_exp.values():
                chain_rejected.extend({**c, "type": side,
                                       "gate": "passed quote/liquidity gates"}
                                      for c in contracts.values())

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
        # Issue #38: qualify-don't-filter. Every evaluated structure lands
        # here with its qualification and reasons, accepted or not.
        considered = []

        def _record(structure, expiration, short_strike, long_strike,
                    qualification, reasons, diagnostics=None):
            considered.append({
                "structure": structure, "symbol": sym,
                "expiration": expiration,
                "short_strike": short_strike, "long_strike": long_strike,
                "width": width, "qualification": qualification,
                "reasons": list(reasons),
                "diagnostics": dict(diagnostics or {}),
            })

        for s in short_puts:
            target = round(s["strike"] - width, 3)
            l = puts_by_strike.get((s["expiration"], target))
            if l is None:
                bp_n_rej += 1
                bp_rej["long leg missing at width"] = \
                    bp_rej.get("long leg missing at width", 0) + 1
                _record("bull_put", s["expiration"], s["strike"], target,
                        "rejected", ["long leg missing at width"])
                continue
            flags, event_reasons = spread_events(sym, s["expiration"], events)
            r = evaluate_vertical(spot, s, l, width, "bull_put")
            reasons = r.get("reasons", []) + event_reasons
            if reasons:
                bp_n_rej += 1
                for reason in reasons:
                    bp_rej[reason] = bp_rej.get(reason, 0) + 1
                _record("bull_put", s["expiration"], s["strike"],
                        l["strike"], "rejected", reasons,
                        r.get("diagnostics"))
                continue
            r.update({"stock": sym, "spot": spot, "events": flags})
            bp_accepted.append(r)
            _record("bull_put", r["expiration"], r["short_strike"],
                    r["long_strike"], "accepted", [])

        for s in short_calls:
            target = round(s["strike"] + width, 3)
            l = calls_by_strike.get((s["expiration"], target))
            if l is None:
                bc_n_rej += 1
                bc_rej["long leg missing at width"] = \
                    bc_rej.get("long leg missing at width", 0) + 1
                _record("bear_call", s["expiration"], s["strike"], target,
                        "rejected", ["long leg missing at width"])
                continue
            flags, event_reasons = spread_events(sym, s["expiration"], events)
            r = evaluate_vertical(spot, s, l, width, "bear_call")
            reasons = r.get("reasons", []) + event_reasons
            if reasons:
                bc_n_rej += 1
                for reason in reasons:
                    bc_rej[reason] = bc_rej.get(reason, 0) + 1
                _record("bear_call", s["expiration"], s["strike"],
                        l["strike"], "rejected", reasons,
                        r.get("diagnostics"))
                continue
            r.update({"stock": sym, "spot": spot, "events": flags})
            bc_accepted.append(r)
            _record("bear_call", r["expiration"], r["short_strike"],
                    r["long_strike"], "accepted", [])

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
                wings = (f"{pw['short_strike']}/{pw['long_strike']}P x "
                         f"{cw['short_strike']}/{cw['long_strike']}C")
                if reasons:
                    ic_n_rej += 1
                    for reason in reasons:
                        ic_rej[reason] = ic_rej.get(reason, 0) + 1
                    _record("iron_condor", pw["expiration"],
                            pw["short_strike"], pw["long_strike"],
                            "rejected", reasons, {"wings": wings})
                    continue
                r.update({"stock": sym, "spot": spot, "events": flags})
                ic_accepted.append(r)
                _record("iron_condor", r["expiration"],
                        r.get("put_short", pw["short_strike"]),
                        r.get("put_long", pw["long_strike"]),
                        "accepted", [], {"wings": wings})

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
                wings = (f"{pw['short_strike']}/{pw['long_strike']}P x "
                         f"{cw['short_strike']}/{cw['long_strike']}C")
                if reasons:
                    jl_n_rej += 1
                    for reason in reasons:
                        ac_rej[reason] = ac_rej.get(reason, 0) + 1
                    _record("asym_condor", pw["expiration"],
                            pw["short_strike"], pw["long_strike"],
                            "rejected", reasons, {"wings": wings})
                    continue
                r.update({"stock": sym, "spot": spot, "events": flags})
                ac_accepted.append(r)
                _record("asym_condor", r["expiration"],
                        r.get("put_short", pw["short_strike"]),
                        r.get("put_long", pw["long_strike"]),
                        "accepted", [], {"wings": wings})

        bp_accepted.sort(key=lambda r: (-r["return_on_risk"], r["friction"]))
        bc_accepted.sort(key=lambda r: (-r["return_on_risk"], r["friction"]))
        ic_accepted.sort(key=lambda r: (-r["return_on_risk"], r["friction"]))
        ac_accepted.sort(key=lambda r: (-r["return_on_risk"], r["friction"]))

        # Vol assessment (issue #7): sits between Regime and Timing.
        # Cheap premium stands down -- structures are vetoed, not ranked.
        if not no_vol and (bp_accepted or ic_accepted or ac_accepted):
            vol_read = vol_read_for(sym, spot, puts_by_exp, calls_by_exp,
                                    exps, iv_hist_path)
            slim = {k: vol_read[k] for k in
                    ("iv", "hv", "iv_rank", "iv_vs_hv",
                     "skew_25d", "term_structure", "decision")}
            for r in bp_accepted + ic_accepted + ac_accepted:
                r["vol"] = slim
            notes.append(
                "vol: " + ", ".join(f"{k}={v}" for k, v in slim.items())
                + f" ({vol_read['reason']})")
            if vol_read["decision"] == _vol.STAND_DOWN:
                n_veto = (len(bp_accepted) + len(ic_accepted)
                          + len(ac_accepted))
                out["vol_veto"] += n_veto
                notes.append(f"vol veto: {n_veto} structures stood down "
                             "(cheap premium)")
                for c in considered:
                    if c["qualification"] == "accepted":
                        c["qualification"] = "rejected"
                        c["reasons"] = ["vol veto: cheap premium"]
                bp_accepted, ic_accepted, ac_accepted = [], [], []

        out["bp"] = bp_accepted[:3]
        out["ic"] = ic_accepted[:3]
        out["ac"] = ac_accepted[:3]
        out["considered"] = considered
        out["chain"] = chain_rejected

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
                out["rejs"][key][k] = out["rejs"][key].get(k, 0) + v
        out["notes"] = notes
    except McpError as e:
        out["error"] = f"MCP error: {e}"
    return out


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
    ap.add_argument("--config", default=None,
                        help="path to gates.yaml (default: gates.yaml next to the script)")
    ap.add_argument("--workers", type=int, default=8,
                    help="concurrent MCP workers (default 8; 1 = sequential)")
    ap.add_argument("--portfolio-config", default=None,
                    help="JSON with buying_power, limits, sectors, correlations; "
                         "adds portfolio-level selection to --json-out")
    ap.add_argument("--no-vol", action="store_true",
                    help="skip the cheap-vs-expensive vol assessment")
    ap.add_argument("--iv-history", default=None,
                    help="path to IV snapshot history (default: iv_history.jsonl "
                         "next to the script; created if missing)")
    args = ap.parse_args()
    if args.config:
        _apply_gates(args.config)
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
    iv_hist_path = args.iv_history or os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "iv_history.jsonl")

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
          f"width {'$' + repr(width_arg) if width_arg else f'auto (price-scaled {WIDTH_MIN:g}-{WIDTH_MAX:g})'}, max spread {MAX_SPREAD_PCT:.0%} of mid, "
          f"liquidity >= {MIN_LIQUIDITY} OI/volume per leg, "
          f"max loss ${MAX_SPREAD_LOSS}/spread, max friction {MAX_FRICTION}x, "
          f"asym condor call distance >= {CALL_DISTANCE_MIN:.0%} above spot, "
          f"earnings-in-window={'REJECT' if REJECT_EARNINGS else 'flag'}, "
          f"unknown-earnings={'REJECT' if REQUIRE_EARNINGS_DATE else 'flag'}, "
          f"credit = short bid - long ask (conservative). "
          f"Assumes standard 100-share deliverables (not validated).")
    if not args.no_vol:
        print(f"Vol assessment: on (cheap-vs-expensive; IV history: {iv_hist_path})")
    else:
        print("Vol assessment: OFF (--no-vol)")

    quote_error = None
    try:
        spot_map = quotes(names, ACCT)
    except McpError as e:
        # A failed batch request is a data outage for every symbol. Preserve
        # the full universe in diagnostics without amplifying the outage with
        # one failing quote request per symbol.
        spot_map = {}
        quote_error = f"MCP error: batch underlying quotes failed: {e}"
        print(quote_error, file=sys.stderr)

    bull_puts, condors, asym_condors = [], [], []
    stock_notes, diagnostics = {}, {}
    screened = []
    vol_veto_total = 0
    rej_all = {"bull_put": {}, "bear_call": {}, "iron_condor": {},
               "asym_condor": {}}

    def safe(sym):
        if quote_error:
            return (sym, {"bp": [], "ic": [], "ac": [], "notes": [],
                          "rejs": {"bull_put": {}, "bear_call": {},
                                   "iron_condor": {}, "asym_condor": {}},
                          "vol_veto": 0, "error": quote_error})
        try:
            return (sym, screen_spreads_sym(sym, spot_map, width_arg,
                                            events, iv_hist_path,
                                            args.no_vol))
        except Exception as e:  # one bad name never kills the run
            return (sym, {"bp": [], "ic": [], "ac": [], "notes": [],
                          "rejs": {"bull_put": {}, "bear_call": {},
                                   "iron_condor": {}, "asym_condor": {}},
                          "vol_veto": 0,
                          "error": f"unexpected error: {type(e).__name__}: {e}"})

    # Thread pool over names (issue #14). Merge in submission order in the
    # main thread: no shared-state locks, deterministic output.
    with concurrent.futures.ThreadPoolExecutor(
            max_workers=max(1, args.workers)) as ex:
        results = list(ex.map(safe, names))
    for sym, r in results:
        stock_notes[sym] = [r["error"]] if r["error"] else r["notes"]
        diagnostics[sym] = {"considered": r.get("considered", []),
                            "chain": r.get("chain", []),
                            "notes": stock_notes[sym],
                            "error": r.get("error")}
        accepted_count = len(r["bp"]) + len(r["ic"]) + len(r["ac"])
        if r["error"]:
            screened.append(evaluation_record({"symbol": sym}, error=r["error"]))
        else:
            screened.append(evaluation_record(
                {"symbol": sym, "accepted_structures": accepted_count},
                [] if accepted_count else (r["notes"] or ["no structures passed all gates"])))
        for key, d in r["rejs"].items():
            for k, v in d.items():
                rej_all[key][k] = rej_all[key].get(k, 0) + v
        bull_puts.extend(r["bp"])
        condors.extend(r["ic"])
        asym_condors.extend(r["ac"])
        vol_veto_total += r["vol_veto"]

    bull_puts.sort(key=lambda r: (-r["return_on_risk"], r["friction"]))
    condors.sort(key=lambda r: (-r["return_on_risk"], r["friction"]))
    asym_condors.sort(key=lambda r: (-r["return_on_risk"], r["friction"]))
    if vol_veto_total:
        print(f"\nVol vetoes: {vol_veto_total} structures stood down on cheap "
              "premium (issue #7).")

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
                    "win_prob_est": r.get("win_prob_est"),
                    "expected_value": r.get("expected_value"),
                    "loss_multiple": r.get("loss_multiple"),
                    "lucrative": r.get("lucrative"),
                    "events": r["events"],
                    "vol": r.get("vol"),
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
                    "win_prob_est": r.get("win_prob_est"),
                    "expected_value": r.get("expected_value"),
                    "loss_multiple": r.get("loss_multiple"),
                    "lucrative": r.get("lucrative"),
                    "events": r["events"],
                    "vol": r.get("vol"),
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
                    "win_prob_est": r.get("win_prob_est"),
                    "expected_value": r.get("expected_value"),
                    "loss_multiple": r.get("loss_multiple"),
                    "lucrative": r.get("lucrative"),
                    "events": r["events"],
                    "vol": r.get("vol"),
                }
        portfolio = None
        if args.portfolio_config:
            import portfolio_selection as _ps
            cfg = _ps.load_config(args.portfolio_config)
            pairs = ([("bull_put", r) for r in bull_puts]
                     + [("iron_condor", r) for r in condors]
                     + [("asym_condor", r) for r in asym_condors])
            corr = {tuple(k.split("|")): v
                    for k, v in (cfg.get("correlations") or {}).items()}
            portfolio = _ps.select_portfolio(
                _ps.candidates_from_spreads(pairs, cfg.get("sectors")),
                cfg["buying_power"], cfg.get("limits"), cfg.get("baseline"), corr)
        with open(args.json_out, "w") as f:
            json.dump({"asof": RUN_DATE.isoformat(), "results": best,
                       "portfolio": portfolio,
                       "diagnostics": diagnostics,
                       "screened": screened,
                       "qualification_counts": qualification_counts(screened),
                       "readout": readout}, f, indent=1)
        print(f"\nwrote {args.json_out}", file=sys.stderr)


if __name__ == "__main__":
    main()
