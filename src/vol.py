"""Cheap-vs-expensive volatility framework (issue #7).

Answers the question the system never asked: is premium worth selling here?

Pure functions over inputs the screeners already have or can collect:
- HV from daily bars (annualized stdev of log returns, 20/60-day)
- IV Rank from an accumulated IV snapshot history (the MCP has no
  historical-IV endpoint, so history is built forward from daily snapshots)
- 25-delta put/call skew and near-vs-far term structure from chain Greeks

Decision rules (tunable in gates.yaml [vol]):
- IVR > ivr_sell AND IV > HV  -> SELL_PREMIUM (rich vol, edge to the seller)
- IVR < ivr_stand_down        -> STAND_DOWN (cheap vol; no long-premium
                                 structures exist yet, so stand down)
- otherwise / insufficient data -> NO_READ (no vol opinion; other gates decide)

Stdlib only. No I/O except the snapshot-history helpers.
"""

import json
import math
import os
from datetime import date

SELL_PREMIUM = "SELL_PREMIUM"
STAND_DOWN = "STAND_DOWN"
NO_READ = "NO_READ"

TRADING_DAYS = 252


def log_returns(closes):
    """Per-period log returns from a price series."""
    return [math.log(closes[i] / closes[i - 1])
            for i in range(1, len(closes)) if closes[i - 1] > 0]


def realized_vol(closes, window):
    """Annualized historical volatility over the last `window` returns.

    Returns None when there are not enough bars.
    """
    rets = log_returns(closes)
    if len(rets) < window:
        return None
    sample = rets[-window:]
    mean = sum(sample) / len(sample)
    var = sum((r - mean) ** 2 for r in sample) / (len(sample) - 1)
    return math.sqrt(var * TRADING_DAYS)


def iv_rank(current_iv, history):
    """Percentile rank of current IV within trailing history (0-100).

    Returns None when history is empty.
    """
    if not history:
        return None
    below = sum(1 for h in history if h < current_iv)
    return 100.0 * below / len(history)


def iv_vs_hv(iv, hv):
    """Ratio of implied to historical vol. >1 means options price more
    movement than recently realized (richer premium)."""
    if iv is None or hv is None or hv <= 0:
        return None
    return iv / hv


def skew(put25_iv, call25_iv):
    """25-delta put/call skew: how much extra investors pay for downside
    protection. Positive = crash premium."""
    if put25_iv is None or call25_iv is None:
        return None
    return put25_iv - call25_iv


def term_structure(iv_near, iv_far):
    """Near-vs-far term structure. Positive = contango (far richer than
    near); negative = backwardation (near-term event priced in)."""
    if iv_near is None or iv_far is None:
        return None
    return iv_far - iv_near


def assess(iv, hv, history, put25_iv=None, call25_iv=None,
           iv_near=None, iv_far=None, cfg=None):
    """Full vol assessment. Returns a dict with the read and the decision.

    history : list of past IV snapshots for this underlying (floats)
    """
    cfg = cfg or {}
    ivr_sell = cfg.get("ivr_sell", 50)
    ivr_stand_down = cfg.get("ivr_stand_down", 25)
    min_history = cfg.get("min_iv_history", 30)

    ivr = iv_rank(iv, history) if len(history) >= min_history else None
    ratio = iv_vs_hv(iv, hv)

    read = {
        "iv": iv,
        "hv": hv,
        "iv_rank": round(ivr, 1) if ivr is not None else None,
        "iv_vs_hv": round(ratio, 2) if ratio is not None else None,
        "skew_25d": skew(put25_iv, call25_iv),
        "term_structure": term_structure(iv_near, iv_far),
        "decision": NO_READ,
        "reason": "insufficient data for a vol read",
    }

    if ivr is None or ratio is None:
        return read
    if ivr < ivr_stand_down:
        read["decision"] = STAND_DOWN
        read["reason"] = (f"IV rank {ivr:.0f} < {ivr_stand_down}: premium is "
                          "cheap; stand down (no long-premium structures yet)")
    elif ivr > ivr_sell and ratio > 1.0:
        read["decision"] = SELL_PREMIUM
        read["reason"] = (f"IV rank {ivr:.0f} > {ivr_sell} and IV/HV "
                          f"{ratio:.2f} > 1: premium is rich; edge to sellers")
    else:
        read["reason"] = "vol neither rich nor cheap enough for a read"
    return read


def record_snapshot(path, underlying, iv, day=None):
    """Append a {date, underlying, iv} snapshot; creates the file if needed."""
    day = day or date.today().isoformat()
    line = json.dumps({"date": day, "underlying": underlying, "iv": iv})
    with open(path, "a") as f:
        f.write(line + "\n")


def load_history(path, underlying, max_points=252):
    """Trailing IV snapshots for one underlying, oldest first."""
    if not os.path.exists(path):
        return []
    out = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if rec.get("underlying") == underlying and rec.get("iv"):
                out.append(rec["iv"])
    return out[-max_points:]
