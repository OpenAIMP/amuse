#!/usr/bin/env python3
"""Render screener JSON outputs into a single-file HTML dashboard.

Usage:
    python3 render_report.py --stock reports/stock-screen.json \
        --spreads reports/spread-screen.json --pmcc reports/pmcc.json \
        --out docs/index.html

All inputs are optional; a missing input renders its section as "no data yet"
instead of failing. Output is one self-contained HTML file (all CSS inline,
no external assets, no JavaScript) suitable for GitHub Pages.
"""
from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import os
import re
import sys

# ---------------------------------------------------------------- helpers

def load_json(path):
    if not path:
        return None
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError) as e:
        print(f"warning: could not read {path}: {e}", file=sys.stderr)
        return None


def esc(v):
    return html.escape("" if v is None else str(v))


def num(v, places=1, suffix=""):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return '<span class="na">—</span>'
    if f != f or f in (float("inf"), float("-inf")):
        return '<span class="na">—</span>'
    return f"{f:.{places}f}{suffix}"


def money(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return '<span class="na">—</span>'
    return f"${f:,.0f}"


def pct(v, places=1):
    return num(v, places, "%")


def dte_between(asof_str, exp_str):
    try:
        a = dt.date.fromisoformat(asof_str)
        e = dt.date.fromisoformat(exp_str)
        return max(0, (e - a).days)
    except (ValueError, TypeError):
        return None


def trend_badge(t):
    t = (t or "").upper()
    cls = {"UP": "good", "DN": "bad", "RNG": "warn"}.get(t, "")
    return f'<span class="badge {cls}">{esc(t) or "—"}</span>'


def events_cell(ev):
    if not ev:
        return '<span class="na">—</span>'
    items = [esc(x) for x in ev]
    cls = "warn" if any("unknown" in x.lower() for x in ev) else ""
    return f'<span class="{cls}">' + "<br>".join(items) + "</span>"


def why_for(symbol, readout):
    """First readout line mentioning the symbol (word boundary), or ''."""
    if not readout:
        return ""
    pat = re.compile(r"\b" + re.escape(symbol) + r"\b")
    for line in readout:
        if isinstance(line, str) and pat.search(line):
            return line
    return ""


# ---------------------------------------------------------------- sections

WORKFLOW = [
    ("Screen", "Find candidates across the watchlist or universe."),
    ("Regime", "Trend structure + anchored VWAP pick the strategy family."),
    ("Timing", "%B, RSI and squeeze confirm — or veto — the entry now."),
    ("Strikes", "Fib levels and swing pivots place short strikes behind structure."),
    ("Size", "1–2% max loss per trade; total heat under 40%."),
    ("Preflight", "Buying power, events, fees — then your confirmation."),
]


def workflow_strip():
    cells = []
    for i, (name, desc) in enumerate(WORKFLOW):
        arrow = '<div class="flow-arrow">→</div>' if i else ""
        cells.append(
            f'{arrow}<div class="flow-step"><div class="flow-name">{i+1}. {esc(name)}</div>'
            f'<div class="flow-desc">{esc(desc)}</div></div>'
        )
    return '<div class="flow">' + "".join(cells) + "</div>"


def stock_section(data):
    if not data:
        return section("Stock screen", '<p class="empty">No data yet — run the stock screener.</p>')
    passing = sorted(data.get("passing", []),
                     key=lambda p: -(p.get("score") if isinstance(p.get("score"), (int, float)) else -1))
    rows = []
    for p in passing:
        ind = p.get("indicators") or {}
        bb = ind.get("bollinger") or {}
        vw = ind.get("vwap") or {}
        st = ind.get("structure") or {}
        sqz = "●" if bb.get("squeeze") else ""
        rows.append(
            "<tr>"
            f"<td class='sym'>{esc(p.get('symbol'))}</td>"
            f"<td class='num'>{num(p.get('price'), 2)}</td>"
            f"<td class='num'>{num(p.get('rsi14'))}</td>"
            f"<td class='num'>{num(bb.get('pct_b'), 2)}</td>"
            f"<td class='num'>{num(bb.get('bandwidth_pct'))}</td>"
            f"<td class='sqz'>{'<span class=\"warn\">●</span>' if sqz else ''}</td>"
            f"<td class='num'>{pct(vw.get('anchored_dist_pct'))}</td>"
            f"<td>{trend_badge(st.get('trend'))}</td>"
            f"<td class='num'><b>{num(p.get('score'))}</b><span class='dim'>/40</span></td>"
            "</tr>"
        )
    table = (
        '<div class="tbl-wrap"><table><thead><tr>'
        "<th>Symbol</th><th>Price</th><th>RSI14</th><th>%B</th><th>BW%</th>"
        "<th>SQZ</th><th>aVWAP%</th><th>Trend</th><th>Score</th>"
        "</tr></thead><tbody>"
        + ("".join(rows) if rows else '<tr><td colspan="9" class="empty">No qualifiers this run.</td></tr>')
        + "</tbody></table></div>"
    )
    readout = ""
    ro = data.get("readout") or []
    if ro:
        lines = "".join(f"<li>{esc(l)}</li>" for l in ro if isinstance(l, str))
        readout = f'<div class="readout"><div class="readout-title">Readout</div><ul>{lines}</ul></div>'
    return section("Stock screen", table + readout)


def spread_tables(data):
    if not data:
        return section("Spread opportunities", '<p class="empty">No data yet — run the spread screener.</p>')
    res = data.get("results") or {}
    asof = data.get("asof")
    readout = data.get("readout") or []
    out = []

    bps = sorted((res.get("bull_puts") or {}).items(),
                 key=lambda kv: -(kv[1].get("return_on_risk") or -1))
    rows = []
    for sym, r in bps:
        dte = dte_between(asof, r.get("expiration"))
        why = why_for(sym, readout)
        rows.append(
            "<tr>"
            f"<td class='sym'>{esc(sym)}</td>"
            f"<td class='num'>{esc(r.get('expiration'))}</td>"
            f"<td class='num'>{num(r.get('short_strike'), 0)}/{num(r.get('long_strike'), 0)}P</td>"
            f"<td class='num'>{dte if dte is not None else '—'}</td>"
            f"<td class='num'>{money(r.get('credit_total'))}</td>"
            f"<td class='num'>{money(r.get('max_loss_total'))}</td>"
            f"<td class='num'>{num(r.get('breakeven'), 2)}</td>"
            f"<td class='num good'>{pct((r.get('return_on_risk') or 0) * 100)}</td>"
            f"<td>{events_cell(r.get('events'))}</td>"
            "</tr>"
            + (f"<tr class='whyrow'><td colspan='9'>{esc(why)}</td></tr>" if why else "")
        )
    out.append("<h3>Bull put spreads <span class='dim'>(ranked by return on risk)</span></h3>")
    out.append(
        '<div class="tbl-wrap"><table><thead><tr>'
        "<th>Sym</th><th>Exp</th><th>Strikes</th><th>DTE</th><th>Credit</th>"
        "<th>Max loss</th><th>Breakeven</th><th>RoR</th><th>Events</th>"
        "</tr></thead><tbody>"
        + ("".join(rows) if rows else '<tr><td colspan="9" class="empty">No qualifying bull puts.</td></tr>')
        + "</tbody></table></div>"
    )

    ics = sorted((res.get("iron_condors") or {}).items(),
                 key=lambda kv: -(kv[1].get("return_on_risk") or -1))
    rows = []
    for sym, r in ics:
        dte = dte_between(asof, r.get("expiration"))
        pw = r.get("put_wing") or []
        cw = r.get("call_wing") or []
        why = why_for(sym, readout)
        rows.append(
            "<tr>"
            f"<td class='sym'>{esc(sym)}</td>"
            f"<td class='num'>{esc(r.get('expiration'))}</td>"
            f"<td class='num'>{num(pw[0] if len(pw) > 0 else None, 0)}/{num(pw[1] if len(pw) > 1 else None, 0)}P</td>"
            f"<td class='num'>{num(cw[0] if len(cw) > 0 else None, 0)}/{num(cw[1] if len(cw) > 1 else None, 0)}C</td>"
            f"<td class='num'>{dte if dte is not None else '—'}</td>"
            f"<td class='num'>{money(r.get('credit_total'))}</td>"
            f"<td class='num'>{money(r.get('max_loss_total'))}</td>"
            f"<td class='num'>{num(r.get('breakeven_put'), 2)} / {num(r.get('breakeven_call'), 2)}</td>"
            f"<td class='num good'>{pct((r.get('return_on_risk') or 0) * 100)}</td>"
            f"<td>{events_cell(r.get('events'))}</td>"
            "</tr>"
            + (f"<tr class='whyrow'><td colspan='10'>{esc(why)}</td></tr>" if why else "")
        )
    out.append("<h3>Iron condors <span class='dim'>(ranked by return on risk)</span></h3>")
    out.append(
        '<div class="tbl-wrap"><table><thead><tr>'
        "<th>Sym</th><th>Exp</th><th>Put wing</th><th>Call wing</th><th>DTE</th>"
        "<th>Credit</th><th>Max loss</th><th>Breakevens</th><th>RoR</th><th>Events</th>"
        "</tr></thead><tbody>"
        + ("".join(rows) if rows else '<tr><td colspan="10" class="empty">No qualifying condors.</td></tr>')
        + "</tbody></table></div>"
    )
    # readout lines not tied to a symbol still get shown
    used = {why_for(sym, readout) for sym, _ in list(bps) + list(ics)}
    rest = [l for l in readout if isinstance(l, str) and l not in used and l.strip()]
    if rest:
        lines = "".join(f"<li>{esc(l)}</li>" for l in rest)
        out.append(f'<div class="readout"><div class="readout-title">Readout</div><ul>{lines}</ul></div>')
    out.append('<p class="fine">Return on risk = credit ÷ max loss: a screening ratio, not an expected return. '
               'Credits use conservative short-bid minus long-ask fills.</p>')
    return section("Spread opportunities", "".join(out))


def pmcc_section(data):
    if not data:
        return section("PMCC watch", '<p class="empty">No data yet — run the PMCC screen.</p>')
    pairs = data.get("pairs") or {}
    ranked = sorted(pairs.items(), key=lambda kv: -((kv[1] or {}).get("premium_to_debit_30d") or -1))
    rows = []
    for sym, r in ranked:
        r = r or {}
        rows.append(
            "<tr>"
            f"<td class='sym'>{esc(sym)}</td>"
            f"<td class='num'>{num(r.get('long_strike'), 0)}C / {num(r.get('short_strike'), 0)}C</td>"
            f"<td class='num'>{num(r.get('premium_to_debit_30d'), 2)}%</td>"
            f"<td class='num'>{money(r.get('capital'))}</td>"
            f"<td class='num'>{pct((r.get('breach_vs_spot') or 0) * 100)}</td>"
            f"<td>{events_cell(r.get('events'))}</td>"
            "</tr>"
        )
    body = (
        '<div class="tbl-wrap"><table><thead><tr>'
        "<th>Sym</th><th>Long / Short</th><th>P/D 30d</th><th>Capital</th><th>Breach</th><th>Events</th>"
        "</tr></thead><tbody>"
        + ("".join(rows) if rows else
           '<tr><td colspan="6" class="empty">No qualifiers — baseline set or nothing meeting entry gates.</td></tr>')
        + "</tbody></table></div>"
    )
    return section("PMCC watch", body)


def rejections_section(stock_data):
    if not stock_data:
        return ""
    rej = stock_data.get("rejected") or {}
    counts = {}
    for sym, info in rej.items():
        for reason in (info or {}).get("reasons", []):
            counts[reason] = counts.get(reason, 0) + 1
    if not counts:
        return ""
    items = "".join(
        f"<li><span class='dim'>{c}×</span> {esc(reason)}</li>"
        for reason, c in sorted(counts.items(), key=lambda kv: -kv[1])
    )
    detail = (
        "<details><summary>Stock screen rejections "
        f"({len(rej)} names, {sum(counts.values())} reason hits)</summary>"
        f"<ul class='rej'>{items}</ul></details>"
    )
    return section("Rejections", detail +
                   '<p class="fine">Spread and PMCC rejection detail lives in the console reports (run artifacts).</p>')


def section(title, body):
    return f'<section class="card"><h2>{esc(title)}</h2>{body}</section>'


# ---------------------------------------------------------------- page

CSS = """
:root{--bg:#0d1117;--card:#161b22;--border:#30363d;--text:#e6edf3;--dim:#8b949e;
--green:#3fb950;--red:#f85149;--amber:#d29922;--blue:#58a6ff}
*{box-sizing:border-box}
body{background:var(--bg);color:var(--text);font-family:-apple-system,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;
margin:0;padding:24px 16px;line-height:1.5}
.wrap{max-width:1100px;margin:0 auto}
header{margin-bottom:20px}
h1{font-size:1.6rem;margin:0 0 4px}
.sub{color:var(--dim);font-size:.9rem;margin:2px 0}
.card{background:var(--card);border:1px solid var(--border);border-radius:10px;
padding:18px;margin:0 0 18px}
h2{font-size:1.15rem;margin:0 0 12px;color:var(--text)}
h3{font-size:1rem;margin:18px 0 8px}
.flow{display:flex;align-items:stretch;gap:0;overflow-x:auto;padding:4px 0}
.flow-step{flex:1;min-width:130px;background:#0d1117;border:1px solid var(--border);
border-radius:8px;padding:10px 12px}
.flow-name{font-weight:700;color:var(--blue);font-size:.85rem;margin-bottom:4px}
.flow-desc{font-size:.78rem;color:var(--dim)}
.flow-arrow{align-self:center;color:var(--dim);padding:0 8px;font-size:1.2rem;flex:none}
.tbl-wrap{overflow-x:auto;border:1px solid var(--border);border-radius:8px}
table{border-collapse:collapse;width:100%;font-size:.85rem;min-width:640px}
thead th{background:#0d1117;color:var(--dim);text-align:left;font-weight:600;
padding:10px 12px;border-bottom:1px solid var(--border);white-space:nowrap;
position:sticky;top:0}
tbody td{padding:9px 12px;border-bottom:1px solid #21262d;white-space:nowrap}
tbody tr:last-child td{border-bottom:none}
tbody tr:hover{background:#1c2128}
.num{font-variant-numeric:tabular-nums;text-align:right;font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}
.sym{font-weight:700}
.good{color:var(--green)} .bad{color:var(--red)} .warn{color:var(--amber)}
.na,.dim{color:var(--dim)} .empty{color:var(--dim);font-style:italic;text-align:center!important}
.badge{display:inline-block;padding:2px 10px;border-radius:20px;font-size:.75rem;font-weight:700}
.badge.good{background:rgba(63,185,80,.15);color:var(--green)}
.badge.bad{background:rgba(248,81,73,.15);color:var(--red)}
.badge.warn{background:rgba(210,153,34,.15);color:var(--amber)}
.readout{background:#0d1117;border-left:3px solid var(--blue);border-radius:0 8px 8px 0;
padding:12px 16px;margin:16px 0 4px}
.readout-title{font-weight:700;color:var(--blue);font-size:.85rem;margin-bottom:6px}
.readout ul{margin:0;padding-left:18px}
.readout li{margin:4px 0;font-size:.9rem}
.whyrow td{white-space:normal!important;font-size:.8rem;color:var(--dim);
border-bottom:1px solid var(--border);padding:4px 12px 10px 28px!important;font-style:italic}
.fine{font-size:.78rem;color:var(--dim);margin:10px 0 0}
details{border:1px solid var(--border);border-radius:8px;padding:10px 14px;background:#0d1117}
summary{cursor:pointer;font-weight:600}
ul.rej{columns:2;column-gap:32px;font-size:.85rem}
ul.rej li{margin:3px 0;break-inside:avoid}
footer{color:var(--dim);font-size:.78rem;text-align:center;margin-top:8px}
@media(max-width:640px){ul.rej{columns:1}body{padding:16px 10px}}
"""

PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Options Lab — Daily Screen</title>
<style>{css}</style>
</head>
<body>
<div class="wrap">
<header>
<h1>Options Lab — Daily Screen</h1>
<p class="sub">Run date: {asof}</p>
<p class="sub">All figures computed from Public.com API data in-run. Credits use conservative short-bid minus long-ask fills.</p>
</header>
<section class="card"><h2>How a trade gets made</h2>{flow}</section>
{stock}
{spreads}
{pmcc}
{rejections}
<footer>Generated {now} · screeners never place orders.</footer>
</div>
</body>
</html>
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stock", default=None)
    ap.add_argument("--spreads", default=None)
    ap.add_argument("--pmcc", default=None)
    ap.add_argument("--out", default="docs/index.html")
    args = ap.parse_args()

    stock = load_json(args.stock)
    spreads = load_json(args.spreads)
    pmcc = load_json(args.pmcc)

    asof = (stock or {}).get("asof") or (spreads or {}).get("asof") \
        or (pmcc or {}).get("asof") or "unknown"

    page = PAGE.format(
        css=CSS,
        asof=esc(asof),
        flow=workflow_strip(),
        stock=stock_section(stock),
        spreads=spread_tables(spreads),
        pmcc=pmcc_section(pmcc),
        rejections=rejections_section(stock),
        now=esc(dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")),
    )
    outdir = os.path.dirname(os.path.abspath(args.out))
    os.makedirs(outdir, exist_ok=True)
    with open(args.out, "w") as f:
        f.write(page)
    print(f"wrote {args.out} ({os.path.getsize(args.out)} bytes)")


if __name__ == "__main__":
    main()
