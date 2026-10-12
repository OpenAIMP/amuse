#!/usr/bin/env python3
"""PMCC screener for low-priced blue chips: deep-ITM LEAPS (~80d) + short ~30d near-term call."""
import json
import os, subprocess, re, sys

CLI = os.environ.get("PUBLIC_MCP_CLI", "/home/hatch/workspace/skills/public-mcp/bin/public-mcp")
ACCT = os.environ.get("PUBLIC_ACCOUNT_ID", "5OI32712")
NAMES = {
    "F": 12.26, "T": 23.24, "PFE": 27.81, "VZ": 43.72, "BAC": 53.62,
}
SHORT_EXP = "2026-12-18"   # ~68 DTE short leg; roll monthly in practice

def call(tool, args):
    out = subprocess.run([CLI, "call", tool, json.dumps(args)],
                         capture_output=True, text=True, timeout=120)
    d = json.loads(out.stdout)
    if d.get("isError"):
        raise RuntimeError(f"{tool}: {json.dumps(d)[:300]}")
    return d

def strike_of(osi):
    m = re.search(r"([CP])(\d{8})$", osi)
    return int(m.group(2)) / 1000.0

def parse_calls(sym, exp):
    p = json.loads(call("get_option_chain", {"symbol": sym, "expiration_date": exp, "account_id": ACCT})["content"][0]["text"])
    out = {}
    for c in p["calls"]:
        try:
            k = strike_of(c["instrument"]["symbol"])
            bid, ask = float(c["bid"] or 0), float(c["ask"] or 0)
            if bid > 0 and ask > 0:
                out[k] = {"sym": c["instrument"]["symbol"], "mid": (bid + ask) / 2}
        except Exception:
            pass
    return out

def expirations(sym):
    d = call("get_option_expirations", {"symbol": sym, "account_id": ACCT})
    return re.findall(r"20\d\d-\d\d-\d\d", d["content"][0]["text"])

for sym, spot in NAMES.items():
    try:
        exps = expirations(sym)
        long_exp = exps[-1]
        leaps = parse_calls(sym, long_exp)
        # deep ITM candidates: 40-70% of spot
        cands = [k for k in sorted(leaps) if spot * 0.35 <= k <= spot * 0.7]
        if not cands:
            print(f"{sym}: no suitable LEAPS strikes"); continue
        g = json.loads(call("get_option_greeks", {"osi_symbols": [leaps[k]["sym"] for k in cands], "account_id": ACCT})["content"][0]["text"])
        deltas = {x["symbol"]: float(x["greeks"]["delta"]) for x in g["greeks"]}
        lk = min(cands, key=lambda k: abs(deltas[leaps[k]["sym"]] - 0.80))
        lo = leaps[lk]
        near = parse_calls(sym, SHORT_EXP)
        # short: nearest strike >= 1.05*spot with decent delta; get deltas
        scands = sorted([k for k in near if k >= spot * 1.02])[:6]
        g2 = json.loads(call("get_option_greeks", {"osi_symbols": [near[k]["sym"] for k in scands], "account_id": ACCT})["content"][0]["text"])
        d2 = {x["symbol"]: float(x["greeks"]["delta"]) for x in g2["greeks"]}
        sk = min(scands, key=lambda k: abs(d2[near[k]["sym"]] - 0.30))
        so = near[sk]
        debit = lo["mid"] - so["mid"]
        shares_cost = spot * 100
        print(f"{sym} @ ${spot:.2f} | Long {long_exp} {lk:.0f}C Δ={deltas[lo['sym']]:.2f} ${lo['mid']:.2f} "
              f"| Short {SHORT_EXP} {sk:.0f}C Δ={d2[so['sym']]:.2f} ${so['mid']:.2f}")
        print(f"   debit ${debit*100:,.0f} ({debit*100/shares_cost*100:.0f}% of ${shares_cost:,.0f} for 100sh) | "
              f"yield {so['mid']/debit*100:.1f}%/cycle | max loss ${debit*100:,.0f} | breakeven ${lk+debit:.2f}")
    except Exception as e:
        print(f"{sym}: ERROR {str(e)[:120]}", file=sys.stderr)
