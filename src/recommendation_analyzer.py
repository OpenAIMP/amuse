#!/usr/bin/env python3
"""
Automated recommendation analyzer.

Generates a comprehensive analysis for any screener recommendation,
covering:
- Technical: RSI (overbought/oversold), trend, support/resistance, pullback risk
- Strategy risk: expected move vs breach, earnings proximity, what-if scenarios
- Screening transparency: what was evaluated, what was discarded, ranking criteria
- Catalysts: earnings dates, binary events

This runs automatically with every screener run — not a one-off.

Usage:
    python3 src/recommendation_analyzer.py \
        --pmcc reports/pmcc-daily.json \
        --stock reports/stock-screen.json \
        --out reports/analysis.json

    python3 src/recommendation_analyzer.py \
        --spreads reports/spread-screen.json \
        --stock reports/stock-screen.json \
        --out reports/analysis.json

Stdlib-only.
"""

import argparse
import datetime as dt
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ---------------------------------------------------------------- helpers

def load_json(path):
    if not path or not os.path.exists(path):
        return {}
    with open(path) as f:
        return json.load(f)


def rsi_reading(rsi):
    """Classify RSI into overbought/oversold/neutral."""
    if rsi is None:
        return "unknown", "No RSI data"
    if rsi >= 70:
        return "overbought", f"RSI {rsi:.0f} — overbought, pullback risk elevated"
    if rsi >= 60:
        return "elevated", f"RSI {rsi:.0f} — elevated, approaching overbought"
    if rsi <= 30:
        return "oversold", f"RSI {rsi:.0f} — oversold, bounce possible"
    if rsi <= 40:
        return "weak", f"RSI {rsi:.0f} — weak, below neutral"
    return "neutral", f"RSI {rsi:.0f} — neutral, no extreme"


def trend_reading(stock_data):
    """Summarize trend from stock screener data."""
    trend = (stock_data.get("trend") or "unknown").upper()
    sma50 = stock_data.get("sma50_dist_pct")
    sma200 = stock_data.get("sma200_dist_pct")
    parts = []
    if trend == "UP":
        parts.append("Uptrend (price > SMA50 > SMA200)")
    elif trend == "DN":
        parts.append("Downtrend (price < SMA50 < SMA200)")
    elif trend == "RNG":
        parts.append("Range-bound (mixed signals)")
    else:
        parts.append(f"Trend: {trend}")
    if sma50 is not None:
        parts.append(f"{sma50:+.1f}% vs SMA50")
    if sma200 is not None:
        parts.append(f"{sma200:+.1f}% vs SMA200")
    return "; ".join(parts)


def pullback_risk(stock_data):
    """Assess pullback risk from technicals."""
    rsi = stock_data.get("rsi14")
    off_high = stock_data.get("off_high_pct")
    risks = []
    level = "low"
    if rsi and rsi >= 70:
        risks.append(f"RSI {rsi:.0f} overbought")
        level = "high"
    elif rsi and rsi >= 60:
        risks.append(f"RSI {rsi:.0f} elevated")
        level = "moderate"
    if off_high is not None and off_high > -3:
        risks.append(f"within {abs(off_high):.1f}% of 52w high")
        if level == "low":
            level = "moderate"
    if not risks:
        risks.append("No overbought signals; RSI neutral, not extended")
    return level, "; ".join(risks)


def expected_move_vs_breach(stock_data, breach_pct):
    """Compare expected 30-day move to breach distance."""
    atr_pct = stock_data.get("atr_pct")
    if atr_pct and breach_pct is not None:
        # Rough 30-day expected move ~ ATR% * sqrt(30)
        exp_30d = atr_pct * 5.48
        ratio = breach_pct / exp_30d if exp_30d > 0 else 0
        if ratio < 0.7:
            risk = "HIGH — breach inside expected move"
        elif ratio < 1.0:
            risk = "MODERATE — breach near expected move"
        else:
            risk = "LOW — breach beyond expected move"
        return {
            "expected_30d_pct": round(exp_30d, 1),
            "breach_pct": round(breach_pct, 1),
            "ratio": round(ratio, 2),
            "risk": risk,
        }
    return {"risk": "unknown — insufficient data"}


# ---------------------------------------------------------------- PMCC analysis

def analyze_pmcc(pmcc_data, stock_data_map):
    """Generate comprehensive analysis for PMCC recommendations."""
    pairs = pmcc_data.get("pairs") or {}
    evaluated = pmcc_data.get("evaluated_pairs") or {}

    # Count evaluated vs qualified
    total_eval = sum(len(v or []) for v in evaluated.values())
    qualified = len(pairs)

    analyses = []
    for sym, pair in sorted(
            pairs.items(),
            key=lambda kv: -((kv[1] or {}).get("premium_to_debit_30d") or 0)):
        pair = pair or {}
        stock = stock_data_map.get(sym.upper(), {})

        # Technical
        rsi = stock.get("rsi14")
        rsi_level, rsi_desc = rsi_reading(rsi)
        trend_desc = trend_reading(stock)
        pb_level, pb_desc = pullback_risk(stock)

        # Strategy risk
        breach = pair.get("breach_vs_spot")
        if breach:
            breach_pct = breach * 100
        else:
            breach_pct = pair.get("breach_pct")
        move_analysis = expected_move_vs_breach(stock, breach_pct)

        # Earnings
        earnings = pair.get("earnings_date") or stock.get("earnings_date")
        events = pair.get("events") or []

        # What was discarded for this symbol
        sym_evals = evaluated.get(sym, []) or evaluated.get(sym.upper(), [])
        n_eval = len(sym_evals)
        n_rej = sum(1 for e in sym_evals
                    if (e.get("qualification_status") or "") == "rejected")

        analyses.append({
            "symbol": sym,
            "structure": "PMCC",
            "long_strike": pair.get("long_strike"),
            "short_strike": pair.get("short_strike"),
            "premium_to_debit_30d": pair.get("premium_to_debit_30d"),
            "capital": pair.get("capital"),
            "breach_pct": round(breach_pct, 1) if breach_pct else None,
            "monthly_income_est": (
                round(pair.get("premium_to_debit_30d", 0) / 100
                      * pair.get("capital", 0), 0)
                if pair.get("premium_to_debit_30d") and pair.get("capital")
                else None
            ),
            "technical": {
                "rsi_level": rsi_level,
                "rsi_description": rsi_desc,
                "trend": trend_desc,
                "pullback_risk_level": pb_level,
                "pullback_risk_detail": pb_desc,
            },
            "strategy_risk": {
                "expected_move": move_analysis,
                "earnings_date": earnings,
                "earnings_in_window": bool(earnings),
                "events": events,
            },
            "screening": {
                "combinations_evaluated": n_eval,
                "combinations_rejected": n_rej,
                "ranking_criterion": "P/D 30d (premium-to-debit), descending",
                "gates": ("LEAPS 0.80-0.95D / 270-800 DTE; "
                          "short 0.15-0.35D / 21-60 DTE; "
                          "P/D >= 4.0%; breach <= 8%; "
                          "no earnings in window; liquid"),
            },
        })

    return {
        "type": "pmcc",
        "generated": dt.datetime.now(dt.timezone.utc).isoformat(),
        "summary": {
            "total_combinations_evaluated": total_eval,
            "qualifying_pairs": qualified,
            "symbols_with_pairs": len(pairs),
        },
        "recommendations": analyses,
    }


# ---------------------------------------------------------------- Spread analysis

def analyze_spreads(spread_data, stock_data_map):
    """Generate comprehensive analysis for spread recommendations."""
    structures = spread_data.get("structures") or []
    analyses = []
    for s in structures[:20]:  # Top 20
        s = s or {}
        sym = (s.get("symbol") or "").upper()
        stock = stock_data_map.get(sym, {})

        rsi = stock.get("rsi14")
        rsi_level, rsi_desc = rsi_reading(rsi)
        trend_desc = trend_reading(stock)
        pb_level, pb_desc = pullback_risk(stock)

        analyses.append({
            "symbol": sym,
            "structure": s.get("strategy") or s.get("type"),
            "strikes": s.get("strikes"),
            "credit": s.get("credit"),
            "max_loss": s.get("max_loss"),
            "win_pct": s.get("win_pct"),
            "ev": s.get("ev"),
            "verdict": s.get("lucrative") or s.get("verdict"),
            "technical": {
                "rsi_level": rsi_level,
                "rsi_description": rsi_desc,
                "trend": trend_desc,
                "pullback_risk_level": pb_level,
                "pullback_risk_detail": pb_desc,
            },
        })

    return {
        "type": "spreads",
        "generated": dt.datetime.now(dt.timezone.utc).isoformat(),
        "summary": {
            "structures_analyzed": len(analyses),
            "total_structures": len(structures),
        },
        "recommendations": analyses,
    }


# ---------------------------------------------------------------- main

def build_stock_map(stock_data):
    """Build {SYMBOL: data} from stock screener output."""
    result = {}
    for entry in stock_data.get("results") or stock_data.get("stocks") or []:
        sym = (entry.get("symbol") or "").upper()
        if sym:
            result[sym] = entry
    # Also try dict format
    for sym, entry in (stock_data.get("by_symbol") or {}).items():
        result[sym.upper()] = entry
    return result


def main(argv):
    ap = argparse.ArgumentParser(
        description="Automated recommendation analyzer")
    ap.add_argument("--pmcc", default=None, help="PMCC JSON path")
    ap.add_argument("--spreads", default=None, help="Spread JSON path")
    ap.add_argument("--stock", default=None, help="Stock screener JSON path")
    ap.add_argument("--out", default=None, help="Output JSON path")
    args = ap.parse_args(argv)

    stock_data = load_json(args.stock)
    stock_map = build_stock_map(stock_data)

    output = {}
    if args.pmcc:
        pmcc_data = load_json(args.pmcc)
        output["pmcc"] = analyze_pmcc(pmcc_data, stock_map)
    if args.spreads:
        spread_data = load_json(args.spreads)
        output["spreads"] = analyze_spreads(spread_data, stock_map)

    if not output:
        print("No input provided (--pmcc or --spreads required)",
              file=sys.stderr)
        return 1

    output["generated"] = dt.datetime.now(dt.timezone.utc).isoformat()

    if args.out:
        with open(args.out, "w") as f:
            json.dump(output, f, indent=2, default=str)
        print(f"Wrote {args.out}")
    else:
        print(json.dumps(output, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
