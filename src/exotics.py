"""Exotic options strategy evaluators (#107, Phases G-I).

Extracted from spread_screener.py for modularity. Each evaluator follows
the standard pattern: returns dict with accepted/kind/expiration/dte/strikes/
credit_total/debit_total/max_loss_total. Undefined-risk strategies carry
risk_warning=True and risk_note.

Phases:
  G: backspreads (call/put), broken-wing butterflies, inverse broken wings
  H: ladders (call/put), Jade Lizards (proper + reverse)
  I: synthetic futures, combos/risk-reversals, strips/straps, guts,
     double diagonals
"""

import math

from options_chain import dte


def evaluate_call_backspread(spot, short_c, long_c1, long_c2):
    """Evaluate a call ratio backspread: sell 1 ATM/ITM call, buy 2 OTM calls.
    Net debit. Unlimited upside profit, limited downside risk (net debit).
    UNDEFINED RISK label not needed — risk is defined (debit paid), but the
    structure is net-long and benefits from upside expansion.
    """
    reasons = []
    exps = {short_c["expiration"], long_c1["expiration"], long_c2["expiration"]}
    if len(exps) > 1:
        reasons.append("legs on different expirations")
        return {"accepted": False, "reasons": reasons, "diagnostics": {}}
    # Structure: short lower strike, long 2x higher strikes
    if not (short_c["strike"] < long_c1["strike"] <= long_c2["strike"]):
        reasons.append("strikes not ordered for backspread")
    # Net debit: 2*long ask - 1*short bid
    debit = 2 * long_c1["ask"] - short_c["bid"]
    # For simplicity, use long_c1 for both longs (same strike)
    if reasons:
        return {"accepted": False, "reasons": reasons, "diagnostics": {}}
    return {
        "accepted": True,
        "kind": "call_backspread",
        "expiration": short_c["expiration"],
        "dte": dte(short_c["expiration"]),
        "short_strike": short_c["strike"],
        "long_strike": long_c1["strike"],
        "ratio": "1x2",
        "credit_total": 0,
        "debit_total": debit * 100 if debit > 0 else 0,
        "max_loss_total": debit * 100 if debit > 0 else 0,
        "max_profit_total": float("inf"),
        "risk_note": "Unlimited upside; max loss = debit paid",
    }


def evaluate_put_backspread(spot, short_p, long_p1, long_p2):
    """Evaluate a put ratio backspread: sell 1 ATM/ITM put, buy 2 OTM puts.
    Net debit. Unlimited downside profit, limited upside risk (net debit).
    """
    reasons = []
    exps = {short_p["expiration"], long_p1["expiration"], long_p2["expiration"]}
    if len(exps) > 1:
        reasons.append("legs on different expirations")
        return {"accepted": False, "reasons": reasons, "diagnostics": {}}
    # Structure: short higher strike, long 2x lower strikes
    if not (short_p["strike"] > long_p1["strike"] >= long_p2["strike"]):
        reasons.append("strikes not ordered for backspread")
    debit = 2 * long_p1["ask"] - short_p["bid"]
    if reasons:
        return {"accepted": False, "reasons": reasons, "diagnostics": {}}
    return {
        "accepted": True,
        "kind": "put_backspread",
        "expiration": short_p["expiration"],
        "dte": dte(short_p["expiration"]),
        "short_strike": short_p["strike"],
        "long_strike": long_p1["strike"],
        "ratio": "1x2",
        "credit_total": 0,
        "debit_total": debit * 100 if debit > 0 else 0,
        "max_loss_total": debit * 100 if debit > 0 else 0,
        "max_profit_total": float("inf"),
        "risk_note": "Unlimited downside; max loss = debit paid",
    }


def evaluate_broken_wing_butterfly(spot, wing1_c, body_c, wing2_c, kind):
    """Evaluate a broken wing butterfly: 3 strikes, one wing wider than other.
    kind in {"call_broken_wing", "put_broken_wing"}.
    Buy 1 wing1, Sell 2 body, Buy 1 wing2. The 'broken' wing (wing2) is
    further OTM, creating directional bias with reduced cost.
    Defined risk: max loss = net debit.
    """
    reasons = []
    exps = {wing1_c["expiration"], body_c["expiration"], wing2_c["expiration"]}
    if len(exps) > 1:
        reasons.append("legs on different expirations")
        return {"accepted": False, "reasons": reasons, "diagnostics": {}}
    # Validate ordering based on kind
    s1, s2, s3 = wing1_c["strike"], body_c["strike"], wing2_c["strike"]
    if kind == "call_broken_wing":
        # Call BWB: buy ITM call, sell 2 ATM, buy FAR OTM
        if not (s1 < s2 < s3):
            reasons.append("call BWB strikes not ascending")
        # Broken wing: s3-s2 > s2-s1 (upper wing wider)
        wing_width_low = s2 - s1
        wing_width_high = s3 - s2
    else:  # put_broken_wing
        # Put BWB: buy OTM put (high strike), sell 2 ATM, buy FAR OTM (low strike)
        # For puts: s1 > s2 > s3 (descending)
        if not (s1 > s2 > s3):
            reasons.append("put BWB strikes not descending")
        wing_width_low = s1 - s2
        wing_width_high = s2 - s3
    if reasons:
        return {"accepted": False, "reasons": reasons, "diagnostics": {}}
    # Net debit: buy wing1 + buy wing2 - 2*sell body
    debit = wing1_c["ask"] + wing2_c["ask"] - 2 * body_c["bid"]
    max_loss = debit * 100 if debit > 0 else 0
    # Max profit: at body strike = (s2-s1) - debit for call BWB
    if kind == "call_broken_wing":
        max_profit = (wing_width_low - debit) * 100 if debit < wing_width_low else 0
    else:
        max_profit = (wing_width_low - debit) * 100 if debit < wing_width_low else 0
    return {
        "accepted": True,
        "kind": kind,
        "expiration": wing1_c["expiration"],
        "dte": dte(wing1_c["expiration"]),
        "wing1_strike": s1,
        "body_strike": s2,
        "wing2_strike": s3,
        "wing_width_low": wing_width_low,
        "wing_width_high": wing_width_high,
        "credit_total": 0,
        "debit_total": debit * 100 if debit > 0 else 0,
        "max_loss_total": max_loss,
        "max_profit_total": max_profit,
        "risk_note": "Defined risk; broken wing creates directional bias",
    }


def evaluate_inverse_broken_wing(spot, wing1_c, body_c, wing2_c, kind):
    """Evaluate an inverse broken wing butterfly: sell wings, buy body.
    kind in {"inverse_call_broken_wing", "inverse_put_broken_wing"}.
    Sell 1 wing1, Buy 2 body, Sell 1 wing2. Net credit.
    Defined risk, profits from movement away from body.
    """
    reasons = []
    exps = {wing1_c["expiration"], body_c["expiration"], wing2_c["expiration"]}
    if len(exps) > 1:
        reasons.append("legs on different expirations")
        return {"accepted": False, "reasons": reasons, "diagnostics": {}}
    s1, s2, s3 = wing1_c["strike"], body_c["strike"], wing2_c["strike"]
    if "call" in kind:
        if not (s1 < s2 < s3):
            reasons.append("inverse call BWB strikes not ascending")
    else:
        if not (s1 > s2 > s3):
            reasons.append("inverse put BWB strikes not descending")
    if reasons:
        return {"accepted": False, "reasons": reasons, "diagnostics": {}}
    # Net credit: 2*buy body - sell wings
    # Actually inverse: sell wings, buy 2 body = credit if wings > body cost
    credit = wing1_c["bid"] + wing2_c["bid"] - 2 * body_c["ask"]
    # Max loss: width of narrow wing - credit
    wing_width = abs(s2 - s1)
    max_loss = (wing_width - credit) * 100 if credit < wing_width else 0
    return {
        "accepted": True,
        "kind": kind,
        "expiration": wing1_c["expiration"],
        "dte": dte(wing1_c["expiration"]),
        "wing1_strike": s1,
        "body_strike": s2,
        "wing2_strike": s3,
        "credit_total": credit * 100 if credit > 0 else 0,
        "debit_total": -credit * 100 if credit < 0 else 0,
        "max_loss_total": max_loss,
        "risk_note": "Defined risk; profits from large moves",
    }


def evaluate_call_ladder(spot, leg1_c, leg2_c, leg3_c, kind):
    """Evaluate a 3-leg call ladder.
    kind in {"bull_call_ladder", "bear_call_ladder"}.
    Bull Call Ladder: Buy 1 ITM call, Sell 1 ATM call, Sell 1 OTM call.
        Net credit, UNDEFINED RISK on upside (naked short OTM call).
    Bear Call Ladder: Sell 1 ITM call, Buy 1 ATM call, Buy 1 OTM call.
        Net debit, defined risk, profits from downside.
    """
    reasons = []
    exps = {leg1_c["expiration"], leg2_c["expiration"], leg3_c["expiration"]}
    if len(exps) > 1:
        reasons.append("legs on different expirations")
        return {"accepted": False, "reasons": reasons, "diagnostics": {}}
    s1, s2, s3 = leg1_c["strike"], leg2_c["strike"], leg3_c["strike"]
    if not (s1 < s2 < s3):
        reasons.append("ladder strikes not ascending")
    if reasons:
        return {"accepted": False, "reasons": reasons, "diagnostics": {}}
    if kind == "bull_call_ladder":
        # Buy ITM, Sell ATM, Sell OTM
        net = leg2_c["bid"] + leg3_c["bid"] - leg1_c["ask"]
        return {
            "accepted": True,
            "kind": kind,
            "expiration": leg1_c["expiration"],
            "dte": dte(leg1_c["expiration"]),
            "leg1_strike": s1, "leg2_strike": s2, "leg3_strike": s3,
            "credit_total": net * 100 if net > 0 else 0,
            "debit_total": -net * 100 if net < 0 else 0,
            "max_loss_total": float("inf"),
            "risk_note": "UNDEFINED RISK - naked short OTM call",
            "risk_warning": True,
        }
    else:  # bear_call_ladder
        # Sell ITM, Buy ATM, Buy OTM
        net = leg1_c["bid"] - leg2_c["ask"] - leg3_c["ask"]
        width = s2 - s1
        max_loss = (width - net) * 100 if net < width else 0
        return {
            "accepted": True,
            "kind": kind,
            "expiration": leg1_c["expiration"],
            "dte": dte(leg1_c["expiration"]),
            "leg1_strike": s1, "leg2_strike": s2, "leg3_strike": s3,
            "credit_total": net * 100 if net > 0 else 0,
            "debit_total": -net * 100 if net < 0 else 0,
            "max_loss_total": max_loss,
            "risk_note": "Defined risk; bearish ladder",
        }


def evaluate_put_ladder(spot, leg1_p, leg2_p, leg3_p, kind):
    """Evaluate a 3-leg put ladder.
    kind in {"bull_put_ladder", "bear_put_ladder"}.
    Bull Put Ladder: Sell 1 ITM put, Buy 1 ATM put, Buy 1 OTM put.
        Net debit, defined risk, profits from upside.
    Bear Put Ladder: Buy 1 ITM put, Sell 1 ATM put, Sell 1 OTM put.
        Net credit, UNDEFINED RISK on downside (naked short OTM put).
    """
    reasons = []
    exps = {leg1_p["expiration"], leg2_p["expiration"], leg3_p["expiration"]}
    if len(exps) > 1:
        reasons.append("legs on different expirations")
        return {"accepted": False, "reasons": reasons, "diagnostics": {}}
    s1, s2, s3 = leg1_p["strike"], leg2_p["strike"], leg3_p["strike"]
    if not (s1 > s2 > s3):
        reasons.append("ladder strikes not descending")
    if reasons:
        return {"accepted": False, "reasons": reasons, "diagnostics": {}}
    if kind == "bull_put_ladder":
        # Sell ITM, Buy ATM, Buy OTM
        net = leg1_p["bid"] - leg2_p["ask"] - leg3_p["ask"]
        width = s1 - s2
        max_loss = (width - net) * 100 if net < width else 0
        return {
            "accepted": True,
            "kind": kind,
            "expiration": leg1_p["expiration"],
            "dte": dte(leg1_p["expiration"]),
            "leg1_strike": s1, "leg2_strike": s2, "leg3_strike": s3,
            "credit_total": net * 100 if net > 0 else 0,
            "debit_total": -net * 100 if net < 0 else 0,
            "max_loss_total": max_loss,
            "risk_note": "Defined risk; bullish ladder",
        }
    else:  # bear_put_ladder
        # Buy ITM, Sell ATM, Sell OTM
        net = leg2_p["bid"] + leg3_p["bid"] - leg1_p["ask"]
        return {
            "accepted": True,
            "kind": kind,
            "expiration": leg1_p["expiration"],
            "dte": dte(leg1_p["expiration"]),
            "leg1_strike": s1, "leg2_strike": s2, "leg3_strike": s3,
            "credit_total": net * 100 if net > 0 else 0,
            "debit_total": -net * 100 if net < 0 else 0,
            "max_loss_total": float("inf"),
            "risk_note": "UNDEFINED RISK - naked short OTM put",
            "risk_warning": True,
        }


def evaluate_jade_lizard(spot, short_put_c, short_call_c, long_call_c):
    """Evaluate a proper Jade Lizard (TastyTrade definition):
    Sell 1 OTM put (NAKED) + Sell 1 OTM call spread (short call + long further OTM call).
    3 legs total. Net credit.
    UNDEFINED RISK on downside (naked short put).
    The 'no upside risk' property: if total credit >= call spread width,
    there is no upside loss.
    """
    reasons = []
    exps = {short_put_c["expiration"], short_call_c["expiration"], long_call_c["expiration"]}
    if len(exps) > 1:
        reasons.append("legs on different expirations")
        return {"accepted": False, "reasons": reasons, "diagnostics": {}}
    # Short put must be OTM (strike < spot)
    if short_put_c["strike"] >= spot:
        reasons.append("short put not OTM")
    # Call spread: short call OTM, long call further OTM
    if not (short_call_c["strike"] < long_call_c["strike"]):
        reasons.append("call spread strikes inverted")
    if short_call_c["strike"] <= spot:
        reasons.append("short call not OTM")
    if reasons:
        return {"accepted": False, "reasons": reasons, "diagnostics": {}}
    call_width = long_call_c["strike"] - short_call_c["strike"]
    total_credit = (short_put_c["bid"] + short_call_c["bid"] - long_call_c["ask"])
    # Upside: max loss = call_width - credit (if credit < width, else 0)
    upside_loss = max(0, (call_width - total_credit)) * 100
    no_upside_risk = total_credit >= call_width
    return {
        "accepted": True,
        "kind": "jade_lizard",
        "expiration": short_put_c["expiration"],
        "dte": dte(short_put_c["expiration"]),
        "short_put_strike": short_put_c["strike"],
        "short_call_strike": short_call_c["strike"],
        "long_call_strike": long_call_c["strike"],
        "call_spread_width": call_width,
        "credit_total": total_credit * 100 if total_credit > 0 else 0,
        "max_loss_total": float("inf"),
        "upside_max_loss": upside_loss,
        "no_upside_risk": no_upside_risk,
        "risk_note": "UNDEFINED RISK on downside (naked short put)",
        "risk_warning": True,
    }


def evaluate_reverse_jade_lizard(spot, short_call_c, short_put_c, long_put_c):
    """Evaluate a Reverse Jade Lizard:
    Sell 1 OTM call (NAKED) + Sell 1 OTM put spread (short put + long further OTM put).
    3 legs total. Net credit.
    UNDEFINED RISK on upside (naked short call).
    """
    reasons = []
    exps = {short_call_c["expiration"], short_put_c["expiration"], long_put_c["expiration"]}
    if len(exps) > 1:
        reasons.append("legs on different expirations")
        return {"accepted": False, "reasons": reasons, "diagnostics": {}}
    if short_call_c["strike"] <= spot:
        reasons.append("short call not OTM")
    if not (short_put_c["strike"] > long_put_c["strike"]):
        reasons.append("put spread strikes inverted")
    if short_put_c["strike"] >= spot:
        reasons.append("short put not OTM")
    if reasons:
        return {"accepted": False, "reasons": reasons, "diagnostics": {}}
    put_width = short_put_c["strike"] - long_put_c["strike"]
    total_credit = (short_call_c["bid"] + short_put_c["bid"] - long_put_c["ask"])
    downside_loss = max(0, (put_width - total_credit)) * 100
    no_downside_risk = total_credit >= put_width
    return {
        "accepted": True,
        "kind": "reverse_jade_lizard",
        "expiration": short_call_c["expiration"],
        "dte": dte(short_call_c["expiration"]),
        "short_call_strike": short_call_c["strike"],
        "short_put_strike": short_put_c["strike"],
        "long_put_strike": long_put_c["strike"],
        "put_spread_width": put_width,
        "credit_total": total_credit * 100 if total_credit > 0 else 0,
        "max_loss_total": float("inf"),
        "downside_max_loss": downside_loss,
        "no_downside_risk": no_downside_risk,
        "risk_note": "UNDEFINED RISK on upside (naked short call)",
        "risk_warning": True,
    }


def evaluate_synthetic_future(spot, call_c, put_c, kind):
    """Evaluate a synthetic stock position using options.
    kind in {"long_synthetic", "short_synthetic"}.
    Long Synthetic: Buy ATM call + Sell ATM put (same strike/expiry).
        Simulates long stock. Unlimited upside, large downside risk.
    Short Synthetic: Sell ATM call + Buy ATM put (same strike/expiry).
        Simulates short stock. Unlimited downside risk.
    """
    reasons = []
    if call_c["expiration"] != put_c["expiration"]:
        reasons.append("legs on different expirations")
        return {"accepted": False, "reasons": reasons, "diagnostics": {}}
    if call_c["strike"] != put_c["strike"]:
        reasons.append("legs on different strikes")
        return {"accepted": False, "reasons": reasons, "diagnostics": {}}
    if reasons:
        return {"accepted": False, "reasons": reasons, "diagnostics": {}}
    strike = call_c["strike"]
    if kind == "long_synthetic":
        # Buy call, Sell put
        net = put_c["bid"] - call_c["ask"]
        return {
            "accepted": True,
            "kind": kind,
            "expiration": call_c["expiration"],
            "dte": dte(call_c["expiration"]),
            "strike": strike,
            "credit_total": net * 100 if net > 0 else 0,
            "debit_total": -net * 100 if net < 0 else 0,
            "max_loss_total": float("inf"),
            "risk_note": "Synthetic long stock; large downside risk",
            "risk_warning": True,
        }
    else:  # short_synthetic
        # Sell call, Buy put
        net = call_c["bid"] - put_c["ask"]
        return {
            "accepted": True,
            "kind": kind,
            "expiration": call_c["expiration"],
            "dte": dte(call_c["expiration"]),
            "strike": strike,
            "credit_total": net * 100 if net > 0 else 0,
            "debit_total": -net * 100 if net < 0 else 0,
            "max_loss_total": float("inf"),
            "risk_note": "Synthetic short stock; unlimited upside risk",
            "risk_warning": True,
        }


def evaluate_combo(spot, long_c, short_c, kind):
    """Evaluate a combo (long/short) using different strikes.
    kind in {"long_combo", "short_combo"}.
    Long Combo: Buy OTM call + Sell OTM put (bullish, net debit/credit).
    Short Combo: Sell OTM call + Buy OTM put (bearish, net debit/credit).
    Similar to synthetic but with different strikes (risk reversal).
    """
    reasons = []
    if long_c["expiration"] != short_c["expiration"]:
        reasons.append("legs on different expirations")
        return {"accepted": False, "reasons": reasons, "diagnostics": {}}
    if reasons:
        return {"accepted": False, "reasons": reasons, "diagnostics": {}}
    if kind == "long_combo":
        # Buy call (higher strike), Sell put (lower strike)
        if not (long_c["strike"] > short_c["strike"]):
            reasons.append("long combo strikes not ordered")
            return {"accepted": False, "reasons": reasons, "diagnostics": {}}
        net = short_c["bid"] - long_c["ask"]
    else:  # short_combo
        # Sell call (higher strike), Buy put (lower strike)
        # long_c is the put, short_c is the call in this case
        if not (short_c["strike"] > long_c["strike"]):
            reasons.append("short combo strikes not ordered")
            return {"accepted": False, "reasons": reasons, "diagnostics": {}}
        net = short_c["bid"] - long_c["ask"]
    return {
        "accepted": True,
        "kind": kind,
        "expiration": long_c["expiration"],
        "dte": dte(long_c["expiration"]),
        "long_strike": long_c["strike"],
        "short_strike": short_c["strike"],
        "credit_total": net * 100 if net > 0 else 0,
        "debit_total": -net * 100 if net < 0 else 0,
        "max_loss_total": float("inf"),
        "risk_note": f"{'Bullish' if kind=='long_combo' else 'Bearish'} risk reversal",
        "risk_warning": True,
    }


def evaluate_strip_strap(spot, leg1_c, leg2_c, leg3_c, kind):
    """Evaluate Strip/Strap: 3-leg volatility structures.
    kind in {"strip", "strap"}.
    Strip: Buy 2 ATM puts + Buy 1 ATM call (bearish bias).
    Strap: Buy 2 ATM calls + Buy 1 ATM put (bullish bias).
    Net debit. Unlimited profit potential both directions.
    """
    reasons = []
    exps = {leg1_c["expiration"], leg2_c["expiration"], leg3_c["expiration"]}
    if len(exps) > 1:
        reasons.append("legs on different expirations")
        return {"accepted": False, "reasons": reasons, "diagnostics": {}}
    if reasons:
        return {"accepted": False, "reasons": reasons, "diagnostics": {}}
    # All legs same strike (ATM)
    strike = leg1_c["strike"]
    # Debit: sum of all asks
    debit = leg1_c["ask"] + leg2_c["ask"] + leg3_c["ask"]
    return {
        "accepted": True,
        "kind": kind,
        "expiration": leg1_c["expiration"],
        "dte": dte(leg1_c["expiration"]),
        "strike": strike,
        "credit_total": 0,
        "debit_total": debit * 100,
        "max_loss_total": debit * 100,
        "max_profit_total": float("inf"),
        "risk_note": f"{'Bearish' if kind=='strip' else 'Bullish'} bias; long volatility",
    }


def evaluate_guts(spot, call_c, put_c, kind):
    """Evaluate Guts: ITM call + ITM put (same expiry).
    kind in {"long_guts", "short_guts"}.
    Long Guts: Buy ITM call + Buy ITM put. Net debit, long volatility.
    Short Guts: Sell ITM call + Sell ITM put. Net credit, UNDEFINED RISK.
    Similar to strangle but with ITM options (higher delta).
    """
    reasons = []
    if call_c["expiration"] != put_c["expiration"]:
        reasons.append("legs on different expirations")
        return {"accepted": False, "reasons": reasons, "diagnostics": {}}
    # Both should be ITM: call strike < spot, put strike > spot
    if not (call_c["strike"] < spot < put_c["strike"]):
        reasons.append("legs not ITM for guts")
        return {"accepted": False, "reasons": reasons, "diagnostics": {}}
    if reasons:
        return {"accepted": False, "reasons": reasons, "diagnostics": {}}
    if kind == "long_guts":
        debit = call_c["ask"] + put_c["ask"]
        return {
            "accepted": True,
            "kind": kind,
            "expiration": call_c["expiration"],
            "dte": dte(call_c["expiration"]),
            "call_strike": call_c["strike"],
            "put_strike": put_c["strike"],
            "credit_total": 0,
            "debit_total": debit * 100,
            "max_loss_total": debit * 100,
            "max_profit_total": float("inf"),
            "risk_note": "Long volatility; ITM guts",
        }
    else:  # short_guts
        credit = call_c["bid"] + put_c["bid"]
        return {
            "accepted": True,
            "kind": kind,
            "expiration": call_c["expiration"],
            "dte": dte(call_c["expiration"]),
            "call_strike": call_c["strike"],
            "put_strike": put_c["strike"],
            "credit_total": credit * 100,
            "debit_total": 0,
            "max_loss_total": float("inf"),
            "risk_note": "UNDEFINED RISK - short ITM strangle",
            "risk_warning": True,
        }


def evaluate_double_diagonal(spot, near_call_c, far_call_c, near_put_c, far_put_c):
    """Evaluate a Double Diagonal: call diagonal + put diagonal.
    Call diagonal: Sell near-term OTM call, Buy far-term OTM call.
    Put diagonal: Sell near-term OTM put, Buy far-term OTM put.
    4 legs, 2 expirations. Net debit (typically).
    Defined risk, profits from time decay and volatility expansion.
    """
    reasons = []
    # Call diagonal: different expirations
    if near_call_c["expiration"] == far_call_c["expiration"]:
        reasons.append("call diagonal needs different expirations")
    # Put diagonal: different expirations
    if near_put_c["expiration"] == far_put_c["expiration"]:
        reasons.append("put diagonal needs different expirations")
    # Near and far should share the same near/far expirations
    if near_call_c["expiration"] != near_put_c["expiration"]:
        reasons.append("near legs on different expirations")
    if far_call_c["expiration"] != far_put_c["expiration"]:
        reasons.append("far legs on different expirations")
    if reasons:
        return {"accepted": False, "reasons": reasons, "diagnostics": {}}
    # Net: sell near (credit), buy far (debit)
    call_net = near_call_c["bid"] - far_call_c["ask"]
    put_net = near_put_c["bid"] - far_put_c["ask"]
    total_net = call_net + put_net
    # Max loss: net debit paid (if debit) or width-based
    # Simplified: max loss = debit if net debit, else undefined-ish
    # For double diagonal, max loss is typically the net debit
    max_loss = -total_net * 100 if total_net < 0 else 0
    return {
        "accepted": True,
        "kind": "double_diagonal",
        "near_expiration": near_call_c["expiration"],
        "far_expiration": far_call_c["expiration"],
        "near_dte": dte(near_call_c["expiration"]),
        "far_dte": dte(far_call_c["expiration"]),
        "call_short_strike": near_call_c["strike"],
        "call_long_strike": far_call_c["strike"],
        "put_short_strike": near_put_c["strike"],
        "put_long_strike": far_put_c["strike"],
        "credit_total": total_net * 100 if total_net > 0 else 0,
        "debit_total": -total_net * 100 if total_net < 0 else 0,
        "max_loss_total": max_loss,
        "risk_note": "Defined risk; long vega, short near-term theta",
    }


