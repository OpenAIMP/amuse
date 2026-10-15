"""Six-step advisory options decision engine for daily screener output.

Reads the existing technical and spread screens, ranks candidates, and writes
JSON plus a human-readable report. It never places orders.
"""
import argparse
import json
import os

from options_math import expected_move, fractional_kelly
from ledger import can_open

MIN_KELLY_TRADES = 30


def _history(ledger, strategy):
    closed = [p for p in (ledger or {}).get("positions", [])
              if p.get("status") == "closed"
              and p.get("strategy", "").lower() == strategy.lower()
              and p.get("exit", {}).get("realized_pnl") is not None]
    if len(closed) < MIN_KELLY_TRADES:
        return None, len(closed)
    wins = [p for p in closed if p["exit"]["realized_pnl"] > 0]
    losses = [p for p in closed if p["exit"]["realized_pnl"] <= 0]
    p = len(wins) / len(closed)
    gain = sum(p["exit"]["realized_pnl"] for p in wins) / len(wins) if wins else 0
    loss = abs(sum(p["exit"]["realized_pnl"] for p in losses) / len(losses)) if losses else 0
    return ((p, gain, loss) if gain > 0 and loss > 0 else None), len(closed)


def build_decisions(stock_data, spread_data, ledger=None, account=None,
                    kelly_fraction=0.25):
    passing = {x.get("symbol"): x for x in (stock_data or {}).get("passing", [])}
    rejected = (stock_data or {}).get("rejected", {})
    results = (spread_data or {}).get("results", {})
    candidates, by_symbol = [], {}
    # Regime router (issue #106): map trend regime to compatible strategy families.
    # Instead of binary pass/fail per strategy, we route each symbol to its
    # regime-appropriate families.
    REGIME_ROUTES = {
        "UP": [("bull_puts", "bull_put_spread"),
               ("asym_condors", "asym_condor")],
        "DN": [("bear_calls", "bear_call_spread")],
        "RNG": [("iron_condors", "iron_condor"),
                ("iron_butterflies", "iron_butterfly")],
    }
    # Collect all symbols that have any structures
    all_syms = set()
    for group in ("bull_puts", "bear_calls", "iron_condors",
                  "iron_butterflies", "asym_condors"):
        all_syms.update((results.get(group) or {}).keys())
    for sym in sorted(all_syms):
        stock = passing.get(sym)
        ind = (stock or {}).get("indicators") or {}
        trend = (ind.get("structure") or {}).get("trend") or "UNKNOWN"
        # Route to regime-appropriate strategies
        routes = REGIME_ROUTES.get(trend, [])
        for group, strategy in routes:
            raw = (results.get(group) or {}).get(sym)
            if not raw:
                continue
            vol = raw.get("vol") or {}
            reasons, steps = [], []
            # 1. Regime / router (always PASS here — routing already filtered)
            steps.append({"step": 1, "name": "Regime", "status": "PASS",
                          "detail": f"stock-qualified={bool(stock)}; trend={trend}; structure={strategy}; routed by regime"})
            # 2. Horizon / event exposure
            dte = raw.get("dte")
            if dte is None and raw.get("expiration"):
                try:
                    from datetime import date
                    dte = (date.fromisoformat(raw["expiration"]) - date.today()).days
                except ValueError:
                    dte = None
            events = raw.get("events") or []
            horizon_ok = dte is not None and dte > 0 and not events
            if events:
                reasons.append("event flags present: " + ", ".join(map(str, events)))
            if dte is None or dte <= 0:
                reasons.append("expiration horizon missing or expired")
            steps.append({"step": 2, "name": "Horizon & catalysts", "status": "PASS" if horizon_ok else "BLOCK",
                          "detail": f"DTE={dte}; event flags={events}"})
            # 3. Timing / signal quality
            score = (stock or {}).get("score")
            squeezed = bool((ind.get("bollinger") or {}).get("squeeze"))
            confirmation = ind.get("confirmations") or {}
            smi_read = confirmation.get("smi_13_3_3") or {}
            adx_read = confirmation.get("adx14") or {}
            timing_context = (
                f"; confirmation context only: SMI={smi_read.get('value')} "
                f"(signal {smi_read.get('signal')}), CCI20={confirmation.get('cci20')}, "
                f"Williams %R14={confirmation.get('williams_r14')}, "
                f"ADX14={adx_read.get('adx')} (+DI={adx_read.get('plus_di')}, "
                f"-DI={adx_read.get('minus_di')})") if confirmation else ""
            timing_ok = score is not None and score >= 20 and not squeezed
            if not stock or score is None:
                reasons.append("timing score unavailable")
            elif score < 20:
                reasons.append(f"technical score {score} is below the 20-point watch threshold")
            steps.append({"step": 3, "name": "Timing", "status": "PASS" if timing_ok else "BLOCK",
                          "detail": f"technical score={score}; squeeze={squeezed}{timing_context}"})
            # 4. Volatility
            vol_state = str(vol.get("decision", "NO_READ")).upper()
            vol_ok = vol_state != "STAND_DOWN"
            if not vol_ok:
                reasons.append("volatility assessment says STAND_DOWN")
            steps.append({"step": 4, "name": "Volatility", "status": "PASS" if vol_ok else "BLOCK",
                          "detail": f"volatility decision={vol_state}; {vol.get('reason', 'assessment unavailable')}"})
            # 5. Structure / economics
            ev = raw.get("expected_value")
            max_loss = raw.get("max_loss_total")
            credit = raw.get("credit_total")
            structure_ok = (isinstance(max_loss, (int, float)) and max_loss > 0
                            and isinstance(credit, (int, float)) and credit > 0
                            and isinstance(ev, (int, float)) and ev > 0)
            if not structure_ok:
                reasons.append("structure lacks positive reported EV or valid defined-risk payoffs")
            steps.append({"step": 5, "name": "Structure & economics", "status": "PASS" if structure_ok else "BLOCK",
                          "detail": f"reported EV=${ev}; max loss=${max_loss}; credit=${credit}; win probability is the screener's delta proxy"})
            # 6. Kelly / portfolio sizing (requires actual, adequately sampled ledger history)
            # Issue #102: when Kelly history is unavailable, mark SKIPPED (not UNSIZED)
            # and do NOT block the trade — missing sizing is informational, not a rejection.
            history, ntrades = _history(ledger, strategy)
            sizing = {"status": "SKIPPED",
                      "reason": f"Kelly sizing unavailable ({ntrades}/{MIN_KELLY_TRADES} closed {strategy} trades) — no size recommendation; use manual judgment"}
            if history and account and max_loss:
                probability, avg_win, avg_loss = history
                k = fractional_kelly(probability, avg_win, avg_loss, kelly_fraction, 0.02)
                risk_budget = float(account) * k["capped_fraction"]
                contracts = int(risk_budget // float(max_loss))
                heat_ok, heat_reason = can_open(ledger or {"positions": []},
                                                float(max_loss) / 100.0,
                                                contracts, float(account)) if contracts else (False, "Kelly budget rounds to zero contracts")
                sizing = {"status": "SIZED" if contracts else "ZERO_CONTRACTS",
                          "historical_trades": ntrades, "empirical_win_rate": round(probability, 4),
                          **{key: round(value, 6) for key, value in k.items()},
                          "risk_budget": round(risk_budget, 2), "contracts": contracts,
                          "note": "Kelly uses realized ledger win rate and average win/loss; capped at 2% account risk."}
                if contracts and not heat_ok:
                    sizing.update({"status": "HEAT_BLOCKED", "contracts": 0,
                                   "reason": heat_reason})
            elif history and not account:
                sizing = {"status": "SKIPPED", "historical_trades": ntrades,
                          "reason": "Kelly sizing unavailable — account value required to convert Kelly fraction into contracts; use manual judgment"}
            # Issue #102: SKIPPED sizing is informational only — do not block the trade.
            # Only ZERO_CONTRACTS and HEAT_BLOCKED are true sizing rejections.
            if sizing["status"] not in ("SIZED", "SKIPPED"):
                reasons.append(sizing.get("reason", "Kelly sizing returned zero contracts"))
            steps.append({"step": 6, "name": "Risk & sizing", "status": sizing["status"],
                          "detail": sizing.get("reason", f"contracts={sizing.get('contracts')}")})
            approved = all(s["status"] == "PASS" for s in steps[:5])
            # Issue #102: CONSIDER when economics pass, even if sizing was skipped
            # (user sizes manually). Only require SIZED for auto-sized recommendations.
            if approved and sizing["status"] == "SIZED" and sizing["contracts"] > 0:
                recommendation = "CONSIDER"
            elif approved:
                recommendation = "CONSIDER (size manually — Kelly unavailable)"
            else:
                recommendation = "NO TRADE"
            # Candidate ranking uses existing EV/RoR plus timing; it is not a calibrated probability.
            rank = (float(ev or 0) + 100 * float(raw.get("return_on_risk") or 0)
                    + 2 * float(score or 0))
            iv = vol.get("iv30") or vol.get("iv") or vol.get("current_iv")
            move = None
            if iv is not None and dte is not None and stock and stock.get("price"):
                try:
                    move = expected_move(float(stock["price"]), float(iv), int(dte))
                except (TypeError, ValueError):
                    pass
            item = {"symbol": sym, "strategy": strategy, "recommendation": recommendation,
                    "rank_score": round(rank, 3), "expiration": raw.get("expiration"),
                    "dte": dte, "credit_total": credit, "max_loss_total": max_loss,
                    "expected_value_delta_proxy": ev, "return_on_risk": raw.get("return_on_risk"),
                    "win_prob_est_delta_proxy": raw.get("win_prob_est"),
                    "expected_move_1sd": move, "kelly_sizing": sizing,
                    "steps": steps, "reasons": reasons}
            candidates.append(item)
            by_symbol.setdefault(sym, []).append(item)
    candidates.sort(key=lambda x: (-x["rank_score"], x["symbol"], x["strategy"]))
    preferred = next((c for c in candidates if c["recommendation"] == "CONSIDER"), None)
    if preferred is None:
        preferred = next((c for c in candidates if c["recommendation"] == "WATCH"), None)
    summary = (f"{preferred['recommendation']}: {preferred['strategy']} on {preferred['symbol']}" if preferred
               else "NO TRADE: no candidate cleared the decision gates")
    # Phase 4 (issue #106): per-symbol best-strategy recommendation.
    # For each symbol, rank its candidates by EV and pick the best.
    best_by_symbol = {}
    for sym, items in by_symbol.items():
        # Sort by EV descending, then by rank_score
        ranked = sorted(items, key=lambda x: (-(x.get("expected_value_delta_proxy") or -999999),
                                              -x.get("rank_score", 0)))
        best = ranked[0] if ranked else None
        if best:
            best_by_symbol[sym] = {
                "strategy": best["strategy"],
                "recommendation": best["recommendation"],
                "expected_value": best.get("expected_value_delta_proxy"),
                "rank_score": best.get("rank_score"),
                "alternatives": len(ranked) - 1,
            }
    return {"asof": (spread_data or {}).get("asof") or (stock_data or {}).get("asof"),
            "summary": summary, "selected_candidate": preferred,
            "candidate_count": len(candidates), "candidates": candidates,
            "best_by_symbol": best_by_symbol,
            "decision_policy": "Advisory only. No orders are placed. Existing delta-based probability/EV estimates are proxies; Kelly requires at least 30 realized closed trades per strategy and an account value.",
            "rejected_stock_symbols": list(rejected.keys())}


def render_markdown(report):
    lines = ["# Amuse unified options decision", "", f"**As of:** {report.get('asof') or 'unknown'}  ",
             f"**Decision:** {report['summary']}", "", report["decision_policy"], "",
             "## Ranked candidates", ""]
    if not report["candidates"]:
        lines.append("No spread candidates were supplied by the screen.")
    for c in report["candidates"]:
        lines.extend([f"### {c['recommendation']} — {c['symbol']} {c['strategy']}",
                      f"Expiry {c.get('expiration')} ({c.get('dte')} DTE); credit ${c.get('credit_total')}; max loss ${c.get('max_loss_total')}; delta-proxy EV ${c.get('expected_value_delta_proxy')}.",
                      "", "| Step | Gate | Status | Detail |", "|---|---|---|---|"])
        for s in c["steps"]:
            lines.append(f"| {s['step']}. {s['name']} | — | {s['status']} | {s['detail']} |")
        if c["reasons"]:
            lines.extend(["", "Reasons / sizing gaps:"] + [f"- {reason}" for reason in c["reasons"]])
        lines.append("")
    lines.extend(["## Interpretation", "", "Black–Scholes pricing, Greeks, expected move, and fractional Kelly are available as reusable calculations. Portfolio Greek/stress results require an open ledger and a current market-context JSON. Screen candidates do not contain per-leg implied volatility, so this report does not fabricate a theoretical option mark or full position Greeks."])
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--stock", required=True)
    ap.add_argument("--spreads", required=True)
    ap.add_argument("--ledger")
    ap.add_argument("--account", type=float)
    ap.add_argument("--kelly-fraction", type=float, default=0.25)
    ap.add_argument("--json-out", default="reports/decision.json")
    ap.add_argument("--markdown-out", default="reports/decision.md")
    args = ap.parse_args()
    def read(path):
        with open(path) as f:
            return json.load(f)
    report = build_decisions(read(args.stock), read(args.spreads),
                             read(args.ledger) if args.ledger else None,
                             args.account, args.kelly_fraction)
    for path, content in ((args.json_out, json.dumps(report, indent=2) + "\n"),
                          (args.markdown_out, render_markdown(report))):
        if path:
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
    print(report["summary"])


if __name__ == "__main__":
    main()
