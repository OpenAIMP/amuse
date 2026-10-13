"""Apply the configured bull-put exit policy to fresh, explicit position marks.

This is a local review aid. It never sends orders and does not publish position
data. The mark file must contain current, timestamped buy-to-close marks.
"""
import argparse
import json
import math
from datetime import date, datetime, timezone

import gates
from exits import evaluate


def _utc(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("timestamp is required")
    parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp must include a UTC offset")
    return parsed.astimezone(timezone.utc)


def _number(value, field, minimum=0):
    if isinstance(value, bool):
        raise ValueError(f"{field} must be numeric")
    try:
        result = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{field} must be numeric")
    if not math.isfinite(result) or result < minimum:
        raise ValueError(f"{field} must be finite and >= {minimum}")
    return result


def _validate_bull_put(legs, asof_date):
    if not isinstance(legs, list) or len(legs) != 2:
        raise ValueError("bull-put position must contain exactly two legs")
    short_puts = [leg for leg in legs if isinstance(leg, dict)
                  and str(leg.get("side", "")).lower() == "short"
                  and str(leg.get("type", "")).lower() == "put"]
    long_puts = [leg for leg in legs if isinstance(leg, dict)
                 and str(leg.get("side", "")).lower() == "long"
                 and str(leg.get("type", "")).lower() == "put"]
    if len(short_puts) != 1 or len(long_puts) != 1:
        raise ValueError("position legs are not one short put and one long put")
    short_strike = _number(short_puts[0].get("strike"), "short put strike", minimum=0.0000001)
    long_strike = _number(long_puts[0].get("strike"), "long put strike", minimum=0.0000001)
    if short_strike <= long_strike:
        raise ValueError("short put strike must be above long put strike")
    try:
        short_expiry = date.fromisoformat(short_puts[0]["expiry"])
        long_expiry = date.fromisoformat(long_puts[0]["expiry"])
    except (KeyError, TypeError, ValueError):
        raise ValueError("both put legs need a valid YYYY-MM-DD expiry")
    if short_expiry != long_expiry:
        raise ValueError("bull-put legs must share an expiration")
    dte = (short_expiry - asof_date).days
    if dte < 0:
        raise ValueError("position expiration is in the past")
    return dte


def evaluate_positions(ledger, snapshot, max_age_minutes=30, now=None,
                       exit_config=None):
    """Return exit recommendations and explicit coverage for an open ledger.

    Snapshot schema: ``schema_version=1``, ``source``, UTC ``asof`` and a
    ``positions`` map keyed by ledger position ID. Each mark has ``close_cost``
    (the ask to buy back the full spread), a DTE value, boolean ``short_itm``,
    and its own UTC ``asof`` timestamp. DTE is derived from the ledger expiry
    and cross-checked against the supplied value.
    """
    if isinstance(max_age_minutes, bool):
        raise ValueError("max_age_minutes must be positive")
    try:
        max_age_minutes = float(max_age_minutes)
    except (TypeError, ValueError):
        raise ValueError("max_age_minutes must be positive")
    if not math.isfinite(max_age_minutes) or max_age_minutes <= 0:
        raise ValueError("max_age_minutes must be positive")
    if not isinstance(ledger, dict) or not isinstance(ledger.get("positions"), list):
        raise ValueError("ledger must contain a positions list")
    if any(not isinstance(pos, dict) for pos in ledger["positions"]):
        raise ValueError("each ledger position must be an object")
    if any(pos.get("status") == "open" and not pos.get("id")
           for pos in ledger["positions"]):
        raise ValueError("each open ledger position must have an ID")
    now = _utc(now) if isinstance(now, str) else (now or datetime.now(timezone.utc))
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    now = now.astimezone(timezone.utc)

    global_errors = []
    schema_version = snapshot.get("schema_version") if isinstance(snapshot, dict) else None
    if isinstance(schema_version, bool) or schema_version != 1:
        global_errors.append("snapshot schema_version must be 1")
    source = snapshot.get("source") if isinstance(snapshot, dict) else None
    if not isinstance(source, str) or not source.strip():
        global_errors.append("snapshot source is required")
    try:
        snapshot_asof = _utc(snapshot.get("asof"))
        snapshot_age = (now - snapshot_asof).total_seconds()
        if snapshot_age < -60 or snapshot_age > max_age_minutes * 60:
            global_errors.append("snapshot timestamp is future-dated or stale")
    except (TypeError, ValueError, AttributeError):
        snapshot_asof = None
        global_errors.append("snapshot asof is missing or invalid")

    marks = snapshot.get("positions", {}) if isinstance(snapshot, dict) else {}
    if not isinstance(marks, dict):
        marks = {}
        global_errors.append("positions must be a position-ID-to-mark object")

    policy = exit_config or gates.load().get("exits", {}).get("bull_put_spread", {})
    output, totals = [], {"HOLD": 0, "TAKE_PROFIT": 0, "STOP_LOSS": 0,
                         "TIME_EXIT": 0, "EXPIRATION_RISK": 0,
                         "UNAVAILABLE": 0, "NOT_SUPPORTED": 0}
    open_positions = [p for p in ledger["positions"]
                      if isinstance(p, dict) and p.get("status") == "open"]
    supported_positions = [p for p in open_positions
                           if p.get("strategy") == "bull_put_spread"]
    fresh_count = 0

    for pos in open_positions:
        result = {"position_id": pos.get("id"), "underlying": pos.get("underlying"),
                  "strategy": pos.get("strategy"), "action": "UNAVAILABLE",
                  "reason": None, "mark_asof": None, "close_cost": None}
        if pos.get("strategy") != "bull_put_spread":
            result.update(action="NOT_SUPPORTED",
                          reason="this policy currently supports bull_put_spread only")
        elif global_errors:
            result["reason"] = "; ".join(global_errors)
        else:
            mark = marks.get(str(pos.get("id")))
            if not isinstance(mark, dict):
                result["reason"] = "no mark supplied for this open position"
            else:
                try:
                    mark_asof = _utc(mark.get("asof"))
                    age = (now - mark_asof).total_seconds()
                    if age < -60 or age > max_age_minutes * 60:
                        raise ValueError("position mark is future-dated or stale")
                    if (mark_asof - snapshot_asof).total_seconds() > 60:
                        raise ValueError("position mark is newer than its snapshot asof")
                    close_cost = _number(mark.get("close_cost"), "close_cost")
                    dte_number = _validate_bull_put(pos.get("legs"), mark_asof.date())
                    if "dte" not in mark:
                        raise ValueError("dte is required")
                    supplied_dte = _number(mark["dte"], "dte")
                    if not supplied_dte.is_integer() or int(supplied_dte) != dte_number:
                        raise ValueError("supplied dte does not match ledger expiry and mark time")
                    short_itm = mark.get("short_itm")
                    if not isinstance(short_itm, bool):
                        raise ValueError("short_itm must be boolean")
                    entry_credit = _number(pos.get("credit"), "entry credit", minimum=0.0000001)
                    action, reason = evaluate(entry_credit, close_cost, dte_number,
                                              short_itm=short_itm, cfg=policy)
                    result.update(action=action, reason=reason,
                                  mark_asof=mark_asof.isoformat().replace("+00:00", "Z"),
                                  mark_age_seconds=round(max(0.0, age), 1),
                                  close_cost=close_cost, dte=dte_number,
                                  short_itm=short_itm)
                    fresh_count += 1
                except (TypeError, ValueError, OverflowError) as exc:
                    result["reason"] = str(exc)
        totals[result["action"]] += 1
        output.append(result)

    coverage = fresh_count / len(supported_positions) if supported_positions else 1.0
    complete = (not global_errors and fresh_count == len(supported_positions)
                and not any(p["action"] == "NOT_SUPPORTED" for p in output))
    return {
        "schema_version": 1,
        "generated_at": now.isoformat().replace("+00:00", "Z"),
        "snapshot": {"source": source, "asof": (snapshot_asof.isoformat().replace("+00:00", "Z")
                                                       if snapshot_asof else None),
                     "max_age_minutes": max_age_minutes},
        "policy": {"strategy": "bull_put_spread", "rules": policy},
        "open_positions": len(open_positions),
        "supported_positions": len(supported_positions),
        "fresh_mark_coverage": round(coverage, 4),
        "fresh_marks": fresh_count,
        "complete": complete,
        "action_counts": totals,
        "recommendations": output,
        "limitations": [
            "Recommendations require human review; no order is placed.",
            "close_cost must be a current executable ask for the complete spread.",
            "The rules are not evidence of positive expectancy; historical option-price validation remains outstanding.",
            "Position-level output is intended for local use and must not be published with public dashboard artifacts.",
        ],
    }


def render_markdown(report):
    lines = ["# Local position management", "",
             f"Generated: {report['generated_at']}",
             f"Snapshot: {report['snapshot']['source'] or 'unknown'} — "
             f"{report['snapshot']['asof'] or 'unavailable'} "
             f"(max age {report['snapshot']['max_age_minutes']:g} minutes)",
             f"Coverage: {report['fresh_marks']}/{report['supported_positions']} "
             f"supported positions ({report['fresh_mark_coverage']:.0%}); "
             f"{'complete' if report['complete'] else 'incomplete'}", "",
             "| Position | Symbol | Strategy | Action | DTE | Close ask | Reason |",
             "|---|---|---|---|---:|---:|---|"]
    for row in report["recommendations"]:
        close = "—" if row["close_cost"] is None else f"${row['close_cost']:.2f}"
        dte = "—" if row.get("dte") is None else str(row["dte"])
        values = [row.get("position_id") or "—", row.get("underlying") or "—",
                  row.get("strategy") or "—", row["action"], dte, close,
                  row.get("reason") or "—"]
        lines.append("| " + " | ".join(str(v).replace("|", "\\|") for v in values) + " |")
    lines.extend(["", "## Action counts", ""])
    lines.extend(f"- {name}: {count}" for name, count in report["action_counts"].items()
                 if count)
    lines.extend(["", "## Limitations", ""])
    lines.extend(f"- {item}" for item in report["limitations"])
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--ledger", required=True, help="local ledger JSON path")
    ap.add_argument("--marks", required=True, help="timestamped marks JSON path")
    ap.add_argument("--max-age-minutes", type=float, default=30.0)
    ap.add_argument("--out", required=True, help="local JSON report path")
    ap.add_argument("--markdown-out", help="optional local Markdown report path")
    ap.add_argument("--config", help="optional gates.yaml path")
    args = ap.parse_args()
    with open(args.ledger, encoding="utf-8") as f:
        ledger = json.load(f)
    with open(args.marks, encoding="utf-8") as f:
        snapshot = json.load(f)
    report = evaluate_positions(ledger, snapshot, max_age_minutes=args.max_age_minutes,
                                exit_config=gates.load(args.config)["exits"]["bull_put_spread"])
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
        f.write("\n")
    if args.markdown_out:
        with open(args.markdown_out, "w", encoding="utf-8") as f:
            f.write(render_markdown(report))
    print(json.dumps({"complete": report["complete"],
                      "supported_positions": report["supported_positions"],
                      "fresh_marks": report["fresh_marks"],
                      "action_counts": report["action_counts"],
                      "out": args.out}, indent=2))


if __name__ == "__main__":
    main()
