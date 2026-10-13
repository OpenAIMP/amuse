#!/usr/bin/env python3
"""Render screener JSON outputs into single-file HTML pages.

Legacy hub mode (unchanged):
    python3 render_report.py --stock reports/stock-screen.json \
        --spreads reports/spread-screen.json --pmcc reports/pmcc.json \
        --out docs/index.html

Report mode (dated, non-overwriting, archived forever):
    python3 render_report.py --stock ... --spreads ... \
        --report-id daily-nasdaq100-2026-10-11 --source nasdaq100 --source-detail "101 names"
    python3 render_report.py --premarket reports/premarket.json \
        --report-id premarket-watchlist-2026-10-13 --source watchlist --source-detail "101 names"
    python3 render_report.py --pmcc reports/pmcc.json \
        --report-id pmcc-watchlist-2026-10 --source watchlist --source-detail "20 names"

Report ids are <type>-<source>-<date>; --source is authoritative when both
the flag and the id carry it. With --report-id, the page goes to
docs/reports/<id>.html (unless --out overrides), a <id>.meta.json sidecar
is written beside it (including source/source_detail), and the page gets a
"back to hub" link plus a provenance banner. Use render_hub.py to rebuild
docs/index.html (the archive homepage) from the sidecars.

All inputs are optional; a missing input renders its section as "no data yet"
in legacy mode and is skipped in report mode. Output is self-contained HTML
(all CSS inline, no external assets, no JavaScript) suitable for GitHub Pages.
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


def esc(v):    return html.escape("" if v is None else str(v))


# "Clicklist": external quote/research pages per ticker. The symbol itself
# links to Google Finance; the ▾ dropdown holds the rest.
QUOTE_LINKS = [
    ("Google Finance", "https://www.google.com/finance/quote/{s}"),
    ("Yahoo Finance", "https://finance.yahoo.com/quote/{s}"),
    ("Nasdaq", "https://www.nasdaq.com/market-activity/stocks/{sl}"),
    ("MarketWatch", "https://www.marketwatch.com/investing/stock/{sl}"),
    ("CNBC", "https://www.cnbc.com/quotes/{s}"),
    ("Public", "https://public.com/stocks/{sl}"),
    ("TradingView", "https://www.tradingview.com/symbols/{s}/"),
    ("Finviz", "https://finviz.com/quote.ashx?t={s}&p=d"),
    ("Fintel", "https://fintel.io/s/us/{sl}"),
    ("WhaleWisdom", "https://whalewisdom.com/stock/{sl}"),
    ("Seeking Alpha", "https://seekingalpha.com/symbol/{s}"),
    ("Zacks", "https://www.zacks.com/stock/research/{s}/earnings-calendar"),
    ("SEC filings", "https://www.sec.gov/cgi-bin/browse-edgar"
                     "?action=getcompany&ticker={s}&type=&dateb=&owner=include&count=40"),
]


def sym_cell(sym):
    """Ticker <td>: symbol links to Google Finance, ▾ opens the clicklist."""
    raw = (sym or "").strip().upper()
    if not raw:
        return "<td class='sym'>—</td>"
    disp = esc(raw)
    menu = "".join(
        f'<a href="{url.format(s=raw, sl=raw.lower())}" target="_blank"'
        f' rel="noopener">{name}</a>'
        for name, url in QUOTE_LINKS[1:]
    )
    primary = QUOTE_LINKS[0][1].format(s=raw, sl=raw.lower())
    return (
        f"<td class='sym'><a class='ticker' href='{primary}' target='_blank'"
        f" rel='noopener'>{disp}</a>"
        f"<details class='qlinks'><summary title='More quote pages'>▾</summary>"
        f"<div class='qmenu'>{menu}</div></details></td>"
    )


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
        tr = ind.get("trend") or {}
        mc = ind.get("macd") or {}
        sqz = "●" if bb.get("squeeze") else ""
        cross = tr.get("cross")
        cross_cell = (f'<span class="badge good">GC</span>' if cross == "golden"
                      else (f'<span class="badge bad">DC</span>' if cross == "death"
                            else '<span class="na">—</span>'))
        mh = mc.get("hist")
        if mh is None:
            mh_cell = '<span class="na">—</span>'
        else:
            cls = "good" if mh > 0 else "bad"
            mh_cell = f"<span class='num {cls}'>{mh:+.2f}</span>"
        tp = ind.get("tape") or {}
        gp = tp.get("gap_pct")
        if gp is None:
            gap_cell = '<span class="na">—</span>'
        else:
            gcls = "good" if gp > 0 else ("bad" if gp < 0 else "")
            gap_cell = f"<span class='num {gcls}'>{gp:+.1f}%</span>"
        mom = tp.get("momentum")
        if mom is None:
            mom_cell = '<span class="na">—</span>'
        elif mom == "neutral":
            mom_cell = '<span class="dim">neutral</span>'
        else:
            mcls = "bad" if mom == "overbought" else "warn"
            mom_cell = f"<span class='badge {mcls}'>{mom}</span>"
        vpct = tp.get("value_pct")
        vv = tp.get("value")
        if vpct is None:
            val_cell = '<span class="na">—</span>'
        else:
            vcls = "warn" if vv == "undervalued" else ("bad" if vv == "overvalued" else "")
            val_cell = f"<span class='num {vcls}'>{vpct:.0f}%</span>"
        bv = tp.get("bias")
        bvotes = tp.get("bias_votes")
        if bv is None:
            bias_cell = '<span class="na">—</span>'
        else:
            bcls = "good" if bv == "bullish" else ("bad" if bv == "bearish" else "")
            votes_txt = f" ({bvotes}/6)" if bvotes is not None else ""
            bias_cell = f"<span class='badge {bcls}'>{bv}{votes_txt}</span>"
        rows.append(
            "<tr>"
            f"{sym_cell(p.get('symbol'))}"
            f"<td class='num'>{num(p.get('price'), 2)}</td>"
            f"<td class='num'>{num(p.get('rsi14'))}</td>"
            f"<td class='num'>{pct(p.get('vs_sma50_pct'))}</td>"
            f"<td class='num'>{pct(p.get('off_52w_high_pct'))}</td>"
            f"<td class='num'>{num(p.get('atr_pct'))}</td>"
            f"<td class='num'>{num(p.get('vol_ratio'), 2)}</td>"
            f"<td class='num'>{num(bb.get('pct_b'), 2)}</td>"
            f"<td class='num'>{num(bb.get('bandwidth_pct'))}</td>"
            f"<td class='sqz'>{'<span class=\"warn\">●</span>' if sqz else ''}</td>"
            f"<td class='num'>{pct(vw.get('anchored_dist_pct'))}</td>"
            f"<td>{trend_badge(st.get('trend'))}</td>"
            f"<td>{cross_cell}</td>"
            f"<td>{mh_cell}</td>"
            f"<td>{gap_cell}</td>"
            f"<td>{mom_cell}</td>"
            f"<td>{val_cell}</td>"
            f"<td>{bias_cell}</td>"
            f"<td class='num'><b>{num(p.get('score'))}</b><span class='dim'>/40</span></td>"
            "</tr>"
        )
    table = (
        '<div class="tbl-wrap"><table><thead><tr>'
        "<th title='Underlying symbol. Click for quote pages.'>Symbol</th><th title='Last price at screen time.'>Price</th>"
        "<th title='RSI(14): momentum oscillator 0-100. Gate keeps 30-70; "
        "below 30 = washed out, above 70 = overheated.'>RSI(14)</th>"
        "<th title='Distance above the 50-day SMA (%). Regime use: the base score "
        "peaks near +2.5% (riding the trend); deeply negative or extremely "
        "extended both score less.'>vs SMA50</th>"
        "<th title='Distance below the 52-week high (%). Gate: must be within 25%. "
        "Near-highs = strength; far below = possible value trap or broken chart.'>"
        "Off 52w high</th>"
        "<th title='Average True Range as % of price: the volatility gate (1-6%). "
        "Too low = premium too thin to sell; too high = moves too violent for "
        "defined-risk spreads. Also the position-sizing input.'>ATR%</th>"
        "<th title='20-day average volume / 60-day average. Above 1.0 = expanding "
        "interest (conviction); feeds 10 of the 30 base score points.'>Vol ratio</th>"
        "<th title='Bollinger %B: where price sits inside the bands "
        "(0 = lower band, 0.5 = middle, 1 = upper). Timing use: above 1.0 = "
        "extended, do not chase (rejected).'>%B</th>"
        "<th title='Bollinger bandwidth as % of the middle band: how wide the "
        "bands are. Low = volatility compression.'>Band width</th>"
        "<th title='Squeeze: bandwidth at its 125-day minimum. A volatility "
        "coil before expansion — timing use: wait, do not enter now.'>Squeeze</th>"
        "<th title='Distance from VWAP anchored at the 52-week low. Regime use: "
        "negative = institutional money underwater — rejected for bullish "
        "premium selling.'>vs Anchored VWAP</th>"
        "<th>Trend</th>"
        "<th title='Golden/death cross: SMA50 crossed SMA200 within the last "
        "20 sessions. GC = golden cross (bullish regime, +2 score); "
        "DC = death cross (bearish, rejected).'>Cross</th>"
        "<th title='MACD histogram (12,26,9): MACD line minus signal line. "
        "Positive = bullish momentum (+1 score); negative = bearish.'>MACD hist</th>"
        "<th title='Overnight gap: (open / prior close − 1). ±2% or more labels "
        "gap up / gap down; smaller = no gap.'>Gap</th>"
        "<th title='RSI(14) state: oversold below 30, overbought above 70, "
        "neutral between. A state label, not a trade signal.'>Momentum</th>"
        "<th title='Technical value: where price sits in its 52-week range. "
        "&le;25% = beaten-down (undervalued), &ge;75% = priced at the top "
        "(overvalued). NOT fundamental valuation — the feed has no "
        "fundamentals.'>Value</th>"
        "<th title='Trend bias: votes from price vs SMA50/200, SMA50 vs SMA200, "
        "MACD hist, RSI>50, pivot trend. 4+ of 6 = bullish, 2 or fewer = "
        "bearish, else neutral.'>Bias</th>"
        "<th>Score</th>"
        "</tr></thead><tbody>"
        + ("".join(rows) if rows else '<tr><td colspan="19" class="empty">No qualifiers this run.</td></tr>')
        + "</tbody></table></div>"
        '<details><summary><b>Column guide — what each value means for decisions</b></summary>'
        '<ul class="guide">'
        "<li><b>Price</b> ($10&ndash;500 gate): names outside the band are rejected — "
        "too cheap = wide spreads, too dear = capital-heavy.</li>"
        "<li><b>RSI(14)</b> (0&ndash;100, gate 30&ndash;70): &lt;30 washed out, "
        "&gt;70 overheated — both rejected. 50&ndash;65 is the sweet spot "
        "(full 10/10 base points): momentum with room to run.</li>"
        "<li><b>vs SMA50</b> (% above the 50-day): regime extension read. The base "
        "score peaks near +2.5% — riding the trend, not stretched. Deeply negative "
        "or extremely extended both score less.</li>"
        "<li><b>Off 52w high</b> (% below the 52-week high, gate &le;25%): near-highs "
        "= strength and clean overhead; far below = possible value trap.</li>"
        "<li><b>ATR%</b> (average true range / price, gate 1&ndash;6%): the volatility "
        "filter. Too low = premium too thin to bother selling; too high = moves too "
        "violent for defined-risk spreads. Doubles as the position-sizing input.</li>"
        "<li><b>Vol ratio</b> (20d avg volume / 60d avg): &gt;1.0 = expanding interest, "
        "conviction behind the move; feeds 10 of the 30 base points.</li>"
        "<li><b>%B</b> (position inside Bollinger Bands): &lt;0 below the lower band, "
        "0&ndash;1 inside, &gt;1.0 above the upper band = extended, rejected "
        "(don't chase). 0.5&ndash;0.9 earns +2 timing points: riding the band, not stretched.</li>"
        "<li><b>Band width</b> (% of middle band): no gate — context. Low = compression, "
        "high = expansion already underway.</li>"
        "<li><b>Squeeze \u25cf</b>: bandwidth at its 125-day minimum — volatility is coiled, "
        "expansion likely. Design stance: <i>wait</i> (scores 0; premium is cheap here, "
        "the worst time for a seller to get paid).</li>"
        "<li><b>vs Anchored VWAP</b> (% from VWAP anchored at the 52-week low): must be "
        "&ge;0. Negative = institutional money underwater — rejected for bullish income. "
        "0&ndash;3% above earns +2 timing points (tight to institutional support).</li>"
        "<li><b>Trend</b> (pivot structure): <b>UP</b> = rising swing highs <i>and</i> lows "
        "— authorizes selling puts. <b>RNG</b> = no structure — condor territory, harvest "
        "range premium. <b>DN</b> = falling highs and lows — bullish premium selling "
        "rejected. Uptrend earns +3 timing points.</li>"
        "<li><b>Cross</b>: <b>GC</b> = golden cross (SMA50 crossed above SMA200 within "
        "20 sessions): bullish regime confirmation, +2. <b>DC</b> = death cross: bearish, "
        "rejected. &mdash; = no cross in window.</li>"
        "<li><b>MACD hist</b> (12,26,9): MACD line minus signal. Positive (green) = bullish "
        "momentum, +1. Negative (red) = bearish momentum.</li>"
        "<li><b>Gap</b> (overnight, open vs prior close): &ge;+2% gap up (green), "
        "&le;&minus;2% gap down (red). Large gaps mean overnight news — check the "
        "catalyst before trusting the regime read.</li>"
        "<li><b>Momentum</b> (RSI state): <i>oversold</i> (RSI&lt;30), <i>overbought</i> "
        "(RSI&gt;70), else neutral. A state label, not a buy/sell signal — "
        "overbought names can stay overbought.</li>"
        "<li><b>Value</b> (% of 52-week range): &le;25% = beaten-down (technically "
        "undervalued), &ge;75% = priced at the top (technically overvalued). "
        "This is chart position, NOT fundamental valuation — the data feed has "
        "no earnings, P/E, or balance-sheet data.</li>"
        "<li><b>Bias</b> (trend composite, votes/6): price&gt;SMA50, price&gt;SMA200, "
        "SMA50&gt;SMA200, MACD hist&gt;0, RSI&gt;50, pivot trend UP. 4+ votes = "
        "bullish, &le;2 = bearish, else neutral.</li>"
        "<li><b>Score</b> (0&ndash;40): base 0&ndash;30 (regime: SMA position 10 + RSI "
        "sweet spot 10 + volume expansion 10) + signals 0&ndash;10 (timing: %B 2 + "
        "anchored VWAP 2 + trend 3 + golden cross 2 + MACD 1; squeeze 0). A pure "
        "ranking device — higher = more gates passed with better timing, not a "
        "probability or expected return.</li>"
        "</ul></details>"
    )
    readout = ""
    ro = data.get("readout") or []
    if ro:
        lines = "".join(f"<li>{esc(l)}</li>" for l in ro if isinstance(l, str))
        readout = f'<div class="readout"><div class="readout-title">Readout</div><ul>{lines}</ul></div>'
    return section("Stock screen", table + readout)


def considered_table(res, asof):
    """Issue #38: qualify-don't-filter. Every structure the screener
    evaluated, accepted or rejected, with its reasons. Proves the screen
    ran and shows what it looked at."""
    rows = []
    for sym in sorted(res):
        r = res[sym] or {}
        for c in r.get("considered") or []:
            c = c or {}
            qual = c.get("qualification") or ""
            qcls = "good" if qual == "accepted" else "bad" if qual == "rejected" else ""
            reasons = c.get("reasons") or []
            wings = (c.get("diagnostics") or {}).get("wings")
            strikes = wings or (
                f"{num(c.get('short_strike'), 0)}/{num(c.get('long_strike'), 0)}"
            )
            dte = dte_between(asof, c.get("expiration"))
            rows.append(
                "<tr>"
                f"{sym_cell(sym)}"
                f"<td>{esc(c.get('structure') or '')}</td>"
                f"<td class='num'>{esc(c.get('expiration') or '')}</td>"
                f"<td class='num'>{esc(strikes)}</td>"
                f"<td class='num'>{dte if dte is not None else '—'}</td>"
                f"<td class='{qcls}'>{esc(qual)}</td>"
                f"<td>{esc('; '.join(reasons) if reasons else '—')}</td>"
                "</tr>"
            )
    if not rows:
        return ""
    n_acc = sum(1 for sym in res for c in ((res[sym] or {}).get("considered") or [])
                if (c or {}).get("qualification") == "accepted")
    n_rej = len(rows) - n_acc
    return (
        "<h3>Considered structures "
        f"<span class='dim'>({len(rows)} evaluated: {n_acc} accepted, {n_rej} rejected)</span></h3>"
        '<div class="tbl-wrap"><table><thead><tr>'
        "<th title='Underlying symbol.'>Sym</th>"
        "<th title='Structure type evaluated.'>Structure</th>"
        "<th title='Option expiration date.'>Exp</th>"
        "<th title='Strikes evaluated (short/long).'>Strikes</th>"
        "<th title='Days to expiration.'>DTE</th>"
        "<th title='Whether the structure passed all gates.'>Qualification</th>"
        "<th title='Why a rejected structure failed. Empty means it passed.'>Reasons</th>"
        "</tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table></div>"
    )


def chain_table(res, asof):
    """Issue #38: raw option chain data. Every contract retrieved, with its
    quote and which gate it hit (or 'passed' for contracts that survived to
    evaluation). Data is never excluded from the report."""
    rows = []
    for sym in sorted(res):
        r = res[sym] or {}
        chain = r.get("chain") or []
        # Also include passed contracts that were evaluated
        seen = set()
        for c in chain:
            c = c or {}
            seen.add((c.get("expiration"), c.get("sym")))
            spread_pct = None
            if c.get("bid") and c.get("ask"):
                try:
                    mid = (c["bid"] + c["ask"]) / 2
                    spread_pct = (c["ask"] - c["bid"]) / mid if mid else None
                except (TypeError, ZeroDivisionError):
                    pass
            rows.append(
                "<tr>"
                f"{sym_cell(sym)}"
                f"<td>{esc(c.get('type') or '')}</td>"
                f"<td class='num'>{esc(c.get('expiration') or '')}</td>"
                f"<td class='num'>{num(c.get('strike'), 2)}</td>"
                f"<td class='num'>{num(c.get('bid'), 2)}</td>"
                f"<td class='num'>{num(c.get('ask'), 2)}</td>"
                f"<td class='num'>{pct((spread_pct or 0) * 100) if spread_pct is not None else '—'}</td>"
                f"<td class='num'>{c.get('open_interest') if c.get('open_interest') is not None else '—'}</td>"
                f"<td class='num'>{c.get('volume') if c.get('volume') is not None else '—'}</td>"
                f"<td class='bad'>{esc(c.get('gate') or '')}</td>"
                "</tr>"
            )
    if not rows:
        return ""
    return (
        "<h3>Option chain data "
        f"<span class='dim'>({len(rows)} contracts retrieved)</span></h3>"
        '<div class="tbl-wrap"><table><thead><tr>'
        "<th title='Underlying symbol.'>Sym</th>"
        "<th title='Put or call.'>Type</th>"
        "<th title='Option expiration date.'>Exp</th>"
        "<th title='Strike price.'>Strike</th>"
        "<th title='Bid price.'>Bid</th>"
        "<th title='Ask price.'>Ask</th>"
        "<th title='Bid-ask spread as % of midpoint.'>Spread%</th>"
        "<th title='Open interest.'>OI</th>"
        "<th title='Volume.'>Vol</th>"
        "<th title='Which gate rejected this contract, if any.'>Gate</th>"
        "</tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table></div>"
    )


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
            f"{sym_cell(sym)}"
            f"<td class='num'>{esc(r.get('expiration'))}</td>"
            f"<td class='num'>{num(r.get('short_strike'), 0)}/{num(r.get('long_strike'), 0)}P</td>"
            f"<td class='num'>{dte if dte is not None else '—'}</td>"
            f"<td class='num'>{money(r.get('credit_total'))}</td>"
            f"<td class='num'>{money(r.get('max_loss_total'))}</td>"
            f"<td class='num'>{num(r.get('breakeven'), 2)}</td>"
            f"<td class='num good'>{pct((r.get('return_on_risk') or 0) * 100)}</td>"
            f"<td class='num'>{pct((r.get('win_prob_est') or 0) * 100)}</td>"
            f"<td class='num'>{money(r.get('expected_value'))}</td>"
            f"<td class='num'>{num(r.get('loss_multiple'), 1)}×</td>"
            f"<td class='{'good' if (r.get('lucrative') in ('Lucrative','Solid')) else 'bad' if (r.get('lucrative') in ('Negative EV','High risk')) else ''}'>{esc(r.get('lucrative') or '—')}</td>"
            f"<td>{events_cell(r.get('events'))}</td>"
            "</tr>"
            + (f"<tr class='whyrow'><td colspan='12'>{esc(why)}</td></tr>" if why else "")
        )
    out.append("<h3>Bull put spreads <span class='dim'>(ranked by return on risk)</span></h3>")
    out.append(
        '<div class="tbl-wrap"><table><thead><tr>'
        "<th title='Underlying symbol. Click for quote pages.'>Sym</th>"
        "<th title='Option expiration date.'>Exp</th>"
        "<th title='Short put strike / long put strike (e.g. 205/200P). Width auto-scales to price ($1–$5).'>Strikes</th>"
        "<th title='Days to expiration. Gate: 21–60.'>DTE</th>"
        "<th title='Net credit received per spread: short bid minus long ask (conservative fill).'>Credit</th>"
        "<th title='Maximum loss per spread: width minus credit. Gate: at most $1000.'>Max loss</th>"
        "<th title='Breakeven at expiration: short strike minus credit per share.'>Breakeven</th><th title='Return on risk: credit / max loss. A screening ratio for ranking structures — not an expected or realized return.'>RoR</th>"
        "<th title='Estimated win probability: (1 - |short delta|). A delta-based estimate, not a market fact.'>Win%</th>"
        "<th title='Expected value: P(win)×credit − P(loss)×max loss. Delta-based estimate.'>EV$</th>"
        "<th title='Loss multiple: max loss ÷ credit. How many times the credit you risk.'>Loss×</th>"
        "<th title='Lucrative verdict: combines Win%, EV$, and Loss×. Lucrative = 70%+ win, positive EV, ≤3× loss. A screen, not a guarantee.'>Lucrative</th>"
        "<th title='Earnings or binary events inside the trade window: reject. Unknown earnings: flagged, not rejected.'>Events</th>"
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
            f"{sym_cell(sym)}"
            f"<td class='num'>{esc(r.get('expiration'))}</td>"
            f"<td class='num'>{num(pw[0] if len(pw) > 0 else None, 0)}/{num(pw[1] if len(pw) > 1 else None, 0)}P</td>"
            f"<td class='num'>{num(cw[0] if len(cw) > 0 else None, 0)}/{num(cw[1] if len(cw) > 1 else None, 0)}C</td>"
            f"<td class='num'>{dte if dte is not None else '—'}</td>"
            f"<td class='num'>{money(r.get('credit_total'))}</td>"
            f"<td class='num'>{money(r.get('max_loss_total'))}</td>"
            f"<td class='num'>{num(r.get('breakeven_put'), 2)} / {num(r.get('breakeven_call'), 2)}</td>"
            f"<td class='num good'>{pct((r.get('return_on_risk') or 0) * 100)}</td>"
            f"<td class='num'>{pct((r.get('win_prob_est') or 0) * 100)}</td>"
            f"<td class='num'>{money(r.get('expected_value'))}</td>"
            f"<td class='num'>{num(r.get('loss_multiple'), 1)}×</td>"
            f"<td class='{'good' if (r.get('lucrative') in ('Lucrative','Solid')) else 'bad' if (r.get('lucrative') in ('Negative EV','High risk')) else ''}'>{esc(r.get('lucrative') or '—')}</td>"
            f"<td>{events_cell(r.get('events'))}</td>"
            "</tr>"
            + (f"<tr class='whyrow'><td colspan='13'>{esc(why)}</td></tr>" if why else "")
        )
    out.append("<h3>Iron condors <span class='dim'>(ranked by return on risk)</span></h3>")
    out.append(
        '<div class="tbl-wrap"><table><thead><tr>'
        "<th title='Underlying symbol. Click for quote pages.'>Sym</th>"
        "<th title='Option expiration date.'>Exp</th>"
        "<th title='Put spread wing: short put strike / long put strike.'>Put wing</th>"
        "<th title='Call spread wing: short call strike / long call strike.'>Call wing</th>"
        "<th title='Days to expiration. Gate: 21–60.'>DTE</th>"
        "<th title='Net credit received: sum of both wing credits (short bid minus long ask each).'>Credit</th>"
        "<th title='Maximum loss: wider wing width minus credit. Gate: at most $1000.'>Max loss</th>"
        "<th title='Put breakeven / call breakeven at expiration.'>Breakevens</th><th title='Return on risk: credit / max loss. A screening ratio for ranking structures — not an expected or realized return.'>RoR</th>"
        "<th title='Estimated win probability: (1-|put delta|)×(1-|call delta|). Delta-based estimate.'>Win%</th>"
        "<th title='Expected value: P(win)×credit − P(loss)×max loss.'>EV$</th>"
        "<th title='Loss multiple: max loss ÷ credit.'>Loss×</th>"
        "<th title='Lucrative verdict: combines Win%, EV$, and Loss×. Lucrative = 70%+ win, positive EV, ≤3× loss. A screen, not a guarantee.'>Lucrative</th>"
        "<th title='Earnings or binary events inside the trade window: reject. Unknown earnings: flagged, not rejected.'>Events</th>"
        "</tr></thead><tbody>"
        + ("".join(rows) if rows else '<tr><td colspan="13" class="empty">No qualifying condors.</td></tr>')
        + "</tbody></table></div>"
    )
    # readout lines not tied to a symbol still get shown
    ac_rows, ac_syms = asym_condor_rows(data, asof, readout)
    if ac_rows:
        out.append("<h3>Asymmetric iron condors <span class='dim'>(defined-risk: put spread + far-OTM call wing, ranked by return on risk)</span></h3>")
        out.append(
            '<div class="tbl-wrap"><table><thead><tr>'
            "<th title='Underlying symbol. Click for quote pages.'>Sym</th>"
            "<th title='Option expiration date.'>Exp</th>"
            "<th title='Put spread wing: short put strike / long put strike.'>Put wing</th>"
            "<th title='Far-OTM call wing: short call strike / long call strike, at least 8% above spot.'>Call wing</th>"
            "<th title='Days to expiration. Gate: 21–60.'>DTE</th>"
            "<th title='Net credit received: put wing credit plus call wing credit.'>Credit</th>"
            "<th title='Maximum loss: put wing width minus credit. Gate: at most $1000.'>Max loss</th>"
            "<th title='Put breakeven / call breakeven at expiration.'>Breakevens</th>"
            "<th title='Call wing distance above spot (%). Gate: at least 8%.'>Up% dist</th><th title='Return on risk: credit / max loss. A screening ratio for ranking structures — not an expected or realized return.'>RoR</th>"
            "<th title='Estimated win probability: delta-based.'>Win%</th>"
            "<th title='Expected value: P(win)×credit − P(loss)×max loss.'>EV$</th>"
            "<th title='Loss multiple: max loss ÷ credit.'>Loss×</th>"
        "<th title='Lucrative verdict: combines Win%, EV$, and Loss×. Lucrative = 70%+ win, positive EV, ≤3× loss. A screen, not a guarantee.'>Lucrative</th>"
            "<th title='Earnings or binary events inside the trade window: reject. Unknown earnings: flagged, not rejected.'>Events</th>"
            "</tr></thead><tbody>"
            + "".join(ac_rows)
            + "</tbody></table></div>"
        )
    used = {why_for(sym, readout) for sym, _ in list(bps) + list(ics)}
    used |= {why_for(sym, readout) for sym in ac_syms}
    # Group readout into (header, bullets); a header whose bullets were all
    # consumed as why-rows under the tables is dropped so it isn't orphaned (#25).
    rest = []
    hdr, bullets = None, []
    def _flush():
        if bullets:
            if hdr is not None:
                rest.append(hdr)
            rest.extend(bullets)
        elif hdr is not None and hdr.startswith("No "):
            rest.append(hdr)  # "No X qualified" stands alone
    for l in readout:
        if not isinstance(l, str) or not l.strip() or l in used:
            continue
        if l.startswith("Top ") or l.startswith("No "):
            _flush()
            hdr, bullets = l, []
        else:
            bullets.append(l)
    _flush()
    if rest:
        lines = "".join(f"<li>{esc(l)}</li>" for l in rest)
        out.append(f'<div class="readout"><div class="readout-title">Readout</div><ul>{lines}</ul></div>')
    considered_html = considered_table(res, asof)
    if considered_html:
        out.append(considered_html)
    chain_html = chain_table(res, asof)
    if chain_html:
        out.append(chain_html)
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
            f"{sym_cell(sym)}"
            f"<td class='num'>{num(r.get('long_strike'), 0)}C / {num(r.get('short_strike'), 0)}C</td>"
            f"<td class='num'>{num(r.get('premium_to_debit_30d'), 2)}%</td>"
            f"<td class='num'>{money(r.get('capital'))}</td>"
            f"<td class='num'>{pct((r.get('breach_vs_spot') or 0) * 100)}</td>"
            f"<td>{events_cell(r.get('events'))}</td>"
            "</tr>"
        )
    body = (
        '<div class="tbl-wrap"><table><thead><tr>'
        "<th title='Underlying symbol. Click for quote pages.'>Sym</th>"
        "<th title='LEAPS long-call strike / short-call strike.'>Long / Short</th>"
        "<th title='Premium-to-debit ratio over 30 days (%). Qualifier gate: at least 4.0.'>P/D 30d</th>"
        "<th title='Capital required for the PMCC position.'>Capital</th>"
        "<th title='Breakeven distance above spot (%). Qualifier gate: within 8%.'>Breach</th>"
        "<th title='Earnings or binary events: any flag disqualifies.'>Events</th>"
        "</tr></thead><tbody>"
        + ("".join(rows) if rows else
           '<tr><td colspan="6" class="empty">No qualifiers — baseline set or nothing meeting entry gates.</td></tr>')
        + "</tbody></table></div>"
    )
    return section("PMCC watch", body)


def method_section(config_path=None):
    """Methodology card: pattern-identification criteria + how each strategy
    earns. Thresholds read live from gates.yaml so the report never drifts
    from the config the screeners actually ran with."""
    import gates as _g
    G = _g.load(config_path)
    st, sp, dt, v, pm = G["stock"], G["spreads"], G["premarket"], G["vol"], G["pmcc"]

    pats = [
        ("UP regime", "trend supports selling puts",
         f"price &gt; SMA{st['sma_fast']} &amp; SMA{st['sma_slow']}, above anchored VWAP "
         f"(52w low), no downtrend pivot structure"),
        ("Timing OK", "not chasing, not dead",
         f"RSI {st['rsi_min']:.0f}&ndash;{st['rsi_max']:.0f}, %B within "
         f"{st['bb_pctb_min']:.0f}&ndash;{st['bb_pctb_max']:.0f} "
         f"(%B&gt;1 = extended, reject), no {st['squeeze_lookback']}-day squeeze, "
         f"MACD hist &gt; 0, no death cross"),
        ("Golden cross", "bullish regime confirmation",
         f"SMA{st['sma_fast']} crossed above SMA{st['sma_slow']} within "
         f"{st['cross_lookback']:.0f} sessions (+2 timing)"),
        ("Day-trade momentum", "abnormal morning move",
         f"|gap| &ge; {dt['gap_min_pct']:.0f}%, rel volume &ge; {dt['rel_vol_min']:.1f}&times;, "
         "developing-VWAP side sets gap-and-go vs fade bias"),
        ("Vol regime: rich", "premium worth selling",
         f"IV rank &gt; {v['ivr_sell']:.0f} and IV &gt; {v['hv_short']}-day HV"),
        ("Vol regime: cheap", "premium not worth selling",
         f"IV rank &lt; {v['ivr_stand_down']:.0f} &rarr; stand down "
         "(structures vetoed, none shown)"),
    ]
    prows = "".join(
        f"<tr><td class='sym'>{p}</td><td>{m}</td><td>{c}</td></tr>"
        for p, m, c in pats)

    strs = [
        ("Bull put spread",
         f"short {sp['short_delta_min']:.2f}&ndash;{sp['short_delta_max']:.2f}&Delta; put + "
         f"long lower-strike put, {sp['dte_min']}&ndash;{sp['dte_max']} DTE",
         "keeps the net credit (short bid &minus; long ask) if the underlying stays "
         "above the short strike &mdash; harvests time decay and the premium "
         "difference between the two strikes"),
        ("Iron condor",
         "bull put spread + bear call spread, same expiry",
         "keeps both credits if the underlying pins between the short strikes "
         "&mdash; harvests premium from range-bound price action on both sides"),
        ("Asymmetric iron condor",
         f"bull put spread + far-OTM call wing (&ge;{sp['call_distance_min']:.0%} above spot)",
         "bullish tilt; the call wing's premium helps finance the put spread"),
        ("PMCC",
         f"{pm['long_delta_min']:.2f}&ndash;{pm['long_delta_max']:.2f}&Delta; LEAPS "
         f"({pm['long_dte_min']}&ndash;{pm['long_dte_max']} DTE) + "
         f"{pm['short_delta_min']:.2f}&ndash;{pm['short_delta_max']:.2f}&Delta; short calls "
         f"({pm['short_dte_min']}&ndash;{pm['short_dte_max']} DTE)",
         "harvests repeated short-call premium against durable delta exposure, "
         "at a fraction of 100-share capital"),
    ]
    srows = "".join(
        f"<tr><td class='sym'>{n}</td><td>{s}</td><td>{e}</td></tr>"
        for n, s, e in strs)

    return section(
        "Methodology &mdash; patterns and strategies",
        "<h3>How patterns are identified</h3>"
        '<div class="tbl-wrap"><table><thead><tr>'
        "<th>Pattern</th><th>What it means</th><th>Criteria (all must hold)</th>"
        "</tr></thead><tbody>" + prows + "</tbody></table></div>"
        "<h3>How the strategies generate income</h3>"
        '<div class="tbl-wrap"><table><thead><tr>'
        "<th>Strategy</th><th>Structure</th><th>The edge it harvests</th>"
        "</tr></thead><tbody>" + srows + "</tbody></table></div>"
        '<p class="fine">Every structure is defined-risk &mdash; max loss is known '
        "before entry, no naked legs. &ldquo;Return on risk&rdquo; (credit &divide; max "
        "loss) is a screening ratio, not a forecast. Thresholds above are the live "
        "values from <span class='num'>gates.yaml</span>.</p>",
    )


def catalyst_section(news_data, symbols):
    """Per-ticker headline watch (issue #21). Only tickers present in the
    report are shown; missing/empty news degrades to nothing."""
    if not news_data or not symbols:
        return ""
    tickers = news_data.get("tickers") or {}
    blocks = []
    for sym in symbols:
        heads = tickers.get(sym) or []
        if not heads:
            continue
        items = "".join(
            f"<li><a href=\"{esc(h['link'])}\" target=\"_blank\" rel=\"noopener\">"
            f"{esc(h['title'])}</a>"
            f"<span class=\"dim\"> — {esc(h.get('source') or '')}</span></li>"
            for h in heads[:3]
        )
        blocks.append(
            f"<div class=\"news-ticker\"><h4>{sym_cell(sym)}</h4><ul>{items}</ul></div>"
        )
    if not blocks:
        return ""
    fetched = esc((news_data.get("fetched_at") or "")[:16].replace("T", " "))
    return (
        "<section class=\"card\"><h2>Catalyst watch</h2>"
        f"<p class=\"dim\">Headlines from the morning fetch ({fetched} UTC) — "
        "check these before trusting any regime read or pricing a structure.</p>"
        + "".join(blocks) + "</section>"
    )


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


def bias_badge(bias):
    b = (bias or "").lower()
    if "gap-and-go" in b:
        cls = "good"
    elif "fade" in b:
        cls = "warn"
    else:
        cls = ""
    return f'<span class="badge {cls}">{esc(bias) or "—"}</span>'


def premarket_section(data, report_mode=False):
    if not data:
        if report_mode:
            return ""
        return section("Pre-market gap screen", '<p class="empty">No data yet — run the pre-market screener.</p>')
    cands = sorted(data.get("candidates") or [],
                   key=lambda c: -((c.get("conviction") or 0)
                                   if isinstance(c.get("conviction"), (int, float)) else -1))
    rows = []
    for c in cands:
        rows.append(
            "<tr>"
            f"{sym_cell(c.get('symbol'))}"
            f"<td class='num'>{num(c.get('price'), 2)}</td>"
            f"<td class='num'>{num(c.get('gap_pct'), 2, '%')}</td>"
            f"<td class='num'>{num(c.get('rel_vol'), 1)}×</td>"
            f"<td class='num'>{num(c.get('vwap_dist_pct'), 2, '%')}</td>"
            f"<td class='num'>{num(c.get('atr_pct'), 2, '%')}</td>"
            f"<td>{bias_badge(c.get('bias'))}</td>"
            "</tr>"
        )
    table = (
        '<div class="tbl-wrap"><table><thead><tr>'
        "<th title='Underlying symbol. Click for quote pages.'>Symbol</th>"
        "<th title='Last price at screen time.'>Price</th>"
        "<th title='Overnight gap: (open / prior close − 1). Gate: at least 2% in either direction.'>Gap%</th>"
        "<th title='Pre-market volume vs its recent average. Gate: at least 1.5×.'>RelVol</th>"
        "<th title='Distance from the developing session VWAP (%). Sets gap-and-go vs fade bias.'>VWAP dist</th>"
        "<th title='Average True Range as % of price. Gate: 1–8%.'>ATR%</th>"
        "<th title='Gap-and-go vs fade bias from the developing-VWAP side. Not a prediction.'>Bias</th>"
        "</tr></thead><tbody>"
        + ("".join(rows) if rows else
           '<tr><td colspan="7" class="empty">No gap candidates — quiet pre-market.</td></tr>')
        + "</tbody></table></div>"
    )
    # Near-misses: rejected but close — explains an empty table (#26)
    near = data.get("near_misses") or []
    near_html = ""
    if near:
        nrows = []
        for n in near:
            missed = "; ".join(n.get("missed") or [])
            nrows.append(
                "<tr>"
                f"{sym_cell(n.get('symbol'))}"
                f"<td class='num'>{num(n.get('price'), 2)}</td>"
                f"<td class='num'>{num(n.get('gap_pct'), 2, '%')}</td>"
                f"<td class='num'>{num(n.get('rel_vol'), 1)}×</td>"
                f"<td class='num'>{num(n.get('atr_pct'), 2, '%')}</td>"
                f"<td>{esc(missed)}</td>"
                "</tr>"
            )
        near_html = (
            "<h3>Near-misses <span class='dim'>(rejected but close — what almost qualified)</span></h3>"
            '<div class="tbl-wrap"><table><thead><tr>'
            "<th>Symbol</th><th>Price</th><th>Gap%</th><th>RelVol</th>"
            "<th>ATR%</th><th>Missed gate</th>"
            "</tr></thead><tbody>" + "".join(nrows) + "</tbody></table></div>"
        )
    ro = data.get("readout") or []
    readout = ""
    if ro:
        lines = "".join(f"<li>{esc(l)}</li>" for l in ro if isinstance(l, str))
        readout = f'<div class="readout"><div class="readout-title">Readout</div><ul>{lines}</ul></div>'
    settings = data.get("settings") or {}
    fine = (
        '<p class="fine">Ranked by conviction = |gap| × relative volume. '
        f"Gates: gap ≥ {esc(settings.get('gap_min_pct', 2))}%, "
        f"rel vol ≥ {esc(settings.get('rel_vol_min', 1.5))}×, "
        f"price ≥ ${esc(settings.get('price_min', 10))}, "
        f"ATR% {esc(settings.get('atr_pct_min', 1))}–{esc(settings.get('atr_pct_max', 8))}. "
        "Technical-only — check headlines before trading any candidate. "
        "Bias is not a prediction.</p>"
    )
    return section("Pre-market gap screen", table + near_html + readout + fine)


def intraday_section(data, report_mode=False):
    """Intraday momentum screen table (#27)."""
    if not data:
        if report_mode:
            return ""
        return section("Intraday momentum screen",
                       '<p class="empty">No data yet — run the intraday screener.</p>')
    cands = sorted(data.get("candidates") or [],
                   key=lambda c: -((c.get("conviction") or 0)
                                   if isinstance(c.get("conviction"), (int, float)) else -1))
    rows = []
    for c in cands:
        sig = c.get("orb_signal") or c.get("vwap_signal") or "—"
        rows.append(
            "<tr>"
            f"{sym_cell(c.get('symbol'))}"
            f"<td class='num'>{num(c.get('price'), 2)}</td>"
            f"<td>{esc(sig)}</td>"
            f"<td class='num'>{num(c.get('rel_vol_tp'), 2)}×</td>"
            f"<td class='num'>{num(c.get('vwap_dist_pct'), 2, '%')}</td>"
            f"<td class='num'>{num(c.get('atr_pct'), 2, '%')}</td>"
            f"<td class='num'>{num(c.get('conviction'), 1)}</td>"
            f"<td>{bias_badge(c.get('bias'))}</td>"
            "</tr>"
        )
    table = (
        '<div class="tbl-wrap"><table><thead><tr>'
        "<th title='Underlying symbol. Click for quote pages.'>Symbol</th>"
        "<th title='Last price at screen time.'>Price</th>"
        "<th title='Fired signal: breakout_up / breakdown_down (15-min opening range), reclaim_up / loss_down (session VWAP cross).'>Signal</th>"
        "<th title='Today\u2019s volume so far vs 20-day average prorated by elapsed session time. Gate: at least 1.5\u00d7.'>RelVol TP</th>"
        "<th title='Distance from the session VWAP (%).'>VWAP dist</th>"
        "<th title='Average True Range as % of price. Gate: 1\u20138%.'>ATR%</th>"
        "<th title='Conviction score: (|breakout distance| + 0.5) \u00d7 time-prorated rel vol.'>Conviction</th>"
        "<th title='Bullish / bearish momentum from the fired signals. Not a prediction.'>Bias</th>"
        "</tr></thead><tbody>"
        + ("".join(rows) if rows else
           '<tr><td colspan="8" class="empty">No intraday momentum candidates.</td></tr>')
        + "</tbody></table></div>"
    )
    near = data.get("near_misses") or []
    near_html = ""
    if near:
        nrows = []
        for n in near:
            missed = "; ".join(n.get("missed") or [])
            nrows.append(
                "<tr>"
                f"{sym_cell(n.get('symbol'))}"
                f"<td>{esc(n.get('signal') or '—')}</td>"
                f"<td class='num'>{num(n.get('rel_vol_tp'), 2)}×</td>"
                f"<td class='num'>{num(n.get('vwap_dist_pct'), 2, '%')}</td>"
                f"<td>{esc(missed)}</td>"
                "</tr>"
            )
        near_html = (
            "<h3>Near-misses <span class='dim'>(signal fired, volume gate missed)</span></h3>"
            '<div class="tbl-wrap"><table><thead><tr>'
            "<th>Symbol</th><th>Signal</th><th>RelVol TP</th>"
            "<th>VWAP dist</th><th>Missed gate</th>"
            "</tr></thead><tbody>" + "".join(nrows) + "</tbody></table></div>"
        )
    settings = data.get("settings") or {}
    fine = (
        '<p class="fine">Signals: 15-min opening-range breakout/breakdown, '
        'session-VWAP reclaim/loss. '
        f"Gates: rel vol (time-prorated) ≥ {esc(settings.get('rel_vol_min', 1.5))}×, "
        f"price ≥ ${esc(settings.get('price_min', 10))}, "
        f"ATR% {esc(settings.get('atr_pct_min', 1))}–{esc(settings.get('atr_pct_max', 8))}. "
        "Technical-only — check headlines before trading any candidate. "
        "Bias is not a prediction.</p>"
    )
    return section("Intraday momentum screen", table + near_html + fine)


def wing_str(wing, suffix):
    """[38, 37] + 'P' -> '38/37P'; passes through an already-formatted string."""
    if isinstance(wing, str):
        return wing
    if isinstance(wing, (list, tuple)) and len(wing) >= 2:
        return f"{num(wing[0], 0)}/{num(wing[1], 0)}{suffix}"
    return "—"


def norm_asym_condor(r, stock=None):
    """Normalize a asym condor record across JSON shapes.

    New shape (list of records): stock, expiration, put_strikes "38/37P",
    call_strikes "46/47C", dte, credit, max_loss, downside_breakeven,
    upside_breakeven, upside_distance_pct, return_on_risk, events.
    Old shape (dict keyed by symbol): put_wing/call_wing lists, credit_total,
    max_loss_total, breakeven_put/breakeven_call.
    """
    r = r or {}
    return {
        "stock": r.get("stock") or stock,
        "expiration": r.get("expiration"),
        "put_strikes": r.get("put_strikes") or wing_str(r.get("put_wing"), "P"),
        "call_strikes": r.get("call_strikes") or wing_str(r.get("call_wing"), "C"),
        "dte": r.get("dte"),
        "credit": r.get("credit", r.get("credit_total")),
        "max_loss": r.get("max_loss", r.get("max_loss_total")),
        "downside_breakeven": r.get("downside_breakeven", r.get("breakeven_put")),
        "upside_breakeven": r.get("upside_breakeven", r.get("breakeven_call")),
        "upside_distance_pct": r.get("upside_distance_pct"),
        "return_on_risk": r.get("return_on_risk"),
        "win_prob_est": r.get("win_prob_est"),
        "expected_value": r.get("expected_value"),
        "loss_multiple": r.get("loss_multiple"),
        "lucrative": r.get("lucrative"),
        "events": r.get("events"),
        "why_key": r.get("stock") or stock,
    }


def asym_condor_rows(data, asof, readout):
    """(rows, symbols) for the Asymmetric iron condor table; ([], []) when none present."""
    res = (data or {}).get("results") or {}
    # Backward compat: JSONs generated before the rename used "jade_lizards".
    raw = res.get("asym_condors") or res.get("jade_lizards") or []
    if isinstance(raw, dict):
        ac_list = [norm_asym_condor(r, stock=sym) for sym, r in raw.items()]
    else:
        ac_list = [norm_asym_condor(r) for r in raw]
    ac_list.sort(key=lambda r: -((r.get("return_on_risk") or -1)
                                 if isinstance(r.get("return_on_risk"), (int, float)) else -1))
    rows = []
    for r in ac_list:
        dte = r.get("dte")
        if dte is None:
            dte = dte_between(asof, r.get("expiration"))
        why = why_for(r.get("why_key"), readout)
        rows.append(
            "<tr>"
            f"{sym_cell(r.get('stock'))}"
            f"<td class='num'>{esc(r.get('expiration'))}</td>"
            f"<td class='num'>{esc(r.get('put_strikes'))}</td>"
            f"<td class='num'>{esc(r.get('call_strikes'))}</td>"
            f"<td class='num'>{dte if dte is not None else '—'}</td>"
            f"<td class='num'>{money(r.get('credit'))}</td>"
            f"<td class='num'>{money(r.get('max_loss'))}</td>"
            f"<td class='num'>{num(r.get('downside_breakeven'), 2)} / {num(r.get('upside_breakeven'), 2)}</td>"
            f"<td class='num'>{pct(r.get('upside_distance_pct'))}</td>"
            f"<td class='num good'>{pct((r.get('return_on_risk') or 0) * 100)}</td>"
            f"<td class='num'>{pct((r.get('win_prob_est') or 0) * 100)}</td>"
            f"<td class='num'>{money(r.get('expected_value'))}</td>"
            f"<td class='num'>{num(r.get('loss_multiple'), 1)}×</td>"
            f"<td class='{'good' if (r.get('lucrative') in ('Lucrative','Solid')) else 'bad' if (r.get('lucrative') in ('Negative EV','High risk')) else ''}'>{esc(r.get('lucrative') or '—')}</td>"
            f"<td>{events_cell(r.get('events'))}</td>"
            "</tr>"
            + (f"<tr class='whyrow'><td colspan='14'>{esc(why)}</td></tr>" if why else "")
        )
    return rows, [r.get("why_key") for r in ac_list if r.get("why_key")]


# ---------------------------------------------------------------- report mode

REPORT_TITLES = {
    "daily": "Options Lab — Daily Screen",
    "premarket": "Options Lab — Pre-market Gap Screen",
    "intraday": "Options Lab — Intraday Momentum Screen",
    "pmcc": "Options Lab — PMCC Screen",
}

SOURCE_LABELS = {
    "nasdaq100": "Nasdaq-100",
    "sp500": "S&P 500",
    "sp100": "S&P 100",
    "dow30": "Dow 30",
    "watchlist": "Watchlist",
    "custom": "Custom",
}


def source_label(key):
    if not key:
        return ""
    return SOURCE_LABELS.get(key, str(key).replace("_", " ").title())


def resolve_docs_dir():
    """Find the docs/ dir: repo root is the parent of src/ (or CWD in CI)."""
    here = os.path.dirname(os.path.abspath(__file__))
    for cand in (os.path.join(here, "..", "docs"),
                 os.path.join(here, "docs"),
                 os.path.join("docs")):
        if os.path.isdir(cand):
            return os.path.normpath(cand)
    return os.path.normpath(os.path.join(here, "..", "docs"))


def parse_report_id(rid):
    """daily-nasdaq100-2026-10-11 -> ("daily", "nasdaq100", "2026-10-11").

    Old two-segment ids (daily-2026-10-11, pmcc-2026-10) yield source=None;
    disambiguated by checking whether the middle segment is a known source
    key or the remainder looks like a date.
    """
    parts = (rid or "").split("-", 2)
    rtype = parts[0] or "report"
    if len(parts) < 3:
        return rtype, None, parts[1] if len(parts) > 1 else ""
    cand, rest = parts[1], parts[2]
    if cand in SOURCE_LABELS or re.fullmatch(r"\d{4}(-\d{2}){1,2}", rest or ""):
        return rtype, cand, rest
    return rtype, None, f"{cand}-{rest}"


def sorted_passing(stock):
    return sorted((stock or {}).get("passing", []),
                  key=lambda p: -(p.get("score") if isinstance(p.get("score"), (int, float)) else -1))


def plural(n, word):
    return f"{n} {word}" + ("" if n == 1 else "s")


def spread_bits(spreads):
    res = (spreads or {}).get("results") or {}
    bits = []
    n = len(res.get("bull_puts") or {})
    if n:
        bits.append(plural(n, "bull put"))
    n = len(res.get("iron_condors") or {})
    if n:
        bits.append(plural(n, "condor"))
    n = len(res.get("asym_condors") or {})
    if n:
        bits.append(plural(n, "asym condor"))
    return bits


def build_blurb(rtype, stock, spreads, pmcc, premarket, intraday=None):
    if rtype == "premarket":
        cands = (premarket or {}).get("candidates") or []
        if not cands:
            return "No qualifiers — quiet screen"
        gg = sum(1 for c in cands if "gap-and-go" in ((c or {}).get("bias") or ""))
        return f"{plural(len(cands), 'gap candidate')}, {gg} with gap-and-go bias"
    if rtype == "intraday":
        cands = (intraday or {}).get("candidates") or []
        if not cands:
            return "No qualifiers — quiet screen"
        bull = sum(1 for c in cands if ((c or {}).get("bias") or "").startswith("bullish"))
        return f"{plural(len(cands), 'momentum candidate')}, {bull} bullish"
    if rtype == "pmcc":
        n = len((pmcc or {}).get("pairs") or {})
        return plural(n, "qualifying pair") if n else "No qualifiers — baseline"
    # daily and anything else
    parts = []
    passing = sorted_passing(stock)
    if passing:
        lead = passing[0]
        try:
            parts.append(f"{lead.get('symbol')} {float(lead.get('score')):.1f} leads")
        except (TypeError, ValueError):
            parts.append(f"{lead.get('symbol')} leads")
    bits = spread_bits(spreads)
    if bits:
        parts.append(", ".join(bits))
    if not parts:
        return "No qualifiers — quiet screen"
    return "; ".join(parts)


def build_stats(rtype, stock, spreads, pmcc, premarket, intraday=None):
    if rtype == "premarket":
        cands = (premarket or {}).get("candidates") or []
        gg = sum(1 for c in cands if "gap-and-go" in ((c or {}).get("bias") or ""))
        return {"candidates": len(cands), "gap_and_go": gg,
                "screened": (premarket or {}).get("universe")}
    if rtype == "intraday":
        cands = (intraday or {}).get("candidates") or []
        return {"candidates": len(cands),
                "screened": (intraday or {}).get("universe")}
    if rtype == "pmcc":
        return {"pairs": len((pmcc or {}).get("pairs") or {})}
    res = (spreads or {}).get("results") or {}
    return {
        "stocks": len((stock or {}).get("passing") or []),
        "bull_puts": len(res.get("bull_puts") or {}),
        "iron_condors": len(res.get("iron_condors") or {}),
        "asym_condors": len(res.get("asym_condors") or {}),
        "pmcc_pairs": len((pmcc or {}).get("pairs") or {}),
    }


def write_meta_sidecar(html_path, rid, rtype, rdate, title, blurb, stats,
                       source=None, source_detail=None):
    meta = {"id": rid, "type": rtype, "date": rdate, "title": title,
            "blurb": blurb, "stats": stats,
            "source": source, "source_detail": source_detail}
    meta_path = os.path.splitext(html_path)[0] + ".meta.json"
    with open(meta_path, "w") as f:
        json.dump(meta, f, indent=1)
    print(f"wrote {meta_path}")
    return meta_path

BACKLINK_CSS = """
.backlink{margin:0 0 14px;font-size:.9rem}
.backlink a{color:var(--blue);text-decoration:none}
.backlink a:hover{text-decoration:underline}
.prov{font-size:.9rem;color:var(--dim);margin:6px 0 0}
.prov b{color:var(--text)}
"""

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
.sym .ticker{color:var(--text);text-decoration:none}
.sym .ticker:hover{color:var(--blue);text-decoration:underline}
details.qlinks{display:inline-block;margin-left:5px;vertical-align:middle;font-weight:400}
details.qlinks summary{cursor:pointer;list-style:none;color:var(--dim);font-size:.68rem;
padding:1px 5px;border-radius:4px;line-height:1.5}
details.qlinks summary::-webkit-details-marker{display:none}
details.qlinks summary:hover{background:#21262d;color:var(--text)}
.qmenu{margin-top:5px;border-top:1px solid var(--border);padding-top:5px}
.qmenu a{display:block;padding:4px 8px;font-size:.78rem;color:var(--text);
text-decoration:none;border-radius:4px;white-space:nowrap}
.qmenu a:hover{background:#1c2128;color:var(--blue)}
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
ul.guide{columns:2;column-gap:32px;font-size:.82rem;list-style:none;margin:10px 0 0;padding:0}
ul.guide li{margin:0 0 8px;break-inside:avoid}
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
<title>{title}</title>
<style>{css}</style>
</head>
<body>
<div class="wrap">
{backlink}
<header>
<h1>{title}</h1>
{provline}
<p class="sub">All figures computed from Public.com API data in-run. Credits use conservative short-bid minus long-ask fills.</p>
</header>
<section class="card"><h2>How a trade gets made</h2>{flow}</section>
{method}
{stock}
{spreads}
{premarket}
{intraday}
{pmcc}
{rejections}
{catalyst}
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
    ap.add_argument("--premarket", default=None)
    ap.add_argument("--intraday", default=None)
    ap.add_argument("--report-id", default=None,
                    help="e.g. daily-nasdaq100-2026-10-13: write to docs/reports/<id>.html + .meta.json sidecar")
    ap.add_argument("--source", default=None,
                    help="report source key: watchlist|nasdaq100|sp100|sp500|dow30|custom (authoritative over --report-id)")
    ap.add_argument("--source-detail", default=None,
                    help='e.g. "101 names"')
    ap.add_argument("--config", default=None,
                    help="path to gates.yaml (default: gates.yaml next to the script); "
                         "keeps the methodology section in sync with a custom screener config")
    ap.add_argument("--news", default=None,
                    help="path to fetch_news.py output JSON for the Catalyst watch section")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    report_mode = bool(args.report_id)
    docs_dir = resolve_docs_dir()

    stock = load_json(args.stock)
    spreads = load_json(args.spreads)
    pmcc = load_json(args.pmcc)
    premarket = load_json(args.premarket)
    intraday = load_json(args.intraday)
    news = load_json(args.news)

    if report_mode:
        rid = args.report_id
        rtype, id_source, rdate = parse_report_id(rid)
        source = args.source or id_source
        source_detail = args.source_detail
        title = REPORT_TITLES.get(rtype, "Options Lab — Screen")
        out = args.out or os.path.join(docs_dir, "reports", rid + ".html")
        hub = os.path.join(docs_dir, "index.html")
        back_href = esc(os.path.relpath(hub, start=os.path.dirname(os.path.abspath(out))))
        backlink = f'<p class="backlink"><a href="{back_href}">← Back to hub</a></p>'
        css = CSS + BACKLINK_CSS
        rdate = rdate or str((stock or {}).get("asof") or (premarket or {}).get("run") or (intraday or {}).get("run") or "undated")
    else:
        title = "Options Lab — Daily Screen"
        out = args.out or "docs/index.html"
        backlink = ""
        css = CSS
        source = source_detail = None

    asof = (stock or {}).get("asof") or (spreads or {}).get("asof") \
        or (pmcc or {}).get("asof") or (premarket or {}).get("run") or (intraday or {}).get("run") or "unknown"

    if source:
        bits = [f"Source: <b>{esc(source_label(source))}</b>"]
        if source_detail:
            bits.append(esc(source_detail))
        bits.append(f"Run {esc(asof)}")
        provline = f'<p class="prov">{" · ".join(bits)}</p>'
    else:
        provline = f'<p class="sub">Run date: {esc(asof)}</p>'

    stock_html = stock_section(stock) if (stock or not report_mode) else ""
    spreads_html = spread_tables(spreads) if (spreads or not report_mode) else ""
    pmcc_html = pmcc_section(pmcc) if (pmcc or not report_mode) else ""
    premarket_html = premarket_section(premarket, report_mode) if premarket else ""
    intraday_html = intraday_section(intraday, report_mode) if intraday else ""
    passing_syms = [p.get("symbol") for p in (stock or {}).get("passing", [])
                    if p.get("symbol")]
    catalyst_html = catalyst_section(news, passing_syms)

    page = PAGE.format(
        css=css,
        title=esc(title),
        backlink=backlink,
        provline=provline,
        flow=workflow_strip(),
        method=method_section(args.config),
        stock=stock_html,
        spreads=spreads_html,
        premarket=premarket_html,
        intraday=intraday_html,
        pmcc=pmcc_html,
        rejections=rejections_section(stock),
        catalyst=catalyst_html,
        now=esc(dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")),
    )
    outdir = os.path.dirname(os.path.abspath(out))
    os.makedirs(outdir, exist_ok=True)
    with open(out, "w") as f:
        f.write(page)
    print(f"wrote {out} ({os.path.getsize(out)} bytes)")

    if report_mode:
        blurb = build_blurb(rtype, stock, spreads, pmcc, premarket, intraday)
        stats = build_stats(rtype, stock, spreads, pmcc, premarket, intraday)
        write_meta_sidecar(out, rid, rtype, rdate,
                           f"{title} · {rdate}", blurb, stats,
                           source=source, source_detail=source_detail)


if __name__ == "__main__":
    main()
