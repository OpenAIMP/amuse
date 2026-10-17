#!/usr/bin/env python3
"""
Render Tastytrade backtest results as HTML (#117).

Takes a backtest JSON file (from tastytrade_backtest.py) and generates
a standalone HTML page showing:
- Summary metrics (win rate, P&L, profit factor, etc.)
- Realized vs modeled comparison
- Gates calibration suggestions

Usage:
    python3 src/render_backtest.py --input reports/backtest-spy.json --out docs/backtest-spy.html

Stdlib-only, reuses CSS from render_report.
"""

import argparse
import datetime as dt
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from render_report import CSS, esc


def _fmt_pct(val):
    """Format as percentage."""
    if val is None:
        return "—"
    return f"{val * 100:.1f}%"


def _fmt_money(val):
    """Format as dollars."""
    if val is None:
        return "—"
    sign = "+" if val >= 0 else ""
    return f"{sign}${val:,.0f}"


def _gates_suggestions(summary, modeled_win_rate=None):
    """
    Generate gates.yaml calibration suggestions based on backtest results.
    
    Returns list of (parameter, current_implication, suggestion) tuples.
    """
    suggestions = []
    realized_wr = summary.get("win_rate", 0)
    
    if modeled_win_rate and abs(realized_wr - modeled_win_rate) > 0.10:
        # Significant deviation (>10pp)
        if realized_wr < modeled_win_rate:
            suggestions.append((
                "probability_calibration",
                f"Modeled Win% ({modeled_win_rate*100:.0f}%) overestimates realized ({realized_wr*100:.0f}%)",
                "Consider reducing delta-based Win% estimates or tightening entry gates in gates.yaml"
            ))
        else:
            suggestions.append((
                "probability_calibration",
                f"Realized Win% ({realized_wr*100:.0f}%) exceeds modeled ({modeled_win_rate*100:.0f}%)",
                "Screener may be too conservative; consider relaxing gates.yaml thresholds"
            ))
    
    profit_factor = summary.get("profitFactor", summary.get("profit_factor"))
    if profit_factor and profit_factor < 1.0:
        suggestions.append((
            "exits.profit_target",
            f"Profit factor {profit_factor:.2f} < 1.0 (losing)",
            "Consider adjusting exits.profit_target or exits.stop_loss in gates.yaml"
        ))
    
    max_dd = summary.get("maxDrawdown", summary.get("max_drawdown"))
    if max_dd and max_dd < -0.20:  # >20% drawdown
        suggestions.append((
            "position_sizing",
            f"Max drawdown {_fmt_pct(max_dd)} exceeds 20%",
            "Consider reducing position size or tightening max_loss in gates.yaml"
        ))
    
    return suggestions


def render_backtest(data, title="Backtest Results"):
    """Render backtest JSON data as HTML."""
    summary = data.get("summary", {})
    symbol = data.get("symbol", "—")
    strategy = data.get("strategy", "—")
    period = data.get("period", "—")
    
    # Metrics table
    metrics = [
        ("Symbol", esc(symbol)),
        ("Strategy", esc(strategy)),
        ("Period", esc(period)),
        ("Trades", summary.get("trade_count", "—")),
        ("Wins", summary.get("win_count", "—")),
        ("Losses", summary.get("loss_count", "—")),
        ("Win Rate", _fmt_pct(summary.get("win_rate"))),
        ("Total P&L", _fmt_money(summary.get("total_pnl"))),
        ("Avg Win", _fmt_money(summary.get("avg_win"))),
        ("Avg Loss", _fmt_money(summary.get("avg_loss"))),
        ("Profit Factor", f"{summary.get('profitFactor', summary.get('profit_factor', '—'))}"),
        ("Max Drawdown", _fmt_pct(summary.get("maxDrawdown", summary.get("max_drawdown")))),
        ("Sharpe", f"{summary.get('sharpeRatio', summary.get('sharpe_ratio', '—'))}"),
    ]
    
    metrics_html = "\n".join(
        f'<tr><td style="font-weight:600">{k}</td><td>{v}</td></tr>'
        for k, v in metrics
    )
    
    # Gates suggestions
    suggestions = _gates_suggestions(summary)
    if suggestions:
        sugg_html = "\n".join(
            f'''<div style="background:var(--card);border:1px solid var(--amber);border-radius:8px;padding:12px;margin:8px 0">
            <strong>{esc(param)}</strong><br>
            <span style="color:var(--amber)">{esc(implication)}</span><br>
            <span style="font-size:0.9em">{esc(suggestion)}</span>
            </div>'''
            for param, implication, suggestion in suggestions
        )
    else:
        sugg_html = '<p style="color:var(--green)">No calibration needed — realized metrics align with modeled expectations.</p>'
    
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

<h2>Summary Metrics</h2>
<table>
{metrics_html}
</table>

<h2>Gates Calibration</h2>
<p>Based on backtest results, the following <code>gates.yaml</code> parameters may need adjustment:</p>
{sugg_html}

<div style="margin-top:24px;padding:16px;background:var(--card);border-radius:8px">
<h3>How to update gates.yaml</h3>
<p>Backtest results can inform <code>gates.yaml</code> tuning:</p>
<ul>
<li><strong>Win rate deviation</strong> → Adjust probability calibration or entry thresholds</li>
<li><strong>Profit factor &lt; 1.0</strong> → Tighten <code>exits.profit_target</code> or <code>exits.stop_loss</code></li>
<li><strong>High drawdown</strong> → Reduce position sizing or <code>max_loss</code> limits</li>
</ul>
<p class="muted">See <a href="https://github.com/OpenAIMP/amuse/blob/main/gates.yaml">gates.yaml</a> for all tunable parameters.</p>
</div>

</div>
</body>
</html>"""
    return html


def main():
    parser = argparse.ArgumentParser(description="Render backtest results to HTML (#117)")
    parser.add_argument("--input", required=True, help="Backtest JSON file")
    parser.add_argument("--out", default="docs/backtest.html", help="Output HTML file")
    parser.add_argument("--title", default="Backtest Results", help="Page title")
    args = parser.parse_args()
    
    with open(args.input) as f:
        data = json.load(f)
    
    html = render_backtest(data, args.title)
    
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w") as f:
        f.write(html)
    
    print(f"Wrote {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
