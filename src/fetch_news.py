#!/usr/bin/env python3
"""Fetch market + ticker news from Google News RSS (issue #21).

Stdlib-only, no API key. Designed to run as a workflow step before rendering:
  python3 src/fetch_news.py --names NVDA,AAPL,... --out reports/news.json \\
      --market-out docs/news.json

Output:
  - <out>: {"fetched_at": iso, "tickers": {SYM: [headlines]}}
  - <market-out>: {"fetched_at": iso, "headlines": [...]}  (committed; the hub
    page bakes these in as the fallback behind the live widget)

A headline is {"title", "link", "published", "source"}. Google News RSS links
are redirect URLs; they resolve in browsers. Failures are swallowed per-feed
(an empty list), never fatal — the renderers degrade gracefully.
"""

import argparse
import datetime
import json
import os
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

UA = {"User-Agent": "Mozilla/5.0 (compatible; amuse-news/1.0)"}
TIMEOUT = 25

MARKET_QUERIES = [
    "S&P 500 stock market",
    "Federal Reserve interest rates",
]

PER_QUERY = 5   # market headlines kept per query (deduped)
PER_TICKER = 3  # headlines kept per ticker


def rss_url(query):
    q = urllib.parse.quote(query)
    return (f"https://news.google.com/rss/search?q={q}"
            f"&hl=en-US&gl=US&ceid=US:en")


def parse_rss(xml_text):
    """Parse a Google News RSS doc into headline dicts. Pure function."""
    out = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return out
    for item in root.findall(".//item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        pub = (item.findtext("pubDate") or "").strip()
        src_el = item.find("source")
        source = (src_el.text or "").strip() if src_el is not None else ""
        # Google appends " - Source" to titles; the <source> tag is cleaner.
        if source and title.endswith(" - " + source):
            title = title[: -(len(source) + 3)]
        if title and link:
            out.append({"title": title, "link": link,
                        "published": pub, "source": source})
    return out


def fetch(query):
    req = urllib.request.Request(rss_url(query), headers=UA)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return parse_rss(r.read().decode("utf-8", "replace"))
    except Exception as e:
        print(f"news: query {query!r} failed: {e}", file=sys.stderr)
        return []


def dedupe(headlines):
    seen, out = set(), []
    for h in headlines:
        key = h["title"].lower()
        if key not in seen:
            seen.add(key)
            out.append(h)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--names", default="",
                    help="comma-separated tickers for per-ticker news")
    ap.add_argument("--out", default="reports/news.json")
    ap.add_argument("--market-out", default="docs/news.json")
    a = ap.parse_args()

    now = (datetime.datetime.now(datetime.timezone.utc)
           .isoformat(timespec="seconds"))

    market = []
    for q in MARKET_QUERIES:
        market.extend(fetch(q)[:PER_QUERY])
    market = dedupe(market)[: PER_QUERY * len(MARKET_QUERIES)]

    tickers = {}
    for sym in [s.strip().upper() for s in a.names.split(",") if s.strip()]:
        heads = fetch(f"{sym} stock")[:PER_TICKER]
        if heads:
            tickers[sym] = heads

    for path, payload in ((a.out, {"fetched_at": now, "tickers": tickers}),
                          (a.market_out, {"fetched_at": now,
                                           "headlines": market})):
        d = os.path.dirname(path)
        if d:
            os.makedirs(d, exist_ok=True)
        with open(path, "w") as f:
            json.dump(payload, f, indent=1)

    print(f"news: {len(market)} market headlines, "
          f"{len(tickers)} tickers with news -> {a.out}, {a.market_out}")


if __name__ == "__main__":
    main()
