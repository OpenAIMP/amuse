"""Evaluation helpers for calendars, diagonals, and paired multi-expiry spreads."""

from itertools import combinations


def evaluate_calendar(spot, short_leg, long_leg, option_type, structure,
                     max_friction=3.0, max_loss=1000.0):
    """Evaluate a near-expiry short and farther-expiry long option."""
    reasons = []
    if short_leg["expiration"] == long_leg["expiration"]:
        reasons.append("legs must have different expirations")
    elif short_leg["expiration"] > long_leg["expiration"]:
        reasons.append("short leg must expire before long leg")
    if option_type not in ("call", "put"):
        reasons.append("invalid option type")
    same_strike = short_leg["strike"] == long_leg["strike"]
    if structure.endswith("calendar") and not same_strike:
        reasons.append("calendar legs must use the same strike")
    if structure.endswith("diagonal") and same_strike:
        reasons.append("diagonal legs must use different strikes")

    required = ("delta", "iv")
    if any(any(leg.get(key) is None for key in required)
           for leg in (short_leg, long_leg)):
        reasons.append("missing Greeks")

    debit = long_leg["ask"] - short_leg["bid"]
    if debit == 0:
        reasons.append("zero net debit or credit")
    spread_cost = short_leg["spread"] + long_leg["spread"]
    friction = spread_cost / abs(debit) if debit else None
    if reasons:
        return {"accepted": False, "reasons": reasons,
                "diagnostics": {"net_debit_per_share": debit,
                                "friction": friction}}
    debit_total = max(0.0, debit) * 100
    credit_total = max(0.0, -debit) * 100
    risk = debit_total if debit > 0 else None
    if friction is not None and friction > max_friction:
        return {"accepted": False,
                "reasons": ["execution friction over limit"],
                "diagnostics": {"friction": friction}}
    if risk is not None and risk > max_loss:
        return {"accepted": False, "reasons": ["max loss over limit"],
                "diagnostics": {"max_loss": risk}}
    return {
        "accepted": True,
        "kind": structure,
        "option_type": option_type,
        "expiration": short_leg["expiration"],
        "long_expiration": long_leg["expiration"],
        "dte": short_leg.get("dte"),
        "long_dte": long_leg.get("dte"),
        "short_strike": short_leg["strike"],
        "long_strike": long_leg["strike"],
        "net_debit_total": debit_total,
        "net_credit_total": credit_total,
        "net_cashflow_total": credit_total - debit_total,
        "max_loss_total": risk,
        "max_loss_status": (
            "debit at risk through near expiration; interim mark-to-market "
            "and early-assignment loss is scenario-dependent"
            if risk is not None else
            "undefined / scenario-dependent; no finite maximum-loss estimate"),
        "breakeven_estimates": None,
        "breakeven_note": "not estimated: near-expiry value of the back-month option is unknown",
        "net_delta": long_leg["delta"] - short_leg["delta"],
        "net_theta": _net_metric(long_leg, short_leg, "theta"),
        "net_vega": _net_metric(long_leg, short_leg, "vega"),
        "term_structure_iv_change": long_leg["iv"] - short_leg["iv"],
        "friction": friction,
        "expected_value": None,
        "expected_value_note": "not estimated: no calibrated multi-expiry payoff probability model",
        "legs": [_leg_record(short_leg, "sell", option_type),
                 _leg_record(long_leg, "buy", option_type)],
        "ranking_score": (
            (long_leg["iv"] - short_leg["iv"])
            - (friction or 0) * 0.01
        ),
    }


def screen_multi_expiry(spot, expirations, puts_by_exp, calls_by_exp,
                        event_checker, max_friction=3.0, max_loss=1000.0):
    """Build and qualify multi-expiry structures from already-gated chains."""
    accepted = {
        "calendars": [], "diagonals": [],
        "double_calendars": [], "double_diagonals": [],
    }
    considered = []
    singles = {"put_calendar": [], "call_calendar": [],
               "put_diagonal": [], "call_diagonal": []}

    def consider(result, structure, front, back, legs):
        flags, event_reasons = [], []
        for expiration in (front, back):
            f, r = event_checker(expiration)
            flags.extend(f)
            event_reasons.extend(r)
        flags = list(dict.fromkeys(flags))
        reasons = result.get("reasons", []) + list(dict.fromkeys(event_reasons))
        details = {
            "structure": structure, "expiration": front,
            "long_expiration": back, "legs": legs,
            "qualification": "rejected" if reasons else "accepted",
            "reasons": reasons,
            "diagnostics": result.get("diagnostics", {}),
        }
        considered.append(details)
        if reasons or not result.get("accepted"):
            return None
        result.update({"events": flags})
        return result

    for front, back in combinations(sorted(expirations), 2):
        for option_type, chains in (("put", puts_by_exp),
                                    ("call", calls_by_exp)):
            front_chain = chains.get(front, {})
            back_chain = chains.get(back, {})
            common = sorted(set(c["strike"] for c in front_chain.values())
                            & set(c["strike"] for c in back_chain.values()))
            for strike in common:
                if abs(strike - spot) > spot * 0.10:
                    continue
                short_leg = _at_strike(front_chain, strike)
                long_leg = _at_strike(back_chain, strike)
                structure = f"{option_type}_calendar"
                result = evaluate_calendar(
                    spot, short_leg, long_leg, option_type, structure,
                    max_friction, max_loss)
                result = consider(result, structure, front, back,
                                  [short_leg, long_leg])
                if result:
                    singles[structure].append(result)

            if option_type == "call":
                shorts = [c for c in front_chain.values()
                          if spot < c["strike"] <= spot * 1.10]
                longs = [c for c in back_chain.values()
                         if spot * 0.90 <= c["strike"] <= spot]
                valid_pairs = ((short, long) for short in shorts for long in longs
                               if long["strike"] < short["strike"])
            else:
                shorts = [c for c in front_chain.values()
                          if spot * 0.90 <= c["strike"] < spot]
                longs = [c for c in back_chain.values()
                         if spot <= c["strike"] <= spot * 1.10]
                valid_pairs = ((short, long) for short in shorts for long in longs
                               if long["strike"] > short["strike"])
            structure = f"{option_type}_diagonal"
            for short_leg, long_leg in valid_pairs:
                result = evaluate_calendar(
                    spot, short_leg, long_leg, option_type, structure,
                    max_friction, max_loss)
                result = consider(result, structure, front, back,
                                  [short_leg, long_leg])
                if result:
                    singles[structure].append(result)

    accepted["calendars"] = singles["put_calendar"] + singles["call_calendar"]
    accepted["diagonals"] = singles["put_diagonal"] + singles["call_diagonal"]
    for structure, kind in (("double_calendars", "calendar"),
                            ("double_diagonals", "diagonal")):
        put_key, call_key = f"put_{kind}", f"call_{kind}"
        for put_spread in singles[put_key]:
            for call_spread in singles[call_key]:
                if (put_spread["expiration"] != call_spread["expiration"]
                        or put_spread["long_expiration"]
                        != call_spread["long_expiration"]
                        or put_spread["short_strike"]
                        >= call_spread["short_strike"]):
                    continue
                result = combine_calendars(
                    put_spread, call_spread, structure,
                    max_friction, max_loss)
                result = consider(
                    result, structure, put_spread["expiration"],
                    put_spread["long_expiration"],
                    put_spread["legs"] + call_spread["legs"])
                if result:
                    accepted[structure].append(result)
    for results in accepted.values():
        results.sort(key=lambda item: (
            -item["ranking_score"], item["friction"]))
    return accepted, considered


def combine_calendars(put_spread, call_spread, structure, max_friction=3.0,
                      max_loss=1000.0):
    """Combine accepted put and call calendars/diagonals."""
    reasons = []
    if put_spread["expiration"] != call_spread["expiration"]:
        reasons.append("front expirations differ")
    if put_spread["long_expiration"] != call_spread["long_expiration"]:
        reasons.append("back expirations differ")
    if put_spread["option_type"] != "put" or call_spread["option_type"] != "call":
        reasons.append("double structure requires one put and one call")
    if reasons:
        return {"accepted": False, "reasons": reasons, "diagnostics": {}}

    debit = put_spread["net_debit_total"] - put_spread["net_credit_total"]
    debit += call_spread["net_debit_total"] - call_spread["net_credit_total"]
    spread_cost = sum(
        (leg["ask"] - leg["bid"])
        for leg in put_spread["legs"] + call_spread["legs"])
    friction = spread_cost / abs(debit) if debit else None
    if debit == 0:
        return {"accepted": False, "reasons": ["zero net debit or credit"],
                "diagnostics": {"friction": None}}
    if friction > max_friction:
        return {"accepted": False,
                "reasons": ["execution friction over limit"],
                "diagnostics": {"friction": friction}}

    put_iv = put_spread["term_structure_iv_change"]
    call_iv = call_spread["term_structure_iv_change"]
    risk = debit if debit > 0 else None
    if risk is not None and risk > max_loss:
        return {"accepted": False, "reasons": ["max loss over limit"],
                "diagnostics": {"max_loss": risk}}
    return {
        "accepted": True,
        "kind": structure,
        "expiration": put_spread["expiration"],
        "long_expiration": put_spread["long_expiration"],
        "dte": put_spread.get("dte"),
        "long_dte": put_spread.get("long_dte"),
        "net_debit_total": max(0.0, debit),
        "net_credit_total": max(0.0, -debit),
        "net_cashflow_total": -debit,
        "max_loss_total": risk,
        "max_loss_status": (
            "net debit at risk through near expiration; interim mark-to-market "
            "and early-assignment loss is scenario-dependent"
            if risk is not None else
            "undefined / scenario-dependent; no finite maximum-loss estimate"),
        "breakeven_estimates": None,
        "breakeven_note": "not estimated: near-expiry value of the back-month options is unknown",
        "net_delta": _sum_metric(put_spread, call_spread, "net_delta"),
        "net_theta": _sum_metric(put_spread, call_spread, "net_theta"),
        "net_vega": _sum_metric(put_spread, call_spread, "net_vega"),
        "term_structure_iv_change": (put_iv + call_iv) / 2,
        "friction": friction,
        "expected_value": None,
        "expected_value_note": "not estimated: no calibrated multi-expiry payoff probability model",
        "legs": put_spread["legs"] + call_spread["legs"],
        "ranking_score": (put_spread["ranking_score"]
                          + call_spread["ranking_score"]) / 2,
    }


def _leg_record(contract, action, option_type):
    return {key: contract.get(key) for key in
            ("sym", "expiration", "strike", "bid", "ask", "spread",
             "delta", "theta", "vega", "iv", "open_interest", "volume")} | {
                 "action": action, "option_type": option_type}


def _at_strike(chain, strike):
    return next(contract for contract in chain.values()
                if contract["strike"] == strike)


def _net_metric(long_leg, short_leg, key):
    if long_leg.get(key) is None or short_leg.get(key) is None:
        return None
    return long_leg[key] - short_leg[key]


def _sum_metric(first, second, key):
    if first.get(key) is None or second.get(key) is None:
        return None
    return first[key] + second[key]
