"""Replay the configured bull-put exit policy on supplied historical marks.

This is a local, mark-based research tool. It does not fetch historical data,
infer fills, or place orders. Each position must provide its costs and
timestamped underlying/option observations.
"""
import argparse
import json
import math
import re
from datetime import date, datetime, timezone

import gates
from exits import evaluate

OSI_RE = re.compile(r"^(.+?)(\d{6})([CP])(\d{8})$")


def _utc(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} timestamp is required")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{name} timestamp is invalid") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{name} timestamp must include UTC offset")
    return parsed.astimezone(timezone.utc)


def _number(value, name, minimum=0.0, strictly_positive=False):
    if isinstance(value, bool):
        raise ValueError(f"{name} must be numeric")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be numeric") from exc
    if not math.isfinite(number) or number < minimum:
        raise ValueError(f"{name} must be finite and >= {minimum}")
    if strictly_positive and number <= 0:
        raise ValueError(f"{name} must be positive")
    return number


def _positive_int(value, name):
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a positive integer")
    number = _number(value, name, strictly_positive=True)
    if not number.is_integer():
        raise ValueError(f"{name} must be a positive integer")
    return int(number)


def _bull_put(position):
    legs = position.get("legs")
    if not isinstance(legs, list) or len(legs) != 2:
        raise ValueError("bull-put position must have exactly two legs")
    short = [leg for leg in legs if isinstance(leg, dict)
             and str(leg.get("side", "")).lower() == "short"
             and str(leg.get("type", "")).lower() == "put"]
    long = [leg for leg in legs if isinstance(leg, dict)
            and str(leg.get("side", "")).lower() == "long"
            and str(leg.get("type", "")).lower() == "put"]
    if len(short) != 1 or len(long) != 1:
        raise ValueError("position must be one short put and one long put")
    short_strike = _number(short[0].get("strike"), "short strike", strictly_positive=True)
    long_strike = _number(long[0].get("strike"), "long strike", strictly_positive=True)
    if short_strike <= long_strike:
        raise ValueError("short put strike must be above long put strike")
    try:
        expiry = date.fromisoformat(short[0]["expiry"])
        long_expiry = date.fromisoformat(long[0]["expiry"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("both put legs need a valid YYYY-MM-DD expiry") from exc
    if expiry != long_expiry:
        raise ValueError("bull-put legs must share an expiration")
    for leg, expected_strike in ((short[0], short_strike), (long[0], long_strike)):
        osi = leg.get("osi")
        match = OSI_RE.fullmatch(osi) if isinstance(osi, str) else None
        if not match:
            raise ValueError("both legs require exact OSI contract identifiers")
        yy, mm, dd = int(match.group(2)[:2]), int(match.group(2)[2:4]), int(match.group(2)[4:6])
        try:
            osi_expiry = date(2000 + yy, mm, dd)
        except ValueError as exc:
            raise ValueError(f"{osi} has an invalid OSI expiration") from exc
        osi_strike = int(match.group(4)) / 1000.0
        if (match.group(3) != "P" or osi_expiry != expiry
                or abs(osi_strike - expected_strike) > 0.0005):
            raise ValueError(f"{osi} does not match put type, strike, and expiration")
    return short_strike, expiry


def _score_position(position, policy, max_quote_lag_minutes, max_gap_hours):
    position_id = position.get("id")
    result = {"position_id": position_id, "status": "INCOMPLETE",
              "action": None, "entry_credit": None, "close_cost": None,
              "gross_pnl": None, "costs": None, "net_pnl": None,
              "exit_asof": None, "observations_used": 0, "data_gap": None,
              "assignment_uncertainty": None}
    try:
        if position.get("strategy") != "bull_put_spread":
            raise ValueError("only bull_put_spread is supported")
        short_strike, expiry = _bull_put(position)
        entry_credit = _number(position.get("entry_credit"), "entry_credit",
                               strictly_positive=True)
        contracts = _positive_int(position.get("contracts"), "contracts")
        multiplier = _positive_int(position.get("multiplier"), "multiplier")
        fees = _number(position.get("fees_per_contract_round_trip"),
                       "fees_per_contract_round_trip")
        slippage = _number(position.get("slippage_per_contract_round_trip"),
                           "slippage_per_contract_round_trip")
        entry_asof = _utc(position.get("entry_asof"), "entry_asof")
        observations = position.get("observations")
        if not isinstance(observations, list) or not observations:
            raise ValueError("observations must be a non-empty list")
        result["entry_credit"] = entry_credit
        result["entry_asof"] = entry_asof.isoformat().replace("+00:00", "Z")
        result["assignment_uncertainty"] = "actual early assignment is not modeled"
    except (TypeError, ValueError, OverflowError) as exc:
        result.update(status="INVALID", data_gap=str(exc))
        return result

    previous = entry_asof
    for index, observation in enumerate(observations):
        try:
            if not isinstance(observation, dict):
                raise ValueError("observation must be an object")
            observed = _utc(observation.get("asof"), "observation")
            if observed <= previous:
                raise ValueError("observations must be strictly chronological after entry")
            if (observed - previous).total_seconds() > max_gap_hours * 3600:
                raise ValueError("observation gap exceeds configured maximum")
            quote_times = [_utc(observation.get(key), key) for key in
                           ("short_quote_asof", "long_quote_asof", "underlying_asof")]
            if any(t > observed or (observed - t).total_seconds() > max_quote_lag_minutes * 60
                   for t in quote_times):
                raise ValueError("one or more source quotes are future-dated or stale")
            if not isinstance(observation.get("source"), str) or not observation["source"].strip():
                raise ValueError("observation source is required")
            short_ask = _number(observation.get("short_ask"), "short_ask")
            long_bid = _number(observation.get("long_bid"), "long_bid")
            spot = _number(observation.get("underlying"), "underlying", strictly_positive=True)
            close_cost = short_ask - long_bid
            if close_cost < 0:
                raise ValueError("short ask less long bid produced a negative close cost")
            dte = (expiry - observed.date()).days
            if dte < 0:
                raise ValueError("observation is after expiration")
            short_itm = spot < short_strike
            action, reason = evaluate(entry_credit, close_cost, dte,
                                      short_itm=short_itm, cfg=policy)
            result["observations_used"] = index + 1
            previous = observed
            if action == "HOLD":
                continue

            gross = (entry_credit - close_cost) * contracts * multiplier
            costs = (fees + slippage) * contracts
            result.update(status="SCORED", action=action, reason=reason,
                          close_cost=round(close_cost, 6),
                          exit_asof=observed.isoformat().replace("+00:00", "Z"),
                          dte=dte, short_itm=short_itm,
                          gross_pnl=round(gross, 2), costs=round(costs, 2),
                          net_pnl=round(gross - costs, 2),
                          cost_assumption="close at observed short ask minus long bid; subtract supplied fees and slippage")
            return result
        except (TypeError, ValueError, OverflowError) as exc:
            result["data_gap"] = f"observation {index + 1}: {exc}"
            return result

    result["data_gap"] = "no exit trigger in supplied observations; outcome is unresolved"
    return result


def _max_drawdown(scored):
    equity = peak = drawdown = 0.0
    for row in sorted(scored, key=lambda item: item["exit_asof"]):
        equity += row["net_pnl"]
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)
    return round(drawdown, 2)


def evaluate_dataset(dataset, exit_config=None, max_quote_lag_minutes=5.0,
                     max_gap_hours=72.0):
    """Replay observed paths and report coverage plus realized mark-based results."""
    if (not isinstance(dataset, dict) or isinstance(dataset.get("schema_version"), bool)
            or dataset.get("schema_version") != 1):
        raise ValueError("dataset schema_version must be 1")
    if not isinstance(dataset.get("source"), str) or not dataset["source"].strip():
        raise ValueError("dataset source provenance is required")
    positions = dataset.get("positions")
    if not isinstance(positions, list):
        raise ValueError("dataset positions must be a list")
    if (not math.isfinite(max_quote_lag_minutes) or max_quote_lag_minutes <= 0
            or not math.isfinite(max_gap_hours) or max_gap_hours <= 0):
        raise ValueError("quote lag and observation gap limits must be positive")
    policy = exit_config or gates.load().get("exits", {}).get("bull_put_spread", {})
    rows = [_score_position(p, policy, max_quote_lag_minutes, max_gap_hours)
            if isinstance(p, dict) else {"position_id": None, "status": "INVALID",
                                         "data_gap": "position must be an object"}
            for p in positions]
    scored = [row for row in rows if row["status"] == "SCORED"]
    net = [row["net_pnl"] for row in scored]
    actions = ("TAKE_PROFIT", "STOP_LOSS", "TIME_EXIT", "EXPIRATION_RISK")
    by_action = {}
    for action in actions:
        results = [row["net_pnl"] for row in scored if row["action"] == action]
        by_action[action] = {
            "count": len(results),
            "net_pnl": round(sum(results), 2) if results else None,
            "average_net_pnl": round(sum(results) / len(results), 2) if results else None,
            "win_rate": round(sum(value > 0 for value in results) / len(results), 4)
                        if results else None,
        }
    return {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "dataset_source": dataset.get("source"),
        "policy": {"strategy": "bull_put_spread", "rules": policy},
        "assumptions": [
            "This is a historical mark replay, not a broker fill or backtest of executable trades.",
            "Exit costs use the observed short-leg ask minus long-leg bid plus supplied fees and slippage.",
            "Only observations available at or before each decision timestamp are considered.",
            "Paths with missing/stale observations, excessive gaps, or no observed policy trigger are unresolved and excluded from P&L summaries.",
            "Assignment uncertainty is not modeled; the configured expiration-risk rule is only a policy signal, not an observed assignment outcome.",
            "Realized mark-to-mark P&L drawdown omits unrealized exposure and capital allocation; it is not portfolio drawdown.",
            "Historical results do not establish future profitability.",
        ],
        "limits": {"max_quote_lag_minutes": max_quote_lag_minutes,
                   "max_gap_hours": max_gap_hours},
        "coverage": {"positions": len(rows), "scored": len(scored),
                     "incomplete": sum(row["status"] == "INCOMPLETE" for row in rows),
                     "invalid": sum(row["status"] == "INVALID" for row in rows),
                     "scored_fraction": round(len(scored) / len(rows), 4) if rows else 0.0,
                     "assignment_uncertainty_positions": sum(
                         row["status"] != "INVALID" for row in rows)},
        "summary": {"net_pnl": round(sum(net), 2) if net else None,
                    "average_net_pnl": round(sum(net) / len(net), 2) if net else None,
                    "win_rate": round(sum(value > 0 for value in net) / len(net), 4) if net else None,
                    "worst_trade": round(min(net), 2) if net else None,
                    "realized_mark_pnl_max_drawdown": _max_drawdown(scored) if scored else None},
        "comparison_baseline": {
            "status": "NOT_COMPUTED",
            "reason": "The input schema does not include an independent hold-to-expiration settlement or fill path.",
        },
        "action_counts": {action: sum(row.get("action") == action for row in rows)
                          for action in actions},
        "by_action": by_action,
        "positions": rows,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, help="local historical mark dataset JSON")
    parser.add_argument("--out", required=True, help="local JSON report path")
    parser.add_argument("--max-quote-lag-minutes", type=float, default=5.0)
    parser.add_argument("--max-gap-hours", type=float, default=72.0)
    parser.add_argument("--config", help="optional gates.yaml path")
    args = parser.parse_args()
    with open(args.input, encoding="utf-8") as handle:
        dataset = json.load(handle)
    config = gates.load(args.config)["exits"]["bull_put_spread"]
    report = evaluate_dataset(dataset, config, args.max_quote_lag_minutes,
                              args.max_gap_hours)
    with open(args.out, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2)
        handle.write("\n")
    print(json.dumps({"coverage": report["coverage"], "summary": report["summary"],
                      "out": args.out}, indent=2))


if __name__ == "__main__":
    main()
