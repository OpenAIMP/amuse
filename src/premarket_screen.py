#!/usr/bin/env python3
"""
Pre-market day-trading screener over the S&P 500 universe.

Designed to run ~9:00am ET before the open. For each name it computes:
  gap_pct      - (current price - prior regular-session close) / prior close
  rel_vol      - today's volume so far vs 20-day average daily volume
  vwap_dist    - distance % from the developing session VWAP
  atr_pct      - 14-day ATR as % of price (expected daily range)
  range_pos    - where price sits inside the ATR-implied expected range

Candidates pass |gap| >= 2.0%, rel_vol >= 1.5, price >= $10, ATR% 1-8,
then rank by conviction = |gap| x rel_vol. Direction is stated as a bias,
never a prediction: gap + holding above developing VWAP -> "gap-and-go
bias"; gap + back below VWAP -> "fade risk" (mirror for gap downs).

HONEST LIMITATION: the MCP has no news/catalyst feed, so gaps driven by
news cannot be classified -- treat every gap here as technical-only and
check headlines before trading any candidate.

The S&P 500 list is EMBEDDED and frozen (sourced 2026-10-11 from
https://en.wikipedia.org/wiki/List_of_S%26P_500_companies); no web fetch
happens at runtime. Dotted symbols (BRK.B, BF.B) are used verbatim --
verified against the API.
"""
import argparse
import concurrent.futures
import json
import math
import os
import statistics
import subprocess
import sys
import time
from datetime import datetime
from zoneinfo import ZoneInfo

CLI = os.environ.get("PUBLIC_MCP_CLI", "/home/hatch/workspace/skills/public-mcp/bin/public-mcp")
ACCT = os.environ.get("PUBLIC_ACCOUNT_ID") or ""
if not ACCT:
    raise SystemExit("PUBLIC_ACCOUNT_ID is not set; configure it as a repo variable/secret (#23)")

# ---- screening configuration (design choices, printed in every report) ----
# Tunables live in gates.yaml; this block binds them to module constants.
import gates as _gates_mod


def _apply_gates(path=None):
    global GAP_MIN_PCT, REL_VOL_MIN, PRICE_MIN
    global ATR_PCT_MIN, ATR_PCT_MAX, TOP_N, MIN_DAILY_BARS
    G = _gates_mod.load(path)["premarket"]
    GAP_MIN_PCT = G["gap_min_pct"]
    REL_VOL_MIN = G["rel_vol_min"]
    PRICE_MIN = G["price_min"]
    ATR_PCT_MIN, ATR_PCT_MAX = G["atr_pct_min"], G["atr_pct_max"]
    TOP_N = G["top_n"]
    MIN_DAILY_BARS = G["min_daily_bars"]


_apply_gates()
PACE_S = 0.2             # seconds between MCP calls

RUN_TS = datetime.now(ZoneInfo("America/New_York")).isoformat(timespec="seconds")
RUN_DATE_ET = datetime.now(ZoneInfo("America/New_York")).date()


class McpError(RuntimeError):
    pass


def mcp_call(tool, args):
    try:
        proc = subprocess.run([CLI, "call", tool, json.dumps(args)],
                              capture_output=True, text=True, timeout=120)
    except subprocess.TimeoutExpired as e:
        raise McpError(f"{tool}: CLI timed out: {e}")
    if proc.returncode != 0:
        raise McpError(f"{tool}: CLI failed: {proc.stderr[:300]}")
    try:
        d = json.loads(proc.stdout)
    except json.JSONDecodeError as e:
        raise McpError(f"{tool}: CLI returned non-JSON output: {e}")
    if not isinstance(d, dict) or "content" not in d or not d["content"]:
        raise McpError(f"{tool}: unexpected response shape")
    if d.get("isError"):
        raise McpError(f"{tool}: {json.dumps(d)[:300]}")
    try:
        return json.loads(d["content"][0]["text"])
    except (json.JSONDecodeError, KeyError, TypeError, IndexError) as e:
        raise McpError(f"{tool}: unparseable content payload: {e}")


# ---- Universe: shared frozen constituents (see universes.py)
try:
    from universes import UNIVERSES
    SP500 = UNIVERSES["sp500"]
except ImportError:  # pragma: no cover - standalone fallback
    SP500 = []


def quote_for(symbol):
    """Return current price from get_quotes, or None."""
    q = mcp_call("get_quotes", {"symbols": [symbol], "account_id": ACCT})
    found = [None]

    def walk(o):
        if isinstance(o, dict):
            s = o.get("instrument", {}).get("symbol")
            if s == symbol and found[0] is None:
                for k in ("last", "price", "mark"):
                    v = o.get(k)
                    try:
                        v = float(v)
                    except (TypeError, ValueError):
                        continue
                    if math.isfinite(v) and v > 0:
                        found[0] = v
                        return
            for v in o.values():
                walk(v)
                if found[0] is not None:
                    return
        elif isinstance(o, list):
            for v in o:
                walk(v)
                if found[0] is not None:
                    return

    walk(q)
    return found[0]


def quotes_for(symbols):
    """Batch quotes for many symbols in ONE get_quotes call.

    Returns {symbol: price}. Symbols missing from the payload are absent
    from the map (caller treats as unknown quote, never as zero).
    """
    out = {}
    q = mcp_call("get_quotes", {"symbols": list(symbols), "account_id": ACCT})

    def walk(o):
        if isinstance(o, dict):
            s = o.get("instrument", {}).get("symbol")
            if s in symbols and s not in out:
                for k in ("last", "price", "mark"):
                    v = o.get(k)
                    try:
                        v = float(v)
                    except (TypeError, ValueError):
                        continue
                    if math.isfinite(v) and v > 0:
                        out[s] = v
                        break
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    walk(q)
    return out


def daily_bars_for(symbol):
    """Return list of (date, close, high, low, volume), validated."""
    p = mcp_call("get_price_history",
                 {"symbol": symbol, "account_id": ACCT,
                  "period": "YEAR", "aggregation": "ONE_DAY"})
    if not isinstance(p, dict):
        raise McpError(f"get_price_history daily: bad payload for {symbol}")
    bars = []
    for b in p.get("regularMarket", {}).get("bars", []):
        try:
            c, h, l = float(b["close"]), float(b["high"]), float(b["low"])
            v = float(b["volume"])
            day = datetime.fromisoformat(b["timestamp"]).date()
        except (KeyError, TypeError, ValueError):
            continue
        if not all(math.isfinite(x) for x in (c, h, l, v)):
            continue
        if c <= 0 or h <= 0 or l <= 0 or v < 0:
            continue
        bars.append((day, c, h, l, v))
    return bars


def intraday_bars_for(symbol):
    """Return list of (date, open, high, low, close, volume) incl. pre-market."""
    p = mcp_call("get_price_history",
                 {"symbol": symbol, "account_id": ACCT,
                  "period": "DAY", "aggregation": "FIVE_MINUTES",
                  "trading_session_toggle": "REGULAR_AND_EXTENDED_HOURS"})
    if not isinstance(p, dict):
        raise McpError(f"get_price_history intraday: bad payload for {symbol}")
    bars = []
    for b in p.get("regularMarket", {}).get("bars", []):
        try:
            o, h, l, c = (float(b["open"]), float(b["high"]),
                          float(b["low"]), float(b["close"]))
            v = float(b["volume"])
            day = datetime.fromisoformat(b["timestamp"]).date()
        except (KeyError, TypeError, ValueError):
            continue
        if not all(math.isfinite(x) for x in (o, h, l, c, v)):
            continue
        if o <= 0 or h <= 0 or l <= 0 or c <= 0 or v < 0:
            continue
        bars.append((day, o, h, l, c, v))
    return bars


def atr14(bars):
    """Wilder's ATR(14) in price units. bars: (date, close, high, low, vol)."""
    if len(bars) < 15:
        return None
    trs = []
    for i in range(1, len(bars)):
        h, l = bars[i][2], bars[i][3]
        pc = bars[i - 1][1]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    a = sum(trs[:14]) / 14
    for tr in trs[14:]:
        a = (a * 13 + tr) / 14
    return a if math.isfinite(a) and a > 0 else None


def screen_one(symbol, quote_map=None):
    """Compute all pre-market signals. Returns (result_dict, [reasons]).

    quote_map: optional {symbol: price} from a batched get_quotes call.
    When provided, no per-symbol quote call is made (issue #14). When None,
    falls back to the single-symbol quote_for.

    result_dict has metrics when computable; reasons lists rejection
    categories (empty when the name qualifies). Never raises for data
    problems -- unknown metrics become rejection reasons, not crashes.
    """
    reasons = []
    res = {"symbol": symbol, "gap_pct": None, "rel_vol": None,
           "vwap_dist_pct": None, "atr_pct": None, "range_atr": None,
           "bias": None, "conviction": None, "price": None,
           "prior_close": None, "session": None}

    try:
        bars = daily_bars_for(symbol)
    except McpError as e:
        return res, [f"daily bars failed: {e}"]
    # Drop an in-progress today: prior close = last COMPLETED daily bar.
    completed = [b for b in bars if b[0] < RUN_DATE_ET] or bars
    if len(completed) < MIN_DAILY_BARS:
        return res, ["insufficient daily history"]
    prior_close = completed[-1][1]
    res["prior_close"] = prior_close
    vols = [b[4] for b in completed[-20:]]
    avg20_vol = statistics.fmean(vols) if all(v >= 0 for v in vols) else None

    atr = atr14(completed)
    if atr is None:
        return res, ["atr uncomputable"]

    try:
        if quote_map is not None:
            price = quote_map.get(symbol)
        else:
            price = quote_for(symbol)
    except McpError as e:
        return res, [f"quote failed: {e}"]
    if price is None:
        return res, ["no quote"]
    res["price"] = price
    if price < PRICE_MIN:
        reasons.append(f"price below ${PRICE_MIN:g}")

    atr_pct = atr / price * 100.0
    res["atr_pct"] = atr_pct
    if not (ATR_PCT_MIN <= atr_pct <= ATR_PCT_MAX):
        reasons.append("atr out of range")

    gap_pct = (price / prior_close - 1) * 100.0
    res["gap_pct"] = gap_pct
    if abs(gap_pct) < GAP_MIN_PCT:
        reasons.append("gap too small")

    # Position inside the ATR-implied expected daily range, in ATR units.
    res["range_atr"] = (price - prior_close) / atr

    try:
        ibars = intraday_bars_for(symbol)
    except McpError as e:
        return res, [f"intraday bars failed: {e}"]
    if not ibars:
        return res, ["no intraday bars"]
    latest_day = max(b[0] for b in ibars)
    today_bars = [b for b in ibars if b[0] == latest_day]
    res["session"] = latest_day.isoformat()
    today_vol = sum(b[5] for b in today_bars)
    if avg20_vol and avg20_vol > 0:
        rel_vol = today_vol / avg20_vol
    else:
        rel_vol = None
    res["rel_vol"] = rel_vol
    if rel_vol is None:
        reasons.append("volume baseline unknown")
    elif rel_vol < REL_VOL_MIN:
        reasons.append("volume too thin")

    # Developing session VWAP from today's bars (all sessions included).
    num = den = 0.0
    for (_d, o, h, l, c, v) in today_bars:
        tp = (h + l + c) / 3.0
        num += tp * v
        den += v
    vwap = num / den if den > 0 else None
    if vwap and vwap > 0:
        res["vwap_dist_pct"] = (price / vwap - 1) * 100.0
        above = price >= vwap
    else:
        res["vwap_dist_pct"] = None
        above = None

    # Direction read: bias, never a prediction.
    if above is None:
        res["bias"] = "unknown (no vwap)"
    elif gap_pct > 0 and above:
        res["bias"] = "gap-and-go bias"
    elif gap_pct > 0 and not above:
        res["bias"] = "fade risk"
    elif gap_pct < 0 and not above:
        res["bias"] = "gap-and-go bias (short)"
    else:
        res["bias"] = "fade risk (bounce)"

    if rel_vol is not None:
        res["conviction"] = abs(gap_pct) * rel_vol
    return res, reasons


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json-out", default=None)
    ap.add_argument("--names", default=None,
                    help="comma-separated override (default: embedded S&P 500)")
    ap.add_argument("--universe", default=None,
                    help="index universe from universes.py: sp500, sp100, nasdaq100, dow30 (--names wins)")
    ap.add_argument("--limit", type=int, default=None,
                    help="cap universe size (for tests)")
    ap.add_argument("--config", default=None,
                    help="path to gates.yaml (default: gates.yaml next to the script)")
    ap.add_argument("--workers", type=int, default=8,
                    help="concurrent MCP workers (default 8; 1 = sequential)")
    args = ap.parse_args()
    if args.config:
        _apply_gates(args.config)
    if args.names:
        names = args.names.split(",")
        universe_tag = "custom"
    elif getattr(args, "universe", None):
        from universes import UNIVERSES
        key = args.universe.strip().lower()
        if key not in UNIVERSES:
            raise SystemExit(f"unknown universe {key!r}; choose from {sorted(UNIVERSES)}")
        names = list(UNIVERSES[key])
        universe_tag = key
    else:
        names = list(SP500)
        universe_tag = "sp500"
    if args.limit:
        names = names[:args.limit]

    print(f"Pre-market gap screen -- run {RUN_TS} (America/New_York)")
    print(f"Universe: {'override' if args.names else 'S&P 500 (embedded, frozen 2026-10-11)'} "
          f"({len(names)} names)")
    print("Settings: "
          f"|gap| >= {GAP_MIN_PCT}%, rel_vol >= {REL_VOL_MIN}, "
          f"price >= ${PRICE_MIN:g}, ATR% {ATR_PCT_MIN}-{ATR_PCT_MAX}, "
          f"rank by conviction = |gap| x rel_vol, top {TOP_N}. "
          f"Gap = quote vs prior regular-session close; rel_vol = today's "
          f"volume so far (all sessions) vs 20d avg daily volume; "
          f"VWAP = developing session VWAP. "
          "LIMITATION: no news/catalyst feed via the MCP -- gaps are "
          "technical-only; check headlines before trading any candidate.")

    cands, rej = [], {}
    rej_notes = {}
    near = []  # near-misses for the report (#26)

    # One batched quote call for the whole universe (issue #14) instead of
    # one call per name. On batch failure, screen_one falls back per-name.
    quote_map = None
    try:
        quote_map = quotes_for(names)
        print(f"batched quotes: {len(quote_map)}/{len(names)} names priced",
              file=sys.stderr)
    except McpError as e:
        print(f"batched quotes failed ({e}); falling back to per-name quotes",
              file=sys.stderr)

    def safe_screen(sym):
        try:
            res, reasons = screen_one(sym, quote_map)
            return (sym, res, reasons, None)
        except McpError as e:
            return (sym, None, [], f"mcp failure: {e}")
        except Exception as e:  # one bad name never kills the run
            return (sym, None, [], f"internal error: {e}")

    workers = max(1, args.workers)
    # Merge in submission order in the main thread: no shared-state locks,
    # deterministic output regardless of worker count.
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        results = list(ex.map(safe_screen, names))

    for i, (sym, res, reasons, err) in enumerate(results):
        if err:
            key = err.split(":")[0]
            rej[key] = rej.get(key, 0) + 1
            rej_notes.setdefault(key, []).append(f"{sym}: {err}"[:90])
            continue
        if reasons:
            for r in reasons:
                key = r.split(":")[0]
                rej[key] = rej.get(key, 0) + 1
            rej_notes[sym] = reasons
            # Near-miss: rejected but close on the key gates — show what
            # almost qualified so an empty report explains itself (#26).
            gap = abs(res.get("gap_pct") or 0)
            rv = res.get("rel_vol") or 0
            if gap >= 0.5 * GAP_MIN_PCT or rv >= 0.67 * REL_VOL_MIN:
                near.append({"symbol": sym,
                             "gap_pct": res.get("gap_pct"),
                             "rel_vol": res.get("rel_vol"),
                             "price": res.get("price"),
                             "atr_pct": res.get("atr_pct"),
                             "bias": res.get("bias"),
                             "missed": reasons})
        else:
            cands.append(res)
        if workers == 1 and i < len(names) - 1:
            time.sleep(PACE_S)

    cands.sort(key=lambda r: (r["conviction"] or 0), reverse=True)
    top = cands[:TOP_N]

    print(f"\n=== TOP {TOP_N} BY CONVICTION ({len(cands)} candidates / {len(names)} screened) ===")
    print(f"{'sym':6} {'price':>8} {'gap%':>7} {'relVol':>7} {'vwapD%':>7} "
          f"{'atr%':>6} {'rngATR':>7} {'conv':>8}  bias")
    for r in top:
        vd = r["vwap_dist_pct"]
        vd_s = "   n/a" if vd is None else f"{vd:+.2f}"
        print(f"{r['symbol']:6} {r['price']:8.2f} {r['gap_pct']:+7.2f} "
              f"{r['rel_vol']:7.2f} {vd_s:>7} "
              f"{r['atr_pct']:6.2f} {r['range_atr']:+7.2f} {r['conviction']:8.1f}  "
              f"{r['bias']}")

    print("\nRejections (nothing silently dropped):")
    for k, v in sorted(rej.items(), key=lambda kv: -kv[1]):
        print(f"  {k} x{v}")

    # ---- plain-English readout ----
    print("\nREADOUT:")
    if not cands:
        print("- No names met the pre-market gates. Tape is quiet or the "
              "gates are too tight for this morning.")
        if near:
            print("- Closest near-misses:")
            for n in near[:5]:
                print(f"  {n['symbol']}: gap {n['gap_pct']:+.2f}%, "
                      f"vol {n['rel_vol']:.1f}x — missed: "
                      f"{'; '.join(n['missed'])}")
    else:
        ups = [r for r in cands if r["gap_pct"] > 0]
        dns = [r for r in cands if r["gap_pct"] < 0]
        gng = [r for r in top if "gap-and-go" in (r["bias"] or "")]
        fade = [r for r in top if "fade risk" in (r["bias"] or "")]
        if gng:
            g = gng[0]
            print(f"- Strongest gap-and-go: {g['symbol']} "
                  f"({g['gap_pct']:+.1f}% gap, {g['rel_vol']:.1f}x vol, "
                  f"{g['vwap_dist_pct']:+.2f}% vs VWAP).")
        if fade:
            f = fade[0]
            print(f"- Strongest fade risk: {f['symbol']} "
                  f"({f['gap_pct']:+.1f}% gap but "
                  f"{f['vwap_dist_pct']:+.2f}% vs VWAP -- momentum not holding).")
        avg_gap = statistics.fmean([r["gap_pct"] for r in cands])
        print(f"- Tape read: {len(cands)} candidates from {len(names)} names; "
              f"{len(ups)} gapping up, {len(dns)} gapping down; "
              f"average gap {avg_gap:+.2f}%.")
        if len(ups) > 2 * max(len(dns), 1):
            print("- Broadly risk-on pre-market: gaps skew up; favor gap-and-go "
                  "setups with VWAP holding.")
        elif len(dns) > 2 * max(len(ups), 1):
            print("- Broadly risk-off pre-market: gaps skew down; favor "
                  "short-side gap-and-go or stand aside.")
        else:
            print("- Mixed tape: trade names individually on their own "
                  "VWAP/volume read, not the market.")
    print("Bias is not a prediction -- check headlines, then manage the open.")

    if args.json_out:
        # Sort near-misses by conviction proxy (|gap| x rel_vol), top 5
        near_sorted = sorted(
            near,
            key=lambda n: abs(n["gap_pct"] or 0) * (n["rel_vol"] or 0),
            reverse=True)[:5]
        with open(args.json_out, "w") as f:
            json.dump({"run": RUN_TS, "universe": len(names),
                       "settings": {"gap_min_pct": GAP_MIN_PCT,
                                    "rel_vol_min": REL_VOL_MIN,
                                    "price_min": PRICE_MIN,
                                    "atr_pct_min": ATR_PCT_MIN,
                                    "atr_pct_max": ATR_PCT_MAX},
                       "candidates": top,
                       "near_misses": near_sorted,
                       "rejections": rej}, f, indent=1)
        print(f"\nwrote {args.json_out}")


if __name__ == "__main__":
    main()
