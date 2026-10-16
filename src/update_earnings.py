#!/usr/bin/env python3
"""
Daily earnings calendar updater (#33).

Fetches upcoming earnings dates from Nasdaq's public calendar API
(no key required) for all symbols across our universes, and merges
them into src/earnings_dates.json.

This eliminates the manual curation process — the earnings guard
never goes blind.

Usage:
    python3 src/update_earnings.py [--days 30] [--dry-run]

Designed to run as a daily step in daily-watch.yml before the screeners.
Stdlib-only.
"""

import argparse
import datetime as dt
import json
import os
import sys
import urllib.request
import urllib.error

SRC_DIR = os.path.dirname(os.path.abspath(__file__))
EARNINGS_PATH = os.path.join(SRC_DIR, "earnings_dates.json")
UNIVERSES_DIR = os.path.join(SRC_DIR, "universes")

NASDAQ_API = "https://api.nasdaq.com/api/calendar/earnings"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; OptionsLab/1.0)",
    "Accept": "application/json",
}


def load_universe_symbols():
    """Load all symbols from every universe file."""
    symbols = set()
    if not os.path.isdir(UNIVERSES_DIR):
        return symbols
    for fname in os.listdir(UNIVERSES_DIR):
        if not fname.endswith(".txt"):
            continue
        with open(os.path.join(UNIVERSES_DIR, fname)) as f:
            for line in f:
                sym = line.strip().upper()
                if sym and not sym.startswith("#"):
                    symbols.add(sym)
    return symbols


def fetch_earnings_for_date(date_str):
    """Fetch earnings calendar for a single date. Returns {symbol: date}."""
    url = f"{NASDAQ_API}?date={date_str}"
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read())
    except (urllib.error.URLError, json.JSONDecodeError, TimeoutError) as e:
        print(f"  warning: failed to fetch {date_str}: {e}", file=sys.stderr)
        return {}
    rows = (data.get("data") or {}).get("rows") or []
    result = {}
    for row in rows:
        sym = (row.get("symbol") or "").strip().upper()
        if sym:
            result[sym] = date_str
    return result


def fetch_upcoming_earnings(symbols, days=30):
    """
    Fetch earnings for the next `days` days, filtered to our symbols.
    Returns {symbol: YYYY-MM-DD}.
    """
    found = {}
    today = dt.date.today()
    for i in range(days):
        d = today + dt.timedelta(days=i)
        date_str = d.strftime("%Y-%m-%d")
        daily = fetch_earnings_for_date(date_str)
        for sym, edate in daily.items():
            if sym in symbols and sym not in found:
                found[sym] = edate
        # Be polite to the API
        if i < days - 1:
            import time
            time.sleep(0.3)
    return found


def load_existing():
    """Load the current earnings_dates.json, preserving the _note."""
    try:
        with open(EARNINGS_PATH) as f:
            return json.load(f)
    except (IOError, json.JSONDecodeError):
        return {"_note": (
            "Curated earnings dates for the screener's earnings-in-window "
            "reject rule (#33). Auto-updated daily by update_earnings.py. "
            "Format: {\"SYM\": {\"earnings\": \"YYYY-MM-DD\"}}."
        )}


def merge_earnings(existing, fetched):
    """
    Merge fetched dates into existing. Returns (merged, changes).

    - New symbols get added
    - Existing symbols get updated if the fetched date differs
    - Past earnings (>7 days ago) get pruned
    - The _note key is preserved
    """
    merged = dict(existing)
    changes = {"added": [], "updated": [], "pruned": []}
    today = dt.date.today()
    cutoff = today - dt.timedelta(days=7)

    for sym, entry in list(merged.items()):
        if sym == "_note":
            continue
        edate_str = entry.get("earnings") if isinstance(entry, dict) else None
        if not edate_str:
            continue
        try:
            edate = dt.date.fromisoformat(edate_str)
        except ValueError:
            continue
        if edate < cutoff:
            del merged[sym]
            changes["pruned"].append(sym)

    for sym, edate in fetched.items():
        if sym == "_note":
            continue
        new_entry = {"earnings": edate}
        if sym not in merged:
            merged[sym] = new_entry
            changes["added"].append(sym)
        elif merged[sym] != new_entry:
            merged[sym] = new_entry
            changes["updated"].append(sym)

    return merged, changes


def main(argv):
    parser = argparse.ArgumentParser(
        description="Daily earnings calendar updater (#33)"
    )
    parser.add_argument("--days", type=int, default=30,
                        help="Days ahead to fetch (default: 30)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print changes without writing")
    args = parser.parse_args(argv)

    print("Loading universe symbols...", file=sys.stderr)
    symbols = load_universe_symbols()
    print(f"  {len(symbols)} symbols across all universes", file=sys.stderr)

    print(f"Fetching earnings for next {args.days} days...", file=sys.stderr)
    fetched = fetch_upcoming_earnings(symbols, days=args.days)
    print(f"  Found {len(fetched)} upcoming earnings", file=sys.stderr)

    existing = load_existing()
    merged, changes = merge_earnings(existing, fetched)

    total_changes = (len(changes["added"]) + len(changes["updated"])
                     + len(changes["pruned"]))
    print(f"Changes: {len(changes['added'])} added, "
          f"{len(changes['updated'])} updated, "
          f"{len(changes['pruned'])} pruned", file=sys.stderr)

    if args.dry_run:
        print(json.dumps({"changes": changes,
                          "sample": dict(list(merged.items())[:5])},
                         indent=2))
        return 0

    if total_changes > 0:
        with open(EARNINGS_PATH, "w") as f:
            json.dump(merged, f, indent=2, sort_keys=True)
            f.write("\n")
        print(f"Wrote {EARNINGS_PATH}", file=sys.stderr)
    else:
        print("No changes needed.", file=sys.stderr)

    # Machine-readable summary for CI
    print(json.dumps({
        "added": len(changes["added"]),
        "updated": len(changes["updated"]),
        "pruned": len(changes["pruned"]),
        "total_symbols": len([k for k in merged if k != "_note"]),
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
