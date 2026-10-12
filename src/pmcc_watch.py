#!/usr/bin/env python3
"""Daily PMCC exception watch: run the screen, diff vs prior state, report only
material changes. Quiet when nothing changed.

Change = new qualifier, qualifier dropped, or |yield shift| >= 1.5 pts on a
top-8 name. Qualifier: p/d30 >= 4.0 and breakeven within 8% above spot and no
event flags.
"""
import argparse
import json, os, subprocess, sys

LAB = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(LAB, "state", "pmcc_last.json")
TODAY = os.path.join(LAB, "state", "pmcc_today.json")

def qualifies(p):
    return (p["premium_to_debit_30d"] >= 4.0
            and p["breach_vs_spot"] <= 0.08
            and not p["events"])

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--names", default=None,
                    help="comma-separated watchlist; forwarded to pmcc_quality.py")
    args = ap.parse_args()
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    cmd = [sys.executable, os.path.join(LAB, "pmcc_quality.py"),
           "--json-out", TODAY]
    if args.names:
        cmd += ["--names", args.names]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=1500)
    if r.returncode != 0:
        print(f"WATCH ERROR: screener failed:\n{r.stderr[-500:]}")
        return
    with open(TODAY) as f:
        today = json.load(f)["pairs"]
    prev = {}
    if os.path.exists(STATE):
        with open(STATE) as f:
            prev = json.load(f)["pairs"]

    tq = {s for s, p in today.items() if qualifies(p)}
    pq = {s for s, p in prev.items() if qualifies(p)} if prev else set()

    notes = []
    for s in sorted(tq - pq):
        p = today[s]
        notes.append(f"NEW QUALIFIER: {s} p/d30 {p['premium_to_debit_30d']:.1f}% "
                     f"cap ${p['capital']:,.0f} breach {p['breach_vs_spot']:+.1%}")
    for s in sorted(pq - tq):
        notes.append(f"DROPPED OUT: {s} no longer meets entry gates")
    for s in sorted(tq & pq):
        d = today[s]["premium_to_debit_30d"] - prev[s]["premium_to_debit_30d"]
        if abs(d) >= 1.5:
            notes.append(f"YIELD SHIFT: {s} {prev[s]['premium_to_debit_30d']:.1f}% -> "
                         f"{today[s]['premium_to_debit_30d']:.1f}% ({d:+.1f} pts)")

    os.replace(TODAY, STATE)
    if not prev:
        print("WATCH BASELINE SET: first run recorded; future runs diff against it. "
              f"Current qualifiers: {', '.join(sorted(tq)) or 'none'}.")
    elif notes:
        print("PMCC WATCH — changes since last run:\n" + "\n".join(f"- {n}" for n in notes))
    else:
        print("PMCC WATCH: no material changes since last run. Staying quiet.")

if __name__ == "__main__":
    main()
