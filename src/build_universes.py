#!/usr/bin/env python3
"""Regenerate the index-universe text files under universes/.

Sources (all public, no API key):
  sp500      Wikipedia List of S&P 500 companies (wikitext API)
  sp100      Wikipedia S&P 100 (wikitext API)
  nasdaq100  Wikipedia List of NASDAQ-100 companies (wikitext API)
  dow30      curated static list (Dow changes ~1x/year; verify annually)
  russell2000  iShares IWM latest-holdings.csv

Fail-safe: a source that errors or returns a count outside the expected
bounds keeps the previous file untouched and the script exits non-zero.
Run monthly via build-universes.yml (or manually: python3 build_universes.py).

Stdlib only.
"""

import csv
import io
import json
import os
import re
import sys
import urllib.request
from datetime import date

UA_WIKI = "amuse-universe-builder/1.0 (https://github.com/OpenAIMP/amuse)"
UA_WEB = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
          "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(HERE, "universes")

# name -> (min_count, max_count) sanity bounds
BOUNDS = {
    "sp500": (495, 515),
    "sp100": (95, 105),
    "nasdaq100": (95, 108),
    "dow30": (30, 30),
    "russell2000": (1800, 2100),
}

# Dow Jones Industrial Average, verified 2026-10-12 against the
# post-Nov-2024 reconstitution (NVDA/SHW replaced INTC/DOW).
# Recheck annually: https://www.spglobal.com/spdji/en/indices/equity/dow-jones-industrial-average/
DOW30 = """MMM AMZN AXP AMGN AAPL BA CAT CVX CSCO KO DIS GS HD HON IBM JNJ
JPM MCD MRK MSFT NKE NVDA PG CRM SHW TRV UNH VZ V WMT""".split()


def fetch(url, ua, timeout=60):
    req = urllib.request.Request(url, headers={"User-Agent": ua})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "ignore")


def wikipedia_constituents(page):
    """Tickers from a Wikipedia constituents table (template or plain cells)."""
    url = ("https://en.wikipedia.org/w/api.php?action=parse&page=" + page +
           "&prop=wikitext&format=json")
    d = json.loads(fetch(url, UA_WIKI))
    wt = d["parse"]["wikitext"]["*"]
    start = wt.find('id="constituents"')
    if start < 0:
        raise ValueError(f"{page}: constituents table not found")
    seg = wt[start:]
    ends = [p for p in (seg.find("\n|}", 10), seg.find("\n==", 10)) if p > 0]
    table = seg[:min(ends)] if ends else seg
    syms = []
    lines = table.splitlines()
    i = 0
    while i < len(lines):
        s = lines[i].strip()
        # a data row starts right after a |- separator; the symbol is the
        # FIRST cell that follows (never parse continuation lines: company
        # names like [[U.S. Steel]] produce false ticker fragments)
        if s == "|-" and i + 1 < len(lines):
            cell_line = lines[i + 1].strip()
            cell = re.sub(r"^\|+", "", cell_line)
            cell = re.split(r"\|\|", cell, 1)[0].strip()
            m = re.match(r"\{\{[A-Za-z]*Symbol\|([A-Z0-9.\-]+)\}\}", cell)
            if m:
                sym = m.group(1)
            else:
                tok = re.split(r"\s", cell, 1)[0].strip().strip("[]")
                sym = tok if re.fullmatch(r"[A-Z][A-Z0-9.\-]{0,6}", tok) else None
            if sym and sym not in syms:
                syms.append(sym)
            i += 2
        else:
            i += 1
    return syms


def ishares_russell2000():
    """Tickers from the iShares IWM latest-holdings.csv."""
    url = ("https://www.ishares.com/us/products/239710/"
           "ishares-russell-2000-etf/latest-holdings.csv")
    text = fetch(url, UA_WEB, timeout=90)
    lines = text.splitlines()
    hdr = next(i for i, l in enumerate(lines[:15]) if l.startswith("Ticker,"))
    asof = ""
    for l in lines[:hdr]:
        if "as of" in l:
            asof = l.split("as of,")[-1].strip().strip('"')
    syms = []
    for row in csv.DictReader(lines[hdr:]):
        t = (row.get("Ticker") or "").strip().upper()
        if not t or t in ("TICKER", "-"):
            continue
        t = t.replace(" ", ".")  # 'MOG A' -> 'MOG.A' (dotted class shares)
        if not re.fullmatch(r"[A-Z][A-Z0-9.\-]{0,8}", t):
            continue
        if t not in syms:
            syms.append(t)
    return syms, asof or str(date.today())


SOURCES = {
    "sp500": ("Wikipedia List of S&P 500 companies",
              lambda: (wikipedia_constituents("List_of_S%26P_500_companies"),
                       str(date.today()))),
    "sp100": ("Wikipedia S&P 100",
              lambda: (wikipedia_constituents("S%26P_100"), str(date.today()))),
    "nasdaq100": ("Wikipedia List of NASDAQ-100 companies",
                  lambda: (wikipedia_constituents("List_of_NASDAQ-100_companies"),
                           str(date.today()))),
    "dow30": ("curated static list (verify annually)",
              lambda: (list(DOW30), "2026-10-12 (static)")),
    "russell2000": ("iShares IWM latest-holdings.csv", ishares_russell2000),
}


def write_universe(name, symbols, source, asof):
    lo, hi = BOUNDS[name]
    if not (lo <= len(symbols) <= hi):
        raise ValueError(f"{name}: got {len(symbols)} symbols, "
                         f"expected {lo}-{hi}; keeping previous file")
    path = os.path.join(OUT_DIR, f"{name}.txt")
    with open(path, "w") as f:
        f.write(f"# {name} constituents\n")
        f.write(f"# source: {source}\n")
        f.write(f"# as-of: {asof}\n")
        f.write(f"# count: {len(symbols)}\n")
        for s in symbols:
            f.write(s + "\n")
    print(f"wrote {path} ({len(symbols)} symbols)")


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    failed = []
    for name, (source, fn) in SOURCES.items():
        try:
            symbols, asof = fn()
            write_universe(name, symbols, source, asof)
        except Exception as e:
            print(f"FAILED {name}: {e}", file=sys.stderr)
            failed.append(name)
    if failed:
        print(f"failed: {', '.join(failed)}; previous files kept",
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
