#!/usr/bin/env python3
"""Loop a screener across index universes and merge into one ranked readout.

Examples:
    python3 scan_loop.py --screener stock_screener.py --universes sp100,nasdaq100
    python3 scan_loop.py --screener spread_screener.py --universes dow30 --extra "--width 2"
    python3 scan_loop.py --screener daytrade_screen.py --universes sp500 --extra "--limit 50"

Each universe runs the screener as a subprocess with --universe <key>;
passing results are merged (dedupe by symbol, keep best score) and printed
as a single cross-universe leaderboard. Rejection stats are aggregated.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile

from universes import UNIVERSES

LAB = os.path.dirname(os.path.abspath(__file__))

# how to rank a "passing" entry per screener
def _rank_key(screener, entry):
    if screener == "stock_screener.py":
        return float(entry.get("score", 0))
    if screener == "spread_screener.py":
        return float(entry.get("return_on_risk", 0))
    if screener == "daytrade_screen.py":
        return float(entry.get("conviction", 0))
    return 0.0


def _passing_entries(screener, data):
    if screener == "stock_screener.py":
        return data.get("passing", [])
    if screener == "spread_screener.py":
        out = []
        for grp in ("bull_puts", "iron_condors"):
            for e in data.get(grp, []):
                e = dict(e)
                e["_strategy"] = grp
                out.append(e)
        return out
    if screener == "daytrade_screen.py":
        return data.get("candidates", data.get("passing", []))
    return []


def _sym(entry):
    return entry.get("symbol") or entry.get("stock") or "?"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--screener", default="stock_screener.py",
                    choices=["stock_screener.py", "spread_screener.py",
                             "daytrade_screen.py"])
    ap.add_argument("--universes", default="sp100,nasdaq100",
                    help="comma-separated universe keys from universes.py")
    ap.add_argument("--extra", default="",
                    help="extra args forwarded to the screener, quoted as one string")
    ap.add_argument("--json-out", default=None)
    args = ap.parse_args()

    universes = [u.strip().lower() for u in args.universes.split(",") if u.strip()]
    bad = [u for u in universes if u not in UNIVERSES]
    if bad:
        raise SystemExit(f"unknown universes {bad}; choose from {sorted(UNIVERSES)}")
    extra = args.extra.split() if args.extra else []
    env = dict(os.environ)

    merged = {}   # symbol -> (rank, universe, entry)
    per_uni = {}
    for u in universes:
        names = UNIVERSES[u]
        print(f"\n--- universe {u} ({len(names)} names) ---", flush=True)
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tf:
            tmp = tf.name
        cmd = [sys.executable, os.path.join(LAB, args.screener),
               "--universe", u, "--json-out", tmp] + extra
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=3600,
                           env=env)
        if r.returncode != 0:
            print(f"  FAILED rc={r.returncode}: {r.stderr[-300:]}")
            per_uni[u] = {"names": len(names), "passed": 0, "error": True}
            continue
        try:
            with open(tmp) as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            print(f"  bad json: {e}")
            per_uni[u] = {"names": len(names), "passed": 0, "error": True}
            continue
        entries = _passing_entries(args.screener, data)
        per_uni[u] = {"names": len(names), "passed": len(entries)}
        print(f"  {len(entries)} passing")
        # print the screener's own readout lines if present
        for line in data.get("readout", [])[:6]:
            print(f"  | {line}")
        for e in entries:
            s = _sym(e)
            rank = _rank_key(args.screener, e)
            if s not in merged or rank > merged[s][0]:
                merged[s] = (rank, u, e)

    ranked = sorted(merged.items(), key=lambda kv: -kv[1][0])
    print("\n=== CROSS-UNIVERSE LEADERS ===")
    for s, (rank, u, e) in ranked[:20]:
        if args.screener == "stock_screener.py":
            print(f"{s:<7} score {rank:5.1f}  [{u}]")
        elif args.screener == "spread_screener.py":
            print(f"{s:<7} {e.get('_strategy',''):<12} RoR {rank:5.1%}  [{u}] "
                  f"{e.get('short_strike','')}/{e.get('long_strike','')}")
        else:
            print(f"{s:<7} conviction {rank:6.2f}  [{u}] bias: {e.get('bias','?')}")
    if not ranked:
        print("(no passing candidates in any universe)")
    print("\nPer-universe:", "; ".join(
        f"{u}: {v['passed']}/{v['names']}" for u, v in per_uni.items()))

    if args.json_out:
        with open(args.json_out, "w") as f:
            json.dump({"screener": args.screener, "universes": per_uni,
                       "leaders": [{"symbol": s, "rank": r, "universe": u,
                                     "entry": e} for s, (r, u, e) in ranked]},
                      f, indent=1)
        print(f"\nwrote {args.json_out}", file=sys.stderr)


if __name__ == "__main__":
    main()
