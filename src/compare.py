"""
Trade comparison: side-by-side setup analysis for two symbols,
or leaderboard across a universe for all views (#114).

Answers "which has the better setup?" for a given directional view
(bullish/bearish/neutral/directional) using the screener's own data —
never invented numbers.

Usage:
    python3 src/compare.py --a NVDA --b AMD --view bullish
    python3 src/compare.py --a SPY --b QQQ --view neutral --json
    python3 src/compare.py --universe lev_etf
    python3 src/compare.py --universe lev_etf --view bearish
    python3 src/compare.py --universe lev_etf --top 10 --json
"""

import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from stock_screener import screen_stock


# ---------------------------------------------------------------------------
# Metric extraction
# ---------------------------------------------------------------------------

def extract_metrics(sym):
    """
    Run the stock screener on a symbol and extract comparison metrics.

    Returns (metrics_dict, error_str). metrics_dict is None on failure.
    """
    sym, ok, metrics, reasons = screen_stock(sym)
    if not ok or metrics is None:
        return None, "; ".join(reasons) if reasons else "screening failed"

    ind = metrics.get("indicators", {}) or {}
    struct = ind.get("structure", {}) or {}
    tape = ind.get("tape", {}) or {}

    # Price data from the latest bar
    bars = metrics.get("bars", []) or []
    last = bars[-1] if bars else {}
    prev = bars[-2] if len(bars) >= 2 else {}

    price = last.get("close") or metrics.get("price")
    prev_close = prev.get("close")

    # Returns
    ret_1d = None
    if price and prev_close:
        ret_1d = (price - prev_close) / prev_close * 100

    # 30-day and YTD returns from bars if available
    ret_30d = None
    ytd_ret = None
    if len(bars) >= 30:
        c30 = bars[-30].get("close")
        if c30 and price:
            ret_30d = (price - c30) / c30 * 100
    # YTD: find first bar of current year
    if bars:
        from datetime import datetime
        year = datetime.now().year
        for b in bars:
            ts = b.get("timestamp") or b.get("date") or ""
            if str(year) in str(ts):
                first_close = b.get("close")
                if first_close and price:
                    ytd_ret = (price - first_close) / first_close * 100
                break

    # 52-week high/low
    hi52 = metrics.get("high_52w") or ind.get("high_52w")
    lo52 = metrics.get("low_52w") or ind.get("low_52w")
    off_high_pct = None
    if hi52 and price:
        off_high_pct = (price - hi52) / hi52 * 100

    # Support/resistance from pivots
    pivots = ind.get("pivots", {}) or {}
    support = pivots.get("support")
    resistance = pivots.get("resistance")

    # RSI
    rsi = ind.get("rsi14") or ind.get("rsi")

    # SMA distances
    sma50 = ind.get("sma50")
    dist_sma50 = None
    if sma50 and price:
        dist_sma50 = (price - sma50) / sma50 * 100

    # Earnings
    earnings_date = None
    try:
        with open(os.path.join(os.path.dirname(__file__),
                               "earnings_dates.json")) as f:
            earnings = json.load(f)
            info = earnings.get(sym.upper(), {})
            earnings_date = info.get("earnings")
    except (IOError, json.JSONDecodeError):
        pass

    return {
        "symbol": sym,
        "price": round(price, 2) if price else None,
        "ret_1d_pct": round(ret_1d, 2) if ret_1d is not None else None,
        "ret_30d_pct": round(ret_30d, 2) if ret_30d is not None else None,
        "ytd_ret_pct": round(ytd_ret, 2) if ytd_ret is not None else None,
        "score": metrics.get("score"),
        "verdict": metrics.get("verdict"),
        "verdict_reason": metrics.get("verdict_reason"),
        "trend": struct.get("trend"),
        "bias": tape.get("bias"),
        "rsi14": round(rsi, 1) if rsi else None,
        "dist_sma50_pct": round(dist_sma50, 2) if dist_sma50 is not None else None,
        "off_high_pct": round(off_high_pct, 2) if off_high_pct is not None else None,
        "support": round(support, 2) if support else None,
        "resistance": round(resistance, 2) if resistance else None,
        "earnings_date": earnings_date,
    }, None


# ---------------------------------------------------------------------------
# Comparison logic
# ---------------------------------------------------------------------------

VIEWS = ("bullish", "bearish", "neutral", "directional")


def _score_for_view(m, view):
    """
    Compute a view-specific comparison score from extracted metrics.
    Higher = better setup for the stated view.

    This is a ranking heuristic, not a trade signal.
    """
    s = 0.0
    reasons = []

    score = m.get("score") or 0
    s += score * 0.5  # base: overall screener score
    reasons.append(f"screener score {score}")

    trend = m.get("trend", "")
    bias = m.get("bias", "")

    # Directional: best of bullish/bearish — for symbols with a strong
    # trend in either direction. Useful for universe scans.
    if view == "directional":
        b_score, b_reasons = _score_for_view(m, "bullish")
        r_score, r_reasons = _score_for_view(m, "bearish")
        if b_score >= r_score:
            return b_score, [f"directional→bullish ({b_score})"] + b_reasons
        else:
            return r_score, [f"directional→bearish ({r_score})"] + r_reasons

    if view == "bullish":
        if trend == "UP":
            s += 10
            reasons.append("UP trend (+10)")
        elif trend == "RNG":
            s += 3
            reasons.append("RNG trend (+3)")
        elif trend == "DN":
            s -= 10
            reasons.append("DN trend (-10)")
        if bias == "bullish":
            s += 5
            reasons.append("bullish bias (+5)")
        # Prefer pullbacks: closer to support, not too extended
        off_high = m.get("off_high_pct")
        if off_high is not None and off_high < -5:
            s += 3
            reasons.append(f"{abs(off_high):.1f}% off high — pullback entry (+3)")
        # Penalize overbought
        rsi = m.get("rsi14")
        if rsi and rsi > 70:
            s -= 5
            reasons.append(f"RSI {rsi} overbought (-5)")

    elif view == "bearish":
        if trend == "DN":
            s += 10
            reasons.append("DN trend (+10)")
        elif trend == "RNG":
            s += 3
            reasons.append("RNG trend (+3)")
        elif trend == "UP":
            s -= 10
            reasons.append("UP trend (-10)")
        if bias == "bearish":
            s += 5
            reasons.append("bearish bias (+5)")
        rsi = m.get("rsi14")
        if rsi and rsi < 30:
            s -= 5
            reasons.append(f"RSI {rsi} oversold (-5)")

    else:  # neutral
        if trend == "RNG":
            s += 10
            reasons.append("RNG trend (+10)")
        # Prefer moderate IV environment (proxied by distance from extremes)
        # and strong liquidity (proxied by screener score)
        s += score * 0.3
        reasons.append("neutral favors range-bound + liquid")

    # Earnings proximity: penalize if earnings within 2 weeks (binary risk)
    # (We don't have "today" vs earnings math here without date parsing;
    # flag it as a caveat instead.)
    if m.get("earnings_date"):
        reasons.append(f"earnings {m['earnings_date']} — check window")

    return round(s, 1), reasons


def compare(a_sym, b_sym, view="bullish"):
    """
    Compare two symbols for a directional view.

    Returns a dict with per-symbol metrics, scores, and a verdict.
    """
    if view not in VIEWS:
        raise ValueError(f"view must be one of {VIEWS}")

    a_metrics, a_err = extract_metrics(a_sym)
    b_metrics, b_err = extract_metrics(b_sym)

    result = {
        "view": view,
        "symbols": [a_sym, b_sym],
        "errors": {},
    }
    if a_err:
        result["errors"][a_sym] = a_err
    if b_err:
        result["errors"][b_sym] = b_err

    if a_metrics is None or b_metrics is None:
        result["verdict"] = None
        result["verdict_reason"] = "insufficient data for comparison"
        return result

    result["a"] = a_metrics
    result["b"] = b_metrics

    a_score, a_reasons = _score_for_view(a_metrics, view)
    b_score, b_reasons = _score_for_view(b_metrics, view)

    result["a_score"] = a_score
    result["a_reasons"] = a_reasons
    result["b_score"] = b_score
    result["b_reasons"] = b_reasons

    if a_score > b_score:
        result["verdict"] = a_sym
        result["verdict_reason"] = (
            f"{a_sym} scores {a_score} vs {b_sym} {b_score} "
            f"for a {view} view"
        )
    elif b_score > a_score:
        result["verdict"] = b_sym
        result["verdict_reason"] = (
            f"{b_sym} scores {b_score} vs {a_sym} {a_score} "
            f"for a {view} view"
        )
    else:
        result["verdict"] = "tie"
        result["verdict_reason"] = f"both score {a_score} for a {view} view"

    return result


# ---------------------------------------------------------------------------
# Output formatting
# ---------------------------------------------------------------------------

DISCLAIMER = (
    "Not investment advice. All metrics from the screener pipeline; "
    "model estimates labeled as such. Do your own due diligence."
)


def format_table(result):
    """Render a markdown comparison table."""
    lines = []
    view = result["view"]
    a_sym, b_sym = result["symbols"]
    lines.append(f"# {a_sym} vs {b_sym} — {view} view")
    lines.append("")

    if result["errors"]:
        for sym, err in result["errors"].items():
            lines.append(f"⚠️ {sym}: {err}")
        lines.append("")

    if "a" not in result:
        lines.append(f"Cannot compare: {result.get('verdict_reason')}")
        return "\n".join(lines)

    a, b = result["a"], result["b"]

    def row(label, key, fmt=None):
        va, vb = a.get(key), b.get(key)
        if fmt and va is not None:
            va = fmt(va)
        if fmt and vb is not None:
            vb = fmt(vb)
        va = va if va is not None else "—"
        vb = vb if vb is not None else "—"
        lines.append(f"| {label} | {va} | {vb} |")

    pct = lambda x: f"{x:+.1f}%"
    px = lambda x: f"${x:,.2f}"

    lines.append(f"| Metric | {a_sym} | {b_sym} |")
    lines.append("|---|---|---|")
    row("Price", "price", px)
    row("1-day", "ret_1d_pct", pct)
    row("30-day", "ret_30d_pct", pct)
    row("YTD", "ytd_ret_pct", pct)
    row("Screener score", "score")
    row("Verdict", "verdict")
    row("Trend", "trend")
    row("Bias", "bias")
    row("RSI(14)", "rsi14")
    row("Dist from SMA50", "dist_sma50_pct", pct)
    row("Off 52w high", "off_high_pct", pct)
    row("Support", "support", px)
    row("Resistance", "resistance", px)
    row("Earnings", "earnings_date")
    lines.append("")
    lines.append(f"**Setup score ({view}):** "
                 f"{a_sym} {result['a_score']} vs "
                 f"{b_sym} {result['b_score']}")
    lines.append("")
    for sym, key in ((a_sym, "a_reasons"), (b_sym, "b_reasons")):
        lines.append(f"**{sym}:**")
        for r in result[key]:
            lines.append(f"- {r}")
        lines.append("")
    lines.append(f"**Verdict: {result['verdict']}** — {result['verdict_reason']}")
    lines.append("")
    lines.append(f"*{DISCLAIMER}*")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Universe leaderboard
# ---------------------------------------------------------------------------

def load_universe(name):
    """Load symbols from src/universes/<name>.txt."""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "universes", f"{name}.txt")
    with open(path) as f:
        return [line.strip().upper() for line in f
                if line.strip() and not line.startswith("#")]


def rank_universe(symbols, views=None, top=None):
    """
    Score every symbol across all views (or a subset).

    Returns ({view: [(symbol, score, metrics, reasons), ...]}, errors)
    sorted by score desc. Symbols that fail screening are skipped.
    """
    views = views or VIEWS
    results = {v: [] for v in views}
    errors = {}

    for sym in symbols:
        metrics, err = extract_metrics(sym)
        if err or metrics is None:
            errors[sym] = err or "screening failed"
            continue
        for view in views:
            score, reasons = _score_for_view(metrics, view)
            results[view].append((sym, score, metrics, reasons))

    for view in views:
        results[view].sort(key=lambda x: x[1], reverse=True)
        if top:
            results[view] = results[view][:top]

    return results, errors


def format_leaderboard(results, errors, universe_name, top=None):
    """Render a multi-view leaderboard as markdown."""
    lines = []
    lines.append(f"# {universe_name} — Setup Leaderboard")
    lines.append("")
    if errors:
        lines.append(f"⚠️ Skipped {len(errors)}: {', '.join(sorted(errors))}")
        lines.append("")

    for view in VIEWS:
        if view not in results:
            continue
        ranked = results[view]
        lines.append(f"## {view.capitalize()} (top {len(ranked)})")
        lines.append("")
        lines.append("| Rank | Symbol | Score | Price | 30d | Trend | Verdict |")
        lines.append("|---|---|---|---|---|---|---|")
        for i, (sym, score, m) in enumerate(ranked, 1):
            price = f"${m['price']:,.2f}" if m.get("price") else "—"
            ret30 = f"{m['ret_30d_pct']:+.1f}%" if m.get("ret_30d_pct") is not None else "—"
            trend = m.get("trend") or "—"
            verdict = m.get("verdict") or "—"
            lines.append(f"| {i} | {sym} | {score} | {price} | {ret30} | {trend} | {verdict} |")
        lines.append("")

    lines.append(f"*{DISCLAIMER}*")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv):
    import argparse
    parser = argparse.ArgumentParser(
        description="Compare two symbols for a directional view (#114)"
    )
    # Pairwise mode
    parser.add_argument("--a", help="First symbol (pairwise mode)")
    parser.add_argument("--b", help="Second symbol (pairwise mode)")
    # Universe mode
    parser.add_argument("--universe",
                        help="Universe name (e.g. lev_etf) for leaderboard mode")
    parser.add_argument("--top", type=int, default=None,
                        help="Top N per view in leaderboard mode")
    parser.add_argument("--view", default="bullish", choices=VIEWS,
                        help="Directional view (default: bullish)")
    parser.add_argument("--json", action="store_true",
                        help="Output raw JSON instead of markdown")
    args = parser.parse_args(argv)

    # Universe leaderboard mode
    if args.universe:
        symbols = load_universe(args.universe)
        if args.view != "bullish" or "--view" not in " ".join(argv):
            # Single view requested
            views = [args.view]
        else:
            # Default: all views
            views = list(VIEWS)
        results, errors = rank_universe(symbols, views=views, top=args.top)
        if args.json:
            out = {
                "universe": args.universe,
                "views": {
                    v: [{"symbol": s, "score": sc,
                         "price": m.get("price"),
                         "trend": m.get("trend"),
                         "verdict": m.get("verdict")}
                        for s, sc, m, _ in ranked]
                    for v, ranked in results.items()
                },
                "errors": errors,
            }
            print(json.dumps(out, indent=2, default=str))
        else:
            print(format_leaderboard(results, errors, args.universe,
                                     top=args.top))
        return 0

    # Pairwise mode (requires --a and --b)
    if not args.a or not args.b:
        parser.error("--a and --b required (or use --universe)")
    result = compare(args.a.upper(), args.b.upper(), args.view)
    if args.json:
        print(json.dumps(result, indent=2, default=str))
    else:
        print(format_table(result))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
