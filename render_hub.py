#!/usr/bin/env python3
"""Build the docs/ report-archive homepage from report sidecars.

Scans docs/reports/*.meta.json and writes docs/index.html: header, the
6-stage workflow strip, then every report ever, grouped by workflow type
(Daily screen / Pre-market day-trade / Monthly PMCC) and within each type
by source (universe), newest-first. Reports are never pruned — this is the
full archive.

Usage:
    python3 render_hub.py [--docs docs]

Docs dir auto-detects: ./repo/docs locally, ./docs in CI.
Stdlib-only, inline CSS, no external assets, no JavaScript.
"""
from __future__ import annotations

import argparse
import datetime as dt
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from render_report import (CSS, WORKFLOW, esc, resolve_docs_dir,
                           source_label, workflow_strip)

TYPE_ORDER = ["daily", "daytrade", "pmcc"]
TYPE_LABELS = {
    "daily": "Daily screen",
    "daytrade": "Pre-market day-trade",
    "pmcc": "Monthly PMCC",
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


def type_section(rtype, by_source):
    groups = "".join(
        f'<div class="srcgroup"><h3>{esc(source_group_label(src))}</h3>'
        + "".join(report_entry(m) for m in by_source[src])
        + "</div>"
        for src in ordered_sources(by_source)
    )
    return f'<section class="card"><h2>{esc(type_label(rtype))}</h2>{groups}</section>'


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
        sections = "".join(type_section(t, archive[t]) for t in types)
    else:
        sections = ('<section class="card"><p class="empty">No reports yet — '
                    "the first scheduled run will populate this archive.</p></section>")

    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Options Lab — Report Archive</title>
<style>{CSS}{HUB_CSS}</style>
</head>
<body>
<div class="wrap">
<header>
<h1>Options Lab — Report Archive</h1>
<p class="sub">Every screen, archived. All figures computed from Public.com API data in-run. Credits use conservative short-bid minus long-ask fills.</p>
</header>
<section class="card"><h2>How a trade gets made</h2>{workflow_strip()}</section>
{sections}
<footer>Archive regenerated {esc(dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC"))} · screeners never place orders.</footer>
</div>
</body>
</html>
"""
    out = os.path.join(docs_dir, "index.html")
    os.makedirs(docs_dir, exist_ok=True)
    with open(out, "w") as f:
        f.write(page)
    n = len(metas)
    print(f"wrote {out} ({os.path.getsize(out)} bytes) from {n} report{'s' if n != 1 else ''}")


if __name__ == "__main__":
    main()
