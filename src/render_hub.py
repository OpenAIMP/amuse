#!/usr/bin/env python3
"""Build the docs/ report hub from report sidecars.

Scans docs/reports/*.meta.json and writes two pages:
  - docs/index.html:   the LATEST report per (workflow type, source) group
  - docs/archive.html: every report ever, grouped by workflow type and
    source, newest-first. Reports are never pruned — this is the full archive.

Usage:
    python3 render_hub.py [--docs docs]

Docs dir auto-detects: ./repo/docs locally, ./docs in CI.
Stdlib-only, inline CSS, no external assets. One inline script powers the
market-news live refresh widget (with a baked-in fallback).
"""
from __future__ import annotations

import argparse
import datetime as dt
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from render_report import (BACKLINK_CSS, CSS, WORKFLOW, esc, resolve_docs_dir,
                           source_label, workflow_strip)

TYPE_ORDER = ["daily", "premarket", "intraday", "pmcc"]
TYPE_LABELS = {
    "daily": "Daily screen",
    "premarket": "Pre-market gap",
    "intraday": "Intraday breakouts",
    "daytrade": "Pre-market gap (legacy)",
    "pmcc": "Monthly PMCC",
    "leverage": "Leveraged ETFs",
}
# preferred source order inside each type group; unknown keys go alphabetical
SOURCE_ORDER = ["watchlist", "nasdaq100", "sp100", "sp500", "dow30", "custom"]

HUB_CSS = """
.src-chip{font-size:.72rem;font-weight:700;background:rgba(88,166,255,.15);color:var(--blue);
border-radius:20px;padding:2px 10px;white-space:nowrap}
.repitem{background:#0d1117;border:1px solid var(--border);border-radius:8px;
padding:12px 14px;margin:10px 0}
.repitem-top{display:flex;align-items:center;gap:10px;flex-wrap:wrap}
.repitem-top .d{color:var(--dim);font-variant-numeric:tabular-nums;font-size:.85rem}
.repitem-top a{color:var(--blue);text-decoration:none;font-size:.85rem;margin-left:auto}
.repitem-top a:hover{text-decoration:underline}
.repitem-blurb{font-size:.9rem;margin:6px 0 4px}
.chips{display:flex;flex-wrap:wrap;gap:6px;margin:8px 0 2px}
.chip{font-size:.75rem;background:#161b22;border:1px solid var(--border);border-radius:20px;
padding:2px 10px;color:var(--dim);font-variant-numeric:tabular-nums}
.srcgroup{margin:14px 0 4px}
.srcgroup > h3{margin:14px 0 4px}
.news-list{margin:8px 0;padding-left:20px}
.news-list li{margin:5px 0;font-size:.9rem}
.refresh-btn{background:#161b22;border:1px solid var(--border);border-radius:6px;
color:var(--dim);cursor:pointer;font-size:.85rem;padding:1px 8px;margin-left:8px}
.refresh-btn:hover{color:var(--blue);border-color:var(--blue)}
"""


def load_metas(docs_dir):
    metas = []
    for path in glob.glob(os.path.join(docs_dir, "reports", "*.meta.json")):
        try:
            with open(path) as f:
                m = json.load(f)
        except (OSError, ValueError) as e:
            print(f"warning: skipping {path}: {e}", file=sys.stderr)
            continue
        if isinstance(m, dict) and m.get("id"):
            metas.append(m)
    return metas


def type_label(t):
    return TYPE_LABELS.get(t, t.replace("_", " ").title())


def source_group_label(src):
    return source_label(src) if src else "Unknown"


def ordered_sources(by_source):
    known = [s for s in SOURCE_ORDER if s in by_source]
    rest = sorted((s for s in by_source if s not in SOURCE_ORDER and s),
                  key=lambda s: source_group_label(s).lower())
    if None in by_source or "" in by_source:
        rest.append(None if None in by_source else "")
    return known + rest


def stat_chips(stats):
    if not isinstance(stats, dict):
        return ""
    chips = []
    for k, v in stats.items():
        label = str(k).replace("_", " ")
        chips.append(f'<span class="chip">{esc(label)}: {esc(v)}</span>')
    return f'<div class="chips">{"".join(chips)}</div>' if chips else ""


def report_entry(m):
    href = f"reports/{esc(m['id'])}.html"
    return (
        '<div class="repitem">'
        f'<div class="repitem-top"><span class="d">{esc(m.get("date", ""))}</span>'
        f'<span class="src-chip">{esc(source_group_label(m.get("source")))}</span>'
        f'<a href="{href}">Open report →</a></div>'
        f'<div class="repitem-blurb">{esc(m.get("blurb", ""))}</div>'
        f"{stat_chips(m.get('stats'))}"
        "</div>"
    )


def type_section(rtype, by_source, limit=None):
    groups = "".join(
        f'<div class="srcgroup"><h3>{esc(source_group_label(src))}</h3>'
        + "".join(report_entry(m) for m in by_source[src][:limit])
        + "</div>"
        for src in ordered_sources(by_source)
    )
    return f'<section class="card"><h2>{esc(type_label(rtype))}</h2>{groups}</section>'


def news_section(docs_dir):
    """Market news card for the hub (issue #21).

    Bakes in the morning's headlines from docs/news.json as the always-present
    fallback; a small inline script then tries a live refresh via the rss2json
    CORS proxy on page load. If the live fetch fails, the morning snapshot
    stays with an explanatory note. Manual retry via the refresh button.
    """
    heads, fetched = [], ""
    try:
        with open(os.path.join(docs_dir, "news.json")) as f:
            data = json.load(f)
        heads = data.get("headlines") or []
        fetched = (data.get("fetched_at") or "")[:16].replace("T", " ")
    except (OSError, ValueError):
        pass
    if heads:
        items = "".join(
            f"<li><a href=\"{esc(h['link'])}\" target=\"_blank\" rel=\"noopener\">"
            f"{esc(h['title'])}</a>"
            f"<span class=\"dim\"> — {esc(h.get('source') or '')}</span></li>"
            for h in heads[:8]
        )
        fallback_note = f"Morning snapshot ({esc(fetched)} UTC)"
    else:
        items = "<li class=\"dim\">No headlines yet — the next scheduled run fetches them.</li>"
        fallback_note = "No snapshot yet"
    return f"""
<section class="card"><h2>Market news</h2>
<p class="dim"><span id="news-status">{fallback_note}</span>
<button id="news-refresh" class="refresh-btn" title="Refresh headlines now">↻</button></p>
<ul id="news-live-list" class="news-list">{items}</ul>
<script>
(function() {{
  var list = document.getElementById('news-live-list');
  var status = document.getElementById('news-status');
  if (!list || !status) return;
  function esc(s) {{
    return String(s == null ? '' : s).replace(/[&<>"']/g, function(c) {{
      return {{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[c];
    }});
  }}
  function render(items, label) {{
    list.innerHTML = items.map(function(h) {{
      var t = h.title || '';
      var dash = t.lastIndexOf(' - ');
      if (dash > 0) t = t.slice(0, dash);
      return '<li><a href="' + esc(h.link) + '" target="_blank" rel="noopener">'
        + esc(t) + '</a></li>';
    }}).join('');
    status.textContent = label;
  }}
  function load() {{
    status.textContent = 'Refreshing headlines…';
    var q = encodeURIComponent('S&P 500 stock market');
    var rss = encodeURIComponent('https://news.google.com/rss/search?q=' + q
      + '&hl=en-US&gl=US&ceid=US:en');
    fetch('https://api.rss2json.com/v1/api.json?rss_url=' + rss)
      .then(function(r) {{ return r.json(); }})
      .then(function(d) {{
        if (d && d.status === 'ok' && d.items && d.items.length)
          render(d.items.slice(0, 8),
                 'Live · updated ' + new Date().toLocaleTimeString());
        else throw new Error('bad payload');
      }})
      .catch(function() {{
        status.textContent = 'Live refresh unavailable — showing morning snapshot.';
      }});
  }}
  document.getElementById('news-refresh').addEventListener('click', load);
  load();
}})();
</script>
</section>"""


def build_page(title, subtitle, sections, backlink=""):
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)}</title>
<style>{CSS}{BACKLINK_CSS}{HUB_CSS}</style>
</head>
<body>
<div class="wrap">
{backlink}
<header>
<h1>{esc(title)}</h1>
<p class="sub">{subtitle}</p>
</header>
<section class="card"><h2>How a trade gets made</h2>{workflow_strip()}</section>
{sections}
<section class="card"><h2>Private open-position review &amp; risk</h2>
<p>The bull-put exit policy can be applied to a local ledger using fresh,
timestamped buy-to-close marks. The review reports take-profit, stop-loss,
time-exit, and assignment-risk actions; missing or stale marks are marked
unavailable. It never places orders.</p>
<p>Run <code>bash bin/manage-positions.sh LEDGER.json MARKS.json</code> from a local
checkout. Position-level results stay in the ignored <code>reports/</code>
folder and should not be published with this public dashboard. See the
<a href="comprehensive-options-market-analysis-framework.html">framework assessment</a> for the mark-file format, coverage
measures, and limits. This adds auditable rule coverage; it does not establish
that the exit policy improves returns.</p>
<p>Portfolio Greeks and scenario risk can also be generated locally from
timestamped Public option/equity quotes and Treasury's daily rate feed:
<code>bash bin/run-portfolio-risk.sh LEDGER.json</code>. Exact OSI identifiers
are required for each option leg. Missing or stale inputs leave risk incomplete;
holdings and reports stay local and are not written to public reports.</p>
<p>Configured bull-put exits can be replayed locally against supplied,
timestamped historical marks:
<code>bash bin/evaluate-historical-exits.sh INPUT.json</code>. This reports
coverage and mark-based outcomes after explicit costs; incomplete paths remain
unresolved and the replay does not claim future profitability. See the
<a href="comprehensive-options-market-analysis-framework.html">framework assessment</a>
for data requirements and limitations.</p>
</section>
<section class="card"><h2>Reading the screens — notes &amp; lessons</h2>
<h3>Pre-market gap vs intraday momentum</h3>
<p>The <b>pre-market gap screen</b> runs before 9:30am ET and qualifies gaps using
gap size, ATR, and price. It compares premarket volume with cached snapshots from
the same 15-minute time bucket over the prior 20 sessions when available. Until
that baseline is ready, it shows raw shares and ranks by gap/ATR without a volume
gate. The post-open <b>opening-range confirmation</b> uses regular-session volume
divided by the 20-day average daily volume prorated by elapsed minutes, and
calculates VWAP from regular-session bars only.</p>
<p>The <b>intraday momentum screen</b> (11am, 2pm ET) uses <b>session-aware</b>
signals, rebuilt 2026-10-12 after the first version proved too narrow:</p>
<ul>
<li><b>Opening-range breakout — and holding.</b> The first version asked "is it
piercing the 15-min range <i>right now</i>?" — but breakouts happen at 10am, not
1:15pm. Now: did it break the range at any point today, and is it still holding
above (or below) it? A breakout that faded back inside the range is flagged
separately.</li>
<li><b>VWAP — sustained position, not the cross moment.</b> The first version only
saw crosses in the last 30 minutes, so an 11am reclaim was invisible by 1:15pm.
Now: what fraction of the session has price held above/below the developing VWAP?
≥ 70% one side counts as sustained.</li>
<li><b>Time-prorated volume.</b> Today's volume so far vs the 20-day average
<i>scaled by elapsed session time</i> — the fix for the pre-market screen's flaw.
1.5× at 11am means genuinely heavy trading, not an impossible bar.</li>
<li><b>Never a blank page.</b> If nothing meets the strict gates, the strongest
volume-plus-drift names still show as <i>momentum watch</i> rows.</li>
</ul>
<h3>RoR — return on risk</h3>
<p>RoR = credit ÷ max loss. A 39.7% RoR on a $142 credit / $358 max-loss condor
means: best case you keep $142, worst case you lose $358 — $0.40 of profit per
$1 risked <i>if</i> it works. Higher RoR = more credit per dollar risked.</p>
<p>RoR is a <b>ranking</b> tool, not a gate and not a forecast. Nothing is rejected
for low RoR; the tables are simply sorted by it. A high RoR never means a trade
is likely to win — the edge in credit spreads is <i>probability</i> (price staying
between the breakevens), not payout ratio.</p>
<p>Max loss + credit always equals the wing width ($358 + $142 = $500 on a
5-point wing). Max loss below credit would need RoR over 100% — the market never
prices liquid spreads that way; if you see it, it's a bad quote.</p>
<h3>Win%, EV$, Loss× — reading the odds</h3>
<p>Three newer columns estimate what RoR alone doesn't say:</p>
<ul>
<li><b>Win%</b> — estimated probability the trade wins (keeps some credit).
For a bull put: 1 − |short delta|. For an iron condor:
(1 − |put delta|) × (1 − |call delta|). Delta approximates the market's
pricing of exercise probability, so this is a <i>model estimate</i>, not a
market fact. A 72% Win% means the options market prices roughly 72% odds the
short legs expire worthless.</li>
<li><b>EV$</b> — expected dollar value: Win% × credit − (1 − Win%) × max loss.
Positive EV means the trade is priced in your favor <i>if</i> the delta-based
odds hold. Negative EV doesn't mean "don't trade" — it means you're paying for
the defined risk, which is the point of spreads.</li>
<li><b>Loss×</b> — loss multiple: max loss ÷ credit. A 2.5× means you risk
$2.50 for every $1 of credit. Higher Loss× needs higher Win% to break even —
the two columns read together.</li>
</ul>
<p><b>Best / worst / optimal price ranges.</b> Best case: price stays between the
breakevens through expiration — you keep the full credit. Worst case: price blows
through a long strike — you lose the max. Optimal: price pins near the short
strikes, maximizing time decay. The breakeven column shows the exact boundaries.</p>
<h3>Winners vs losers — how to read Win%</h3>
<p>Every spread row now carries <b>Win%</b>, <b>EV$</b>, and <b>Loss×</b>:</p>
<ul>
<li><b>High Win% (70%+) + positive EV$</b> — the market prices this in your favor.
These are the "high chance of winning" candidates. Still defined-risk: a gap
through the long strike loses the max.</li>
<li><b>High Win% + negative EV$</b> — you're paying for safety. Common on
low-IV names; the trade is a hedge-like income position, not an edge.</li>
<li><b>Low Win% (&lt;55%) + high RoR</b> — lottery tickets. Big payout if right,
but the odds say you'll lose more often than not. Size these tiny or skip.</li>
<li><b>Loss× above 4</b> — you're risking $4+ per $1 of credit. Needs Win%
above 80% to break even on expectancy. Treat with suspicion.</li>
</ul>
<p>Sort mentally by <b>EV$ first, Win% second, RoR third</b>. RoR ranks payout
efficiency; EV$ ranks whether the odds justify the risk.</p>
<h3>Reading the legs</h3>
<p>First strike = <b>short (sell)</b>, second = <b>long (buy)</b>.
210/205P means sell the 210 put, buy the 205 put. 245/250C means sell the 245
call, buy the 250 call. The short strikes are where premium is collected — and
what defines the profit zone via the breakevens.</p>
<p class="fine">Reports are static snapshots; regenerating means re-running the
screener. Figures computed from Public.com API data in-run. Screeners never
place orders.</p>
</section>
<footer>Regenerated {esc(dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC"))} · screeners never place orders.</footer>
</div>
</body>
</html>
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--docs", default=None)
    args = ap.parse_args()

    docs_dir = args.docs or resolve_docs_dir()
    metas = load_metas(docs_dir)

    # type -> source -> [metas newest-first]
    archive = {}
    for m in metas:
        rtype = m.get("type") or "other"
        archive.setdefault(rtype, {}).setdefault(m.get("source"), []).append(m)
    for by_source in archive.values():
        for lst in by_source.values():
            lst.sort(key=lambda m: (str(m.get("date", "")), str(m.get("id", ""))),
                     reverse=True)

    types = [t for t in TYPE_ORDER if t in archive]
    types += sorted((t for t in archive if t not in TYPE_ORDER),
                    key=lambda t: type_label(t).lower())

    if types:
        latest_sections = "".join(type_section(t, archive[t], limit=1) for t in types)
        archive_sections = "".join(type_section(t, archive[t]) for t in types)
    else:
        latest_sections = archive_sections = (
            '<section class="card"><p class="empty">No reports yet — '
            "the first scheduled run will populate this archive.</p></section>")

    n = len(metas)
    n_groups = sum(len(by_source) for by_source in archive.values())

    hub = build_page(
        "Options Lab — Latest Reports",
        ("The most recent run of each screen. "
         f'<a href="archive.html">Full archive →</a> '
         f'<a href="compare.html">Setup leaderboard →</a> '
         f"({n} reports, {n_groups} screens)"),
        news_section(docs_dir) + latest_sections,
    )
    out = os.path.join(docs_dir, "index.html")
    os.makedirs(docs_dir, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        f.write(hub)

    arch = build_page(
        "Options Lab — Report Archive",
        f"Every report ever published ({n} reports), newest first.",
        archive_sections,
        backlink='<p class="backlink"><a href="index.html">← Latest reports</a></p>',
    )
    aout = os.path.join(docs_dir, "archive.html")
    with open(aout, "w", encoding="utf-8") as f:
        f.write(arch)

    print(f"wrote {out} ({os.path.getsize(out)} bytes) "
          f"and {aout} ({os.path.getsize(aout)} bytes) "
          f"from {n} report{'s' if n != 1 else ''}")


if __name__ == "__main__":
    main()
