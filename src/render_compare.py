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

# Column tooltips
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from column_tooltips import TOOLTIPS
    import json as _json
    _TIP_DICT = _json.dumps(TOOLTIPS)
    TOOLTIP_JS = (
        "<script>\n"
        "const COLUMN_TIPS = " + _TIP_DICT + ";\n"
        "document.addEventListener('DOMContentLoaded', () => {\n"
        "  document.querySelectorAll('th').forEach(th => {\n"
        "    const text = th.textContent.trim();\n"
        "    if (COLUMN_TIPS[text] && !th.hasAttribute('title')) {\n"
        "      th.setAttribute('title', COLUMN_TIPS[text]);\n"
        "      th.style.cursor = 'help';\n"
        "    }\n"
        "  });\n"
        "});\n"
        "</script>\n"
    )
except ImportError:
    TOOLTIP_JS = ""

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
        for rank, (sym, score, m, reasons) in enumerate(ranked, 1):
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
        parts.append("</tbody></table></div>")

        # Leader's scoring breakdown
        if ranked:
            lead_sym, lead_score, _, lead_reasons = ranked[0]
            parts.append(
                f'<div style="margin-top:12px;padding:12px;background:#0d1117;'
                f'border-radius:8px;border:1px solid var(--border)">'
                f'<strong>Why {esc(lead_sym)} leads ({view}):</strong>'
                f'<span style="color:var(--dim)"> score {lead_score}</span><br>'
            )
            for r in lead_reasons:
                parts.append(f'<span style="color:var(--dim)">• {esc(r)}</span><br>')
            parts.append('</div>')

        parts.append("</div></div>")

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
    parts.append("</div>" + TOOLTIP_JS + "</body></html>")
    return "\n".join(parts)


def main(argv):
    parser = argparse.ArgumentParser(description="Render setup leaderboard")
    parser.add_argument("--universe", required=True)
    parser.add_argument("--top", type=int, default=15)
    parser.add_argument("--out", default=None)
    args = parser.parse_args(argv)

    import compare as cmp
    upath = f"src/universes/{args.universe}.txt"
    with open(upath) as f:
        symbols = [l.strip() for l in f if l.strip() and not l.startswith("#")]
    results, errors = cmp.rank_universe(symbols, top=args.top)
    html = render_page(args.universe, results, errors)
    out = args.out or f"docs/compare.html"
    with open(out, "w") as f:
        f.write(html)
    # JSON sidecar
    jout = out + ".json"
    serializable = {}
    for view, ranked in results.items():
        serializable[view] = [
            {"symbol": s, "score": sc,
             "price": m.get("price"), "trend": m.get("trend"),
             "verdict": m.get("verdict")}
            for s, sc, m, _ in ranked
        ]
    with open(jout, "w") as f:
        import json as js
        js.dump({"universe": args.universe, "results": serializable,
                 "errors": errors}, f, indent=2)
    print(f"Wrote {out} and {jout}")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main(sys.argv[1:]))
