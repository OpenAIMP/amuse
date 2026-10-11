#!/usr/bin/env python3
"""PMCC on index ETFs: SPY, QQQ, IWM. Deep-ITM LEAPS (~80d) + short ~30d near-term call."""
import json
import os, subprocess, re, sys

CLI = os.environ.get("PUBLIC_MCP_CLI", "/home/hatch/workspace/skills/public-mcp/bin/public-mcp")
ACCT = os.environ.get("PUBLIC_ACCOUNT_ID", "5OI32712")
SHORT_EXP = "2026-12-18"

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

def greeks(syms):
    g = json.loads(call("get_option_greeks", {"osi_symbols": syms, "account_id": ACCT})["content"][0]["text"])
    return {x["symbol"]: float(x["greeks"]["delta"]) for x in g["greeks"]}

q = json.loads(call("get_quotes", {"symbols": ["SPY", "QQQ", "IWM"], "account_id": ACCT})["content"][0]["text"])
spots = {}
def qwalk(o):
    if isinstance(o, dict):
        if o.get("instrument", {}).get("symbol") in ("SPY", "QQQ", "IWM") and "last" in o:
            try: spots[o["instrument"]["symbol"]] = float(o["last"])
            except: pass
        for v in o.values(): qwalk(v)
    elif isinstance(o, list):
        for v in o: qwalk(v)
qwalk(q)
print("spots:", spots)

for sym, spot in spots.items():
    try:
        d = call("get_option_expirations", {"symbol": sym, "account_id": ACCT})
        exps = re.findall(r"20\d\d-\d\d-\d\d", d["content"][0]["text"])
        long_exp = exps[-1]
        leaps = parse_calls(sym, long_exp)
        cands = [k for k in sorted(leaps) if spot * 0.5 <= k <= spot * 0.8]
        dl = greeks([leaps[k]["sym"] for k in cands])
        lk = min(cands, key=lambda k: abs(dl[leaps[k]["sym"]] - 0.80))
        lo = leaps[lk]
        near = parse_calls(sym, SHORT_EXP)
        scands = sorted([k for k in near if k >= spot * 1.02])[:6]
        d2 = greeks([near[k]["sym"] for k in scands])
        sk = min(scands, key=lambda k: abs(d2[near[k]["sym"]] - 0.30))
        so = near[sk]
        debit = lo["mid"] - so["mid"]
        print(f"{sym} @ ${spot:.2f} | Long {long_exp} {lk:.0f}C Δ={dl[lo['sym']]:.2f} ${lo['mid']:.2f} | Short {SHORT_EXP} {sk:.0f}C Δ={d2[so['sym']]:.2f} ${so['mid']:.2f}")
        print(f"   debit ${debit*100:,.0f} ({debit*100/(spot*100)*100:.0f}% of ${spot*100:,.0f}) | yield {so['mid']/debit*100:.1f}%/cycle | max loss ${debit*100:,.0f} | breakeven ${lk+debit:.2f}")
    except Exception as e:
        print(f"{sym}: ERROR {str(e)[:150]}", file=sys.stderr)
