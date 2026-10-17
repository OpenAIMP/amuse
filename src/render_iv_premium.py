#!/usr/bin/env python3
"""
Render high-IV premium screener results as HTML (#115).

Takes JSON output from iv_premium_screener.py --json and generates
a standalone HTML page.

Usage:
    python3 src/iv_premium_screener.py --universe lev_etf --json > reports/iv-premium.json
    python3 src/render_iv_premium.py --input reports/iv-premium.json --out docs/iv-premium.html

Stdlib-only, reuses CSS from render_report.
"""

import argparse
import datetime as dt
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from render_report import CSS, esc


def render_iv_premium(data, title="High-IV Premium Opportunities"):
    """Render IV premium screener JSON as HTML."""
    candidates = data.get("candidates", [])
    total_found = data.get("total_found", 0)
    symbols_screened = data.get("symbols_screened", 0)
    max_strike_pct = data.get("max_strike_pct", 0.6)
    errors = data.get("errors", [])

    rows = []
    for c in candidates:
        rows.append(
            "<tr>"
            f"<td><strong>{esc(c.get('symbol', '—'))}</strong></td>"
            f"<td>{esc(c.get('window', '—'))}</td>"
            f"<td class='num'>{esc(c.get('expiration', '—'))}</td>"
            f"<td class='num'>{c.get('dte', '—')}</td>"
            f"<td class='num'>{c.get('strike', '—')}</td>"
            f"<td class='num'>{c.get('spot', '—')}</td>"
            f"<td class='num'>{c.get('strike_pct', 0)*100:.1f}%</td>"
            f"<td class='num'>{c.get('iv', 0)*100:.1f}%</td>"
            f"<td class='num'>${c.get('bid', 0):.2f}</td>"
            f"<td class='num'>{c.get('win_prob', 0)*100:.1f}%</td>"
            "</tr>"
        )

    table_html = (
        '<div class="tbl-wrap"><table><thead><tr>'
        "<th>Symbol</th><th>Window</th><th>Expiration</th><th>DTE</th>"
        "<th>Strike</th><th>Spot</th><th>Strike %</th><th>IV</th>"
        "<th>Bid</th><th>Win %</th>"
        "</tr></thead><tbody>"
        + "\n".join(rows) +
        "</tbody></table></div>"
    ) if rows else '<p class="empty">No candidates found.</p>'

    errors_html = ""
    if errors:
        errors_html = (
            f'<div class="warn"><strong>⚠️ {len(errors)} symbols skipped:</strong> '
            + esc(", ".join(errors[:10]))
            + ("..." if len(errors) > 10 else "")
            + "</div>"
        )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)}</title>
<style>{CSS}</style>
</head>
<body>
<div class="wrap">
<h1>{esc(title)}</h1>
<p class="muted">Generated {dt.datetime.now().strftime('%Y-%m-%d %H:%M UTC')} ·
<a href="index.html">← Back to hub</a></p>

<div class="stats">
<span><strong>{total_found}</strong> candidates</span> ·
<span><strong>{symbols_screened}</strong> symbols screened</span> ·
<span>Strike ≤ {max_strike_pct*100:.0f}% of spot</span>
</div>

<h2>Top Opportunities <span class="dim">(ranked by IV)</span></h2>
{table_html}
{errors_html}

<div class="disclaimer">
<p>Not investment advice. IV is a model estimate. Deep OTM puts have high
win probability but carry tail risk.</p>
</div>

</div>
</body>
</html>"""
    return html


def main():
    parser = argparse.ArgumentParser(description="Render IV premium results to HTML (#115)")
    parser.add_argument("--input", required=True, help="JSON file from iv_premium_screener.py --json")
    parser.add_argument("--out", default="docs/iv-premium.html", help="Output HTML file")
    parser.add_argument("--title", default="High-IV Premium Opportunities", help="Page title")
    args = parser.parse_args()

    with open(args.input) as f:
        data = json.load(f)

    html = render_iv_premium(data, args.title)

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w") as f:
        f.write(html)

    print(f"Wrote {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
