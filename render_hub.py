#!/usr/bin/env python3
"""Build the docs/ hub page from report sidecars.

Scans docs/reports/*.meta.json, groups by report type, newest first, and
writes docs/index.html: a stable landing page linking every dated report.

Usage:
    python3 render_hub.py [--docs docs]

Docs dir auto-detects: ./repo/docs locally, ./docs in CI.
Stdlib-only, inline CSS, no external assets, no JavaScript.
"""
from __future__ import annotations

import argparse
import datetime as dt
import glob
import html
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from render_report import CSS, WORKFLOW, esc, resolve_docs_dir, workflow_strip

TYPE_ORDER = ["daily", "daytrade", "pmcc"]
TYPE_LABELS = {
    "daily": "Daily screen",
    "daytrade": "Day-trade screen",
    "pmcc": "PMCC screen",
}

HUB_CSS = """
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:14px;margin:0 0 18px}
.repcard{background:#0d1117;border:1px solid var(--border);border-radius:10px;padding:16px}
.repcard .k{font-size:.75rem;color:var(--dim);text-transform:uppercase;letter-spacing:.06em;margin-bottom:6px}
.repcard h3{margin:0 0 6px;font-size:1.05rem}
.repcard .blurb{font-size:.88rem;color:var(--text);margin:6px 0 10px}
.repcard .empty{font-style:italic}
.chips{display:flex;flex-wrap:wrap;gap:6px;margin:8px 0 12px}
.chip{font-size:.75rem;background:#161b22;border:1px solid var(--border);border-radius:20px;
padding:2px 10px;color:var(--dim);font-variant-numeric:tabular-nums}
.btn{display:inline-block;background:#1f6feb;color:#fff;font-weight:600;font-size:.85rem;
padding:8px 16px;border-radius:8px;text-decoration:none}
.btn:hover{background:#388bfd}
.arch{margin:0;padding-left:0;list-style:none}
.arch li{margin:6px 0;font-size:.9rem}
.arch .d{color:var(--dim);font-variant-numeric:tabular-nums;margin-right:8px}
.arch a{color:var(--blue);text-decoration:none}
.arch a:hover{text-decoration:underline}
details + details{margin-top:10px}
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


def stat_chips(stats):
    if not isinstance(stats, dict):
        return ""
    chips = []
    for k, v in stats.items():
        label = str(k).replace("_", " ")
        chips.append(f'<span class="chip">{esc(label)}: {esc(v)}</span>')
    return f'<div class="chips">{"".join(chips)}</div>' if chips else ""


def latest_card(rtype, metas):
    """Newest report of this type as a card, or a 'no runs yet' card."""
    if not metas:
        return (
            '<div class="repcard">'
            f'<div class="k">{esc(type_label(rtype))}</div>'
            '<p class="blurb empty">No runs yet.</p>'
            "</div>"
        )
    m = metas[0]
    href = f"reports/{esc(m['id'])}.html"
    return (
        '<div class="repcard">'
        f'<div class="k">{esc(type_label(rtype))} · latest</div>'
        f"<h3>{esc(m.get('title', m['id']))}</h3>"
        f'<p class="blurb">{esc(m.get("blurb", ""))}</p>'
        f"{stat_chips(m.get('stats'))}"
        f'<a class="btn" href="{href}">Open report →</a>'
        "</div>"
    )


def archive_details(rtype, metas):
    older = metas[1:]
    if not older:
        return ""
    items = "".join(
        f'<li><span class="d">{esc(m.get("date", ""))}</span>'
        f'<a href="reports/{esc(m["id"])}.html">{esc(m.get("title", m["id"]))}</a></li>'
        for m in older
    )
    return (
        "<details>"
        f"<summary>{esc(type_label(rtype))} archive ({len(older)} older)</summary>"
        f'<ul class="arch">{items}</ul>'
        "</details>"
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--docs", default=None)
    args = ap.parse_args()

    docs_dir = args.docs or resolve_docs_dir()
    metas = load_metas(docs_dir)

    by_type = {}
    for m in metas:
        by_type.setdefault(m.get("type") or "other", []).append(m)
    for lst in by_type.values():
        lst.sort(key=lambda m: str(m.get("date", "")), reverse=True)

    types = [t for t in TYPE_ORDER if t in by_type or True]
    types += [t for t in sorted(by_type) if t not in TYPE_ORDER]

    cards = "".join(latest_card(t, by_type.get(t, [])) for t in types)
    archives = "".join(archive_details(t, by_type[t]) for t in types if by_type.get(t))

    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Options Lab</title>
<style>{CSS}{HUB_CSS}</style>
</head>
<body>
<div class="wrap">
<header>
<h1>Options Lab</h1>
<p class="sub">All figures computed from Public.com API data in-run. Credits use conservative short-bid minus long-ask fills.</p>
</header>
<section class="card"><h2>How a trade gets made</h2>{workflow_strip()}</section>
<section class="card"><h2>Latest reports</h2><div class="cards">{cards}</div></section>
{('<section class="card"><h2>Archive</h2>' + archives + '</section>') if archives else ''}
<footer>Hub regenerated {esc(dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC"))} · screeners never place orders.</footer>
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
