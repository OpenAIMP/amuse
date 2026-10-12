#!/usr/bin/env python3
"""Price a Poor Man's Covered Call on AMD.
Long: deep-ITM Jan-2028 LEAPS call (~80 delta). Short: Nov-20 ~30-delta call."""
import json
import os, subprocess, re

CLI = os.environ.get("PUBLIC_MCP_CLI", "/home/hatch/workspace/skills/public-mcp/bin/public-mcp")
ACCT = os.environ.get("PUBLIC_ACCOUNT_ID", "5OI32712")

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

def parse_chain(exp):
    p = json.loads(call("get_option_chain", {"symbol": "AMD", "expiration_date": exp, "account_id": ACCT})["content"][0]["text"])
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

leaps = parse_chain("2028-01-21")
cands = [k for k in sorted(leaps) if 350 <= k <= 520]
g = json.loads(call("get_option_greeks", {"osi_symbols": [leaps[k]["sym"] for k in cands], "account_id": ACCT})["content"][0]["text"])
deltas = {x["symbol"]: float(x["greeks"]["delta"]) for x in g["greeks"]}
long_k = min(cands, key=lambda k: abs(deltas[leaps[k]["sym"]] - 0.80))
long_o = leaps[long_k]
print(f"Long leg: Jan-2028 {long_k:.0f}C  mid=${long_o['mid']:.2f}  delta={deltas[long_o['sym']]:.2f}")

near = parse_chain("2026-11-20")
short_k = 680
short_o = near[short_k]
print(f"Short leg: Nov-20 {short_k:.0f}C  mid=${short_o['mid']:.2f} (30-delta)")

debit = long_o["mid"] - short_o["mid"]
print(f"\nNet debit: ${debit:.2f}/share = ${debit*100:,.0f} per PMCC")
print(f"Max loss (AMD to zero): ${debit*100:,.0f}  |  Breakeven at Jan-2028 expiry: ${long_k + debit:.2f}")
print(f"Monthly income yield on capital: {short_o['mid']/debit*100:.1f}% per ~40-day cycle")
print(f"Capital vs 100 shares @631: ${debit*100:,.0f} vs $63,100 ({debit*100/63100*100:.0f}% of the capital)")
print(f"If AMD assigned away above {short_k}: profit = {(short_k - long_k - debit)*100:,.0f} + keep rolling")
