#!/usr/bin/env python3
"""
Render a universe comparison leaderboard as a standalone HTML page (#114).

Runs compare.rank_universe() across all views and writes docs/compare.html.
The hub (render_hub.py) links to this page from index.html.

Usage:
    python3 src/render_compare.py --universe lev_etf
    python3 src/render_compare.py --universe lev_etf --top 10 --out docs/compare.html

Stdlib-only, reuses CSS from render_report.
"""

import argparse
import datetime as dt
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from compare import VIEWS, load_universe, rank_universe
from render_report import CSS, esc


def _badge(val):
    """Color badge for trend/verdict."""
    if val in ("UP", "Go for it"):
        return f'<span style="color:var(--green);font-weight:700">{esc(val)}</span>'
    if val in ("DN",):
        return f'<span style="color:var(--red);font-weight:700">{esc(val)}</span>'
    if val in ("RNG", "Watch"):
        return f'<span style="color:var(--amber);font-weight:700">{esc(val)}</span>'
    return esc(val or "—")


def _fmt_pct(v):
    if v is None:
        return "—"
    cls = "var(--green)" if v >= 0 else "var(--red)"
    return f'<span style="color:{cls}">{v:+.1f}%</span>'


def render_page(universe_name, results, errors, top=None):
    """Build the full HTML page."""
    now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    total = sum(len(r) for r in results.values())

    parts = [f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Setup Leaderboard — {esc(universe_name)}</title>
<style>{CSS}
.view-tabs{{display:flex;gap:8px;margin:0 0 16px;flex-wrap:wrap}}
.view-tab{{padding:8px 16px;border:1px solid var(--border);border-radius:20px;
background:#0d1117;color:var(--dim);cursor:pointer;font-size:.85rem;font-weight:600}}
.view-tab.active{{background:rgba(88,166,255,.15);color:var(--blue);border-color:var(--blue)}}
.view-section{{display:none}}
.view-section.active{{display:block}}
.backlink{{margin-bottom:16px}}
.backlink a{{color:var(--blue);text-decoration:none;font-size:.9rem}}
</style></head>
<body><div class="wrap">
<div class="backlink"><a href="index.html">← Back to Latest Reports</a></div>
<header>
<h1>Setup Leaderboard — {esc(universe_name)}</h1>
<div class="sub">Ranked by view-specific setup score · {esc(now)} ·
{total} symbols scored</div>
"""]
    if errors:
        parts.append(
            f'<div class="sub">⚠️ Skipped {len(errors)}: '
            f'{esc(", ".join(sorted(errors)))}</div>'
        )
    parts.append("</header>")

    # Tab buttons
    parts.append('<div class="view-tabs">')
    for i, view in enumerate(VIEWS):
        if view not in results:
            continue
        cls = "view-tab active" if i == 0 else "view-tab"
        parts.append(
            f'<button class="{cls}" data-view="{view}">'
            f'{view.capitalize()}</button>'
        )
    parts.append('</div>')

    # Decision logic explainer
    parts.append("""<div class="card"><h2>How each view scores</h2>
<div class="sub" style="margin-bottom:12px">Higher score = better setup for that view.
All inputs come from the screener pipeline — never invented.</div>
<div class="tbl-wrap"><table>
<thead><tr><th>View</th><th>Decision logic</th></tr></thead><tbody>
<tr><td><strong>Bullish</strong></td><td class="wrap-cell">
Favors <strong>UP trend</strong> (+10) and bullish bias (+5).
Rewards <strong>pullback entries</strong> — 5%+ off the 52-week high (+3).
Penalizes <strong>overbought</strong> RSI above 70 (−5).
Downtrend names score negative.</td></tr>
<tr><td><strong>Bearish</strong></td><td class="wrap-cell">
Favors <strong>DN trend</strong> (+10) and bearish bias (+5).
Penalizes <strong>oversold</strong> RSI below 30 (−5) — avoids catching falling knives.
Uptrend names score negative.</td></tr>
<tr><td><strong>Neutral</strong></td><td class="wrap-cell">
Favors <strong>range-bound (RNG) trend</strong> (+10).
Rewards <strong>liquid, high-scoring names</strong> — screener score weighted 0.8×
(base 0.5× + bonus 0.3×). Built for premium-selling in chop.</td></tr>
<tr><td><strong>Directional</strong></td><td class="wrap-cell">
Takes the <strong>stronger of the bullish and bearish scores</strong> per symbol.
Finds the best trending setups <strong>regardless of side</strong> —
useful for universe scans where direction is undecided.</td></tr>
</tbody></table></div>
<div class="sub" style="margin-top:10px">Base: screener score × 0.5 for all views.
Earnings dates flagged as a caveat — check the window before trading binary events.</div>
</div>""")

    # One section per view
    for i, view in enumerate(VIEWS):
        if view not in results:
            continue
        ranked = results[view]
        cls = "view-section active" if i == 0 else "view-section"
        parts.append(f'<div class="{cls}" id="view-{view}">')
        parts.append(f'<div class="card"><h2>{view.capitalize()} '
                     f'— Top {len(ranked)}</h2>')
        parts.append('<div class="tbl-wrap"><table>')
        parts.append(
            "<thead><tr><th>#</th><th>Symbol</th><th>Score</th>"
            "<th>Price</th><th>30d</th><th>YTD</th><th>Trend</th>"
            "<th>RSI</th><th>Verdict</th></tr></thead><tbody>"
        )
        for rank, (sym, score, m) in enumerate(ranked, 1):
            price = f"${m['price']:,.2f}" if m.get("price") else "—"
            rsi = f"{m['rsi14']:.0f}" if m.get("rsi14") else "—"
            parts.append(
                f"<tr><td>{rank}</td>"
                f"<td><strong>{esc(sym)}</strong></td>"
                f"<td>{score}</td>"
                f"<td>{price}</td>"
                f"<td>{_fmt_pct(m.get('ret_30d_pct'))}</td>"
                f"<td>{_fmt_pct(m.get('ytd_ret_pct'))}</td>"
                f"<td>{_badge(m.get('trend'))}</td>"
                f"<td>{rsi}</td>"
                f"<td>{_badge(m.get('verdict'))}</td></tr>"
            )
        parts.append("</tbody></table></div></div></div>")

    # Tab switching JS
    parts.append("""<script>
document.querySelectorAll('.view-tab').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.view-tab').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.view-section').forEach(s => s.classList.remove('active'));
    btn.classList.add('active');
    document.getElementById('view-' + btn.dataset.view).classList.add('active');
  });
});
</script>""")

    parts.append(
        '<div class="sub" style="margin-top:16px">'
        'Not investment advice. All metrics from the screener pipeline; '
        'model estimates labeled as such.</div>'
    )
    parts.append("</div></body></html>")
    return "\n".join(parts)


def resolve_docs_dir():
    """Find the docs/ directory."""
    for cand in ("docs", "./docs", "../docs"):
        if os.path.isdir(cand):
            return cand
    # Fallback: repo/docs relative to src/
    repo_docs = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "..", "docs")
    if os.path.isdir(repo_docs):
        return repo_docs
    raise SystemExit("docs/ directory not found")


def main(argv):
    parser = argparse.ArgumentParser(
        description="Render universe comparison leaderboard (#114)"
    )
    parser.add_argument("--universe", default="lev_etf",
                        help="Universe name (default: lev_etf)")
    parser.add_argument("--top", type=int, default=15,
                        help="Top N per view (default: 15)")
    parser.add_argument("--out", default=None,
                        help="Output path (default: docs/compare.html)")
    args = parser.parse_args(argv)

    docs_dir = resolve_docs_dir()
    out_path = args.out or os.path.join(docs_dir, "compare.html")

    print(f"Loading universe '{args.universe}'...", file=sys.stderr)
    symbols = load_universe(args.universe)
    print(f"  {len(symbols)} symbols", file=sys.stderr)

    print("Scoring across all views...", file=sys.stderr)
    results, errors = rank_universe(symbols, top=args.top)
    for view in VIEWS:
        print(f"  {view}: {len(results.get(view, []))} ranked",
              file=sys.stderr)

    html = render_page(args.universe, results, errors, top=args.top)
    with open(out_path, "w") as f:
        f.write(html)
    print(f"Wrote {out_path} ({len(html)} bytes)", file=sys.stderr)

    # Also write a JSON sidecar for programmatic access
    sidecar = {
        "universe": args.universe,
        "generated_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "views": {
            v: [{"symbol": s, "score": sc} for s, sc, _ in ranked]
            for v, ranked in results.items()
        },
        "errors": errors,
    }
    with open(out_path + ".json", "w") as f:
        json.dump(sidecar, f, indent=2)

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
