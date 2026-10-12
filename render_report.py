#!/usr/bin/env python3
"""Render screener JSON outputs into single-file HTML pages.

Legacy hub mode (unchanged):
    python3 render_report.py --stock reports/stock-screen.json \
        --spreads reports/spread-screen.json --pmcc reports/pmcc.json \
        --out docs/index.html

Report mode (dated, non-overwriting, archived forever):
    python3 render_report.py --stock ... --spreads ... \
        --report-id daily-nasdaq100-2026-10-11 --source nasdaq100 --source-detail "101 names"
    python3 render_report.py --daytrade reports/daytrade.json \
        --report-id daytrade-sp500-2026-10-13 --source sp500 --source-detail "503 names"
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
            f"<td class='num'><b>{num(p.get('score'))}</b><span class='dim'>/37</span></td>"
            "</tr>"
        )
    table = (
        '<div class="tbl-wrap"><table><thead><tr>'
        "<th>Symbol</th><th>Price</th>"
        "<th title='RSI(14): momentum oscillator 0-100. Gate keeps 30-70; "
        "below 30 = washed out, above 70 = overheated.'>RSI(14)</th>"
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
        "<th>Trend</th><th>Score</th>"
        "</tr></thead><tbody>"
        + ("".join(rows) if rows else '<tr><td colspan="9" class="empty">No qualifiers this run.</td></tr>')
        + "</tbody></table></div>"
        '<p class="fine"><b>Column guide.</b> '
        "<b>%B</b> — price position inside Bollinger Bands (0 lower, 1 upper); "
        "timing: &gt;1.0 is extended, rejected. "
        "<b>Band width</b> — band width as % of the middle band; low reads as compression. "
        "<b>Squeeze \u25cf</b> — bandwidth at its 125-day low: volatility is coiled, "
        "expansion likely &mdash; wait, do not enter. "
        "<b>vs Anchored VWAP</b> — distance from VWAP anchored at the 52-week low; "
        "regime: below it means institutional money is underwater, rejected for bullish income. "
        "<b>Score</b> — composite 0&ndash;37: base 0&ndash;30 (regime) + signals 0&ndash;7 (timing).</p>"
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
        "<th>Max loss</th><th>Breakeven</th><th title='Return on risk: credit / max loss. A screening ratio for ranking structures — not an expected or realized return.'>RoR</th><th>Events</th>"
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
        "<th>Credit</th><th>Max loss</th><th>Breakevens</th><th title='Return on risk: credit / max loss. A screening ratio for ranking structures — not an expected or realized return.'>RoR</th><th>Events</th>"
        "</tr></thead><tbody>"
        + ("".join(rows) if rows else '<tr><td colspan="10" class="empty">No qualifying condors.</td></tr>')
        + "</tbody></table></div>"
    )
    # readout lines not tied to a symbol still get shown
    ac_rows, ac_syms = asym_condor_rows(data, asof, readout)
    if ac_rows:
        out.append("<h3>Asymmetric iron condors <span class='dim'>(defined-risk: put spread + far-OTM call wing, ranked by return on risk)</span></h3>")
        out.append(
            '<div class="tbl-wrap"><table><thead><tr>'
            "<th>Sym</th><th>Exp</th><th>Put wing</th><th>Call wing</th><th>DTE</th>"
            "<th>Credit</th><th>Max loss</th><th>Breakevens</th><th>Up% dist</th><th title='Return on risk: credit / max loss. A screening ratio for ranking structures — not an expected or realized return.'>RoR</th><th>Events</th>"
            "</tr></thead><tbody>"
            + "".join(ac_rows)
            + "</tbody></table></div>"
        )
    used = {why_for(sym, readout) for sym, _ in list(bps) + list(ics)}
    used |= {why_for(sym, readout) for sym in ac_syms}
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


def method_section(config_path=None):
    """Methodology card: pattern-identification criteria + how each strategy
    earns. Thresholds read live from gates.yaml so the report never drifts
    from the config the screeners actually ran with."""
    import gates as _g
    G = _g.load(config_path)
    st, sp, dt, v, pm = G["stock"], G["spreads"], G["daytrade"], G["vol"], G["pmcc"]

    pats = [
        ("UP regime", "trend supports selling puts",
         f"price &gt; SMA{st['sma_fast']} &amp; SMA{st['sma_slow']}, above anchored VWAP "
         f"(52w low), no downtrend pivot structure"),
        ("Timing OK", "not chasing, not dead",
         f"RSI {st['rsi_min']:.0f}&ndash;{st['rsi_max']:.0f}, %B within "
         f"{st['bb_pctb_min']:.0f}&ndash;{st['bb_pctb_max']:.0f} "
         f"(%B&gt;1 = extended, reject), no {st['squeeze_lookback']}-day squeeze"),
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


def daytrade_section(data, report_mode=False):
    if not data:
        if report_mode:
            return ""
        return section("Day-trade screen", '<p class="empty">No data yet — run the day-trade screener.</p>')
    cands = sorted(data.get("candidates") or [],
                   key=lambda c: -((c.get("conviction") or 0)
                                   if isinstance(c.get("conviction"), (int, float)) else -1))
    rows = []
    for c in cands:
        rows.append(
            "<tr>"
            f"<td class='sym'>{esc(c.get('symbol'))}</td>"
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
        "<th>Symbol</th><th>Price</th><th>Gap%</th><th>RelVol</th>"
        "<th>VWAP dist</th><th>ATR%</th><th>Bias</th>"
        "</tr></thead><tbody>"
        + ("".join(rows) if rows else
           '<tr><td colspan="7" class="empty">No gap candidates — quiet pre-market.</td></tr>')
        + "</tbody></table></div>"
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
    return section("Day-trade screen", table + readout + fine)


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
            f"<td class='sym'>{esc(r.get('stock'))}</td>"
            f"<td class='num'>{esc(r.get('expiration'))}</td>"
            f"<td class='num'>{esc(r.get('put_strikes'))}</td>"
            f"<td class='num'>{esc(r.get('call_strikes'))}</td>"
            f"<td class='num'>{dte if dte is not None else '—'}</td>"
            f"<td class='num'>{money(r.get('credit'))}</td>"
            f"<td class='num'>{money(r.get('max_loss'))}</td>"
            f"<td class='num'>{num(r.get('downside_breakeven'), 2)} / {num(r.get('upside_breakeven'), 2)}</td>"
            f"<td class='num'>{pct(r.get('upside_distance_pct'))}</td>"
            f"<td class='num good'>{pct((r.get('return_on_risk') or 0) * 100)}</td>"
            f"<td>{events_cell(r.get('events'))}</td>"
            "</tr>"
            + (f"<tr class='whyrow'><td colspan='11'>{esc(why)}</td></tr>" if why else "")
        )
    return rows, [r.get("why_key") for r in ac_list if r.get("why_key")]


# ---------------------------------------------------------------- report mode

REPORT_TITLES = {
    "daily": "Options Lab — Daily Screen",
    "daytrade": "Options Lab — Day-Trade Screen",
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
    """Find the docs/ dir both locally (./repo/docs) and in CI (./docs)."""
    here = os.path.dirname(os.path.abspath(__file__))
    for cand in (os.path.join(here, "repo", "docs"), os.path.join(here, "docs")):
        if os.path.isdir(cand):
            return cand
    return os.path.join(here, "repo", "docs")


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


def build_blurb(rtype, stock, spreads, pmcc, daytrade):
    if rtype == "daytrade":
        cands = (daytrade or {}).get("candidates") or []
        if not cands:
            return "No qualifiers — quiet screen"
        gg = sum(1 for c in cands if "gap-and-go" in ((c or {}).get("bias") or ""))
        return f"{plural(len(cands), 'gap candidate')}, {gg} with gap-and-go bias"
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


def build_stats(rtype, stock, spreads, pmcc, daytrade):
    if rtype == "daytrade":
        cands = (daytrade or {}).get("candidates") or []
        gg = sum(1 for c in cands if "gap-and-go" in ((c or {}).get("bias") or ""))
        return {"candidates": len(cands), "gap_and_go": gg,
                "screened": (daytrade or {}).get("universe")}
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
{daytrade}
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
    ap.add_argument("--daytrade", default=None)
    ap.add_argument("--report-id", default=None,
                    help="e.g. daily-nasdaq100-2026-10-13: write to docs/reports/<id>.html + .meta.json sidecar")
    ap.add_argument("--source", default=None,
                    help="report source key: watchlist|nasdaq100|sp100|sp500|dow30|custom (authoritative over --report-id)")
    ap.add_argument("--source-detail", default=None,
                    help='e.g. "101 names"')
    ap.add_argument("--config", default=None,
                    help="path to gates.yaml (default: gates.yaml next to the script); "
                         "keeps the methodology section in sync with a custom screener config")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    report_mode = bool(args.report_id)
    docs_dir = resolve_docs_dir()

    stock = load_json(args.stock)
    spreads = load_json(args.spreads)
    pmcc = load_json(args.pmcc)
    daytrade = load_json(args.daytrade)

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
        rdate = rdate or str((stock or {}).get("asof") or (daytrade or {}).get("run") or "undated")
    else:
        title = "Options Lab — Daily Screen"
        out = args.out or "docs/index.html"
        backlink = ""
        css = CSS
        source = source_detail = None

    asof = (stock or {}).get("asof") or (spreads or {}).get("asof") \
        or (pmcc or {}).get("asof") or (daytrade or {}).get("run") or "unknown"

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
    daytrade_html = daytrade_section(daytrade, report_mode) if daytrade else ""

    page = PAGE.format(
        css=css,
        title=esc(title),
        backlink=backlink,
        provline=provline,
        flow=workflow_strip(),
        method=method_section(args.config),
        stock=stock_html,
        spreads=spreads_html,
        daytrade=daytrade_html,
        pmcc=pmcc_html,
        rejections=rejections_section(stock),
        now=esc(dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")),
    )
    outdir = os.path.dirname(os.path.abspath(out))
    os.makedirs(outdir, exist_ok=True)
    with open(out, "w") as f:
        f.write(page)
    print(f"wrote {out} ({os.path.getsize(out)} bytes)")

    if report_mode:
        blurb = build_blurb(rtype, stock, spreads, pmcc, daytrade)
        stats = build_stats(rtype, stock, spreads, pmcc, daytrade)
        write_meta_sidecar(out, rid, rtype, rdate,
                           f"{title} · {rdate}", blurb, stats,
                           source=source, source_detail=source_detail)


if __name__ == "__main__":
    main()
