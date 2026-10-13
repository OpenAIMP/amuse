"""Historical calibration/backtest for screened verticals and iron condors.

Local research tool: it does not fetch data or place orders. Each record is a
screened structure captured at entry with its modeled POP/EV and the features
known at that time; settlement uses the supplied underlying closes. Holds to
expiry (no early-exit modeling). Per-share dollars are scaled by 100.

Lookahead guard: a record whose ``as_of`` (when its inputs were observed) is
after ``entry_date`` is rejected, and settlement uses only the underlying close
on the expiry date. Records with missing/invalid data are skipped and reported,
never raised.
"""
import argparse
import json
import math
from datetime import date

STRATEGIES = ("bull_put", "bear_call", "iron_condor")
MULT = 100.0

IV_RANK_BINS = [(0, 25, "0-25"), (25, 50, "25-50"), (50, 75, "50-75"),
                (75, 101, "75-100")]
DTE_BINS = [(0, 21, "0-20"), (21, 36, "21-35"), (36, 61, "36-60"),
            (61, 10**6, "61+")]
DELTA_BINS = [(0, 0.10, "<0.10"), (0.10, 0.15, "0.10-0.15"),
              (0.15, 0.20, "0.15-0.20"), (0.20, 10, ">=0.20")]
WIDTH_BINS = [(0, 2.5, "<2.5"), (2.5, 5, "2.5-<5"), (5, 10, "5-<10"),
              (10, 10**6, "10+")]


def _num(v):
    if isinstance(v, bool) or v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _date(v):
    try:
        return date.fromisoformat(str(v)[:10])
    except (TypeError, ValueError):
        return None


def _bucket(value, bins):
    if value is None:
        return "unknown"
    for lo, hi, label in bins:
        if lo <= value < hi:
            return label
    return "unknown"


def _payoff_per_share(rec, close):
    """Expiry P&L per share for one structure at underlying close."""
    credit = rec["credit"]
    kind = rec["strategy"]
    loss = 0.0
    if kind in ("bull_put", "iron_condor"):
        loss += max(rec["short_put"] - close, 0) - max(rec["long_put"] - close, 0)
    if kind in ("bear_call", "iron_condor"):
        loss += max(close - rec["short_call"], 0) - max(close - rec["long_call"], 0)
    return credit - loss


def _normalize(rec):
    """Validate a record. Returns (normalized, None) or (None, reason)."""
    if not isinstance(rec, dict):
        return None, "not an object"
    kind = rec.get("strategy")
    if kind not in STRATEGIES:
        return None, "unknown strategy"
    entry, expiry = _date(rec.get("entry_date")), _date(rec.get("expiry"))
    if entry is None or expiry is None or expiry <= entry:
        return None, "invalid dates"
    as_of = rec.get("as_of")
    if as_of is not None:
        as_of_d = _date(as_of)
        if as_of_d is None:
            return None, "invalid as_of"
        if as_of_d > entry:
            return None, "lookahead: as_of after entry_date"
    credit = _num(rec.get("credit"))
    if credit is None or credit <= 0:
        return None, "missing credit"
    out = {"id": rec.get("id"), "symbol": rec.get("symbol"), "strategy": kind,
           "entry_date": entry, "expiry": expiry, "credit": credit}
    strikes = {"bull_put": ("short_put", "long_put"),
               "bear_call": ("short_call", "long_call"),
               "iron_condor": ("short_put", "long_put",
                               "short_call", "long_call")}[kind]
    for k in strikes:
        v = _num(rec.get(k))
        if v is None:
            return None, "missing strike " + k
        out[k] = v
    widths = []
    if "short_put" in out:
        widths.append(out["short_put"] - out["long_put"])
    if "short_call" in out:
        widths.append(out["long_call"] - out["short_call"])
    if any(w <= 0 for w in widths):
        return None, "invalid strikes"
    out["width"] = max(widths)
    if credit >= out["width"]:
        return None, "credit exceeds width"
    out["max_loss"] = (out["width"] - credit) * MULT
    out["dte"] = (expiry - entry).days
    for k in ("modeled_pop", "modeled_ev", "iv_rank", "short_delta"):
        out[k] = _num(rec.get(k))
    if out["modeled_pop"] is not None and not 0 <= out["modeled_pop"] <= 1:
        out["modeled_pop"] = None
    out["regime"] = str(rec.get("regime") or "unknown")
    return out, None


def run_backtest(records, closes):
    """Settle records. ``closes``: {symbol: {iso_date: close}}.

    Returns {"trades": [...chronological...], "skipped": [{id, reason}]}.
    """
    trades, skipped = [], []
    for i, rec in enumerate(records or []):
        n, why = _normalize(rec)
        if n is None:
            skipped.append({"id": (rec or {}).get("id", i)
                            if isinstance(rec, dict) else i, "reason": why})
            continue
        series = (closes or {}).get(n["symbol"]) or {}
        close = _num(series.get(n["expiry"].isoformat()))
        if close is None or close <= 0:
            skipped.append({"id": n["id"] if n["id"] is not None else i,
                            "reason": "missing expiry close"})
            continue
        pnl = _payoff_per_share(n, close) * MULT
        n.update(close=close, pnl=pnl, r_multiple=pnl / n["max_loss"],
                 win=pnl > 0)
        trades.append(n)
    trades.sort(key=lambda t: (t["expiry"], t["entry_date"]))
    return {"trades": trades, "skipped": skipped}


def _quantile(sorted_vals, q):
    if not sorted_vals:
        return None
    pos = (len(sorted_vals) - 1) * q
    lo, hi = int(math.floor(pos)), int(math.ceil(pos))
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (pos - lo)


def metrics(trades):
    """Aggregate realized stats and compare to modeled POP/EV."""
    n = len(trades)
    if n == 0:
        return {"n": 0}
    pnls = [t["pnl"] for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    gross_win, gross_loss = sum(wins), -sum(losses)
    equity = peak = dd = 0.0
    for p in pnls:
        equity += p
        peak = max(peak, equity)
        dd = max(dd, peak - equity)
    rs = sorted(t["r_multiple"] for t in trades)
    out = {
        "n": n,
        "win_rate": len(wins) / n,
        "avg_win": gross_win / len(wins) if wins else None,
        "avg_loss": -gross_loss / len(losses) if losses else None,
        "realized_ev": sum(pnls) / n,
        "total_pnl": sum(pnls),
        "max_drawdown": dd,
        "profit_factor": (gross_win / gross_loss if gross_loss > 0
                          else (math.inf if gross_win > 0 else None)),
        "r_multiple": {"mean": sum(rs) / n, "min": rs[0], "p25": _quantile(rs, .25),
                       "median": _quantile(rs, .5), "p75": _quantile(rs, .75),
                       "max": rs[-1]},
    }
    pops = [t["modeled_pop"] for t in trades if t["modeled_pop"] is not None]
    evs = [t["modeled_ev"] for t in trades if t["modeled_ev"] is not None]
    out["modeled_pop"] = sum(pops) / len(pops) if pops else None
    out["modeled_ev"] = sum(evs) / len(evs) if evs else None
    out["pop_gap"] = (out["win_rate"] - out["modeled_pop"]
                      if pops else None)
    out["ev_gap"] = (out["realized_ev"] - out["modeled_ev"]
                     if evs else None)
    return out


SEGMENTS = {
    "iv_rank": lambda t: _bucket(t["iv_rank"], IV_RANK_BINS),
    "dte": lambda t: _bucket(t["dte"], DTE_BINS),
    "short_delta": lambda t: _bucket(
        abs(t["short_delta"]) if t["short_delta"] is not None else None,
        DELTA_BINS),
    "spread_width": lambda t: _bucket(t["width"], WIDTH_BINS),
    "strategy": lambda t: t["strategy"],
    "regime": lambda t: t["regime"],
}


def segment(trades):
    """Metrics per segment value for each dimension."""
    out = {}
    for name, fn in SEGMENTS.items():
        groups = {}
        for t in trades:
            groups.setdefault(fn(t), []).append(t)
        out[name] = {k: metrics(v) for k, v in sorted(groups.items())}
    return out


def out_of_sample(trades, train_fraction=0.7):
    """Chronological split: earlier trades in-sample, later out-of-sample."""
    if not 0 < train_fraction < 1:
        raise ValueError("train_fraction must be between 0 and 1")
    cut = int(len(trades) * train_fraction)
    return {"in_sample": metrics(trades[:cut]),
            "out_of_sample": metrics(trades[cut:])}


def walk_forward(trades, train_days, test_days, step_days=None):
    """Rolling windows by expiry date: train on [s, s+train), test the next
    ``test_days``. Trades are assigned by expiry (when P&L becomes known)."""
    if train_days <= 0 or test_days <= 0:
        raise ValueError("train_days and test_days must be positive")
    step = step_days or test_days
    if step <= 0:
        raise ValueError("step_days must be positive")
    if not trades:
        return []
    first, last = trades[0]["expiry"].toordinal(), trades[-1]["expiry"].toordinal()
    folds, start = [], first
    while start + train_days <= last:
        t_end = start + train_days
        train = [t for t in trades if start <= t["expiry"].toordinal() < t_end]
        test = [t for t in trades
                if t_end <= t["expiry"].toordinal() < t_end + test_days]
        folds.append({"train_start": date.fromordinal(start).isoformat(),
                      "test_start": date.fromordinal(t_end).isoformat(),
                      "test_end": date.fromordinal(t_end + test_days).isoformat(),
                      "train": metrics(train), "test": metrics(test)})
        start += step
    return folds


def report(records, closes, train_fraction=0.7, wf_train_days=None,
           wf_test_days=None):
    res = run_backtest(records, closes)
    trades = res["trades"]
    out = {"overall": metrics(trades), "segments": segment(trades),
           "out_of_sample": out_of_sample(trades, train_fraction),
           "skipped": res["skipped"]}
    if wf_train_days and wf_test_days:
        out["walk_forward"] = walk_forward(trades, wf_train_days, wf_test_days)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("input", help="JSON: {\"records\": [...], \"closes\": {...}}")
    ap.add_argument("--train-fraction", type=float, default=0.7)
    ap.add_argument("--wf-train-days", type=int)
    ap.add_argument("--wf-test-days", type=int)
    a = ap.parse_args()
    with open(a.input) as fh:
        data = json.load(fh)
    print(json.dumps(report(data.get("records"), data.get("closes"),
                            a.train_fraction, a.wf_train_days, a.wf_test_days),
                     indent=2, default=str))


if __name__ == "__main__":
    main()
