#!/usr/bin/env python3
"""
Intraday momentum screener (issue #27).

Designed to run at 11:00am and 2:00pm ET on weekdays -- signals that work
mid-session, not pre-market. For each name it computes:

  orb_break    - opening-range breakout: 15-min OR (9:30-9:45 ET) high/low;
                 price beyond OR +/- buffer
  vwap_signal  - VWAP reclaim (was below, now above) or VWAP loss
  rel_vol_tp   - today's volume so far vs TIME-PRORATED 20-day average
                 (fixes the premarket flaw of comparing partial-day volume
                 to a full-day average)

Candidates pass: price >= $10, ATR% 1-8, rel_vol_tp >= 1.5, and at least
one of ORB breakout / VWAP cross. Ranked by conviction.

Signals are technical-only; check headlines before trading. Direction is
a bias, never a prediction.

Stdlib only. Mirrors premarket_screen.py structure (issue #14 batching,
#23 account requirement).
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
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

CLI = os.environ.get("PUBLIC_MCP_CLI", "/home/hatch/workspace/skills/public-mcp/bin/public-mcp")
ACCT = os.environ.get("PUBLIC_ACCOUNT_ID") or ""
if not ACCT:
    raise SystemExit("PUBLIC_ACCOUNT_ID is not set; configure it as a repo variable/secret (#23)")

ET = ZoneInfo("America/New_York")
MARKET_OPEN_MIN = 9 * 60 + 30   # 9:30 ET in minutes since midnight
MARKET_CLOSE_MIN = 16 * 60      # 16:00 ET
SESSION_MINUTES = MARKET_CLOSE_MIN - MARKET_OPEN_MIN  # 390

import gates as _gates_mod


def _apply_gates(path=None):
    global OR_MINUTES, BREAKOUT_BUFFER_PCT, REL_VOL_MIN, PRICE_MIN
    global ATR_PCT_MIN, ATR_PCT_MAX, TOP_N, MIN_DAILY_BARS, VWAP_LOOKBACK_BARS
    G = _gates_mod.load(path)["intraday"]
    OR_MINUTES = G["or_minutes"]
    BREAKOUT_BUFFER_PCT = G["breakout_buffer_pct"]
    REL_VOL_MIN = G["rel_vol_min"]
    PRICE_MIN = G["price_min"]
    ATR_PCT_MIN, ATR_PCT_MAX = G["atr_pct_min"], G["atr_pct_max"]
    TOP_N = G["top_n"]
    MIN_DAILY_BARS = G["min_daily_bars"]
    VWAP_LOOKBACK_BARS = G["vwap_lookback_bars"]


_apply_gates()
PACE_S = 0.2

RUN_TS = datetime.now(ET).isoformat(timespec="seconds")
RUN_DATE_ET = datetime.now(ET).date()


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


try:
    from universes import UNIVERSES
    NASDAQ100 = UNIVERSES["nasdaq100"]
except ImportError:  # pragma: no cover - standalone fallback
    NASDAQ100 = []


def quotes_for(symbols):
    """Batch quotes for many symbols in ONE get_quotes call."""
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


def intraday_bars_today(symbol):
    """Today's intraday bars with ET datetimes: (dt, o, h, l, c, v).

    Regular session only (9:30-16:00 ET). Returns [] outside market hours
    or when no bars are available.
    """
    p = mcp_call("get_price_history",
                 {"symbol": symbol, "account_id": ACCT,
                  "period": "DAY", "aggregation": "FIVE_MINUTES",
                  "trading_session_toggle": "REGULAR_HOURS"})
    if not isinstance(p, dict):
        raise McpError(f"get_price_history intraday: bad payload for {symbol}")
    bars = []
    for b in p.get("regularMarket", {}).get("bars", []):
        try:
            o, h, l, c = (float(b["open"]), float(b["high"]),
                          float(b["low"]), float(b["close"]))
            v = float(b["volume"])
            ts = datetime.fromisoformat(b["timestamp"])
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=ET)
            else:
                ts = ts.astimezone(ET)
        except (KeyError, TypeError, ValueError):
            continue
        if not all(math.isfinite(x) for x in (o, h, l, c, v)):
            continue
        if o <= 0 or h <= 0 or l <= 0 or c <= 0 or v < 0:
            continue
        if ts.date() != RUN_DATE_ET:
            continue
        mins = ts.hour * 60 + ts.minute
        if not (MARKET_OPEN_MIN <= mins < MARKET_CLOSE_MIN):
            continue
        bars.append((ts, o, h, l, c, v))
    bars.sort(key=lambda b: b[0])
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


def session_vwap(bars):
    """Cumulative VWAP over the given intraday bars. None if no volume."""
    num = den = 0.0
    for (_ts, o, h, l, c, v) in bars:
        tp = (h + l + c) / 3.0
        num += tp * v
        den += v
    return num / den if den > 0 else None


def screen_one(symbol, quote_map=None, now_et=None):
    """Compute intraday momentum signals. Returns (result_dict, [reasons]).

    result_dict has metrics when computable; reasons lists rejection
    categories (empty when the name qualifies). Never raises for data
    problems.
    """
    reasons = []
    res = {"symbol": symbol, "price": None, "orb_high": None,
           "orb_low": None, "orb_signal": None, "vwap": None,
           "vwap_dist_pct": None, "vwap_signal": None,
           "rel_vol_tp": None, "atr_pct": None, "conviction": None,
           "bias": None}
    now_et = now_et or datetime.now(ET)

    # --- daily context: ATR and 20d avg volume ---
    try:
        bars = daily_bars_for(symbol)
    except McpError as e:
        return res, [f"daily bars failed: {e}"]
    completed = [b for b in bars if b[0] < RUN_DATE_ET] or bars
    if len(completed) < MIN_DAILY_BARS:
        return res, ["insufficient daily history"]
    vols = [b[4] for b in completed[-20:]]
    avg20_vol = statistics.fmean(vols) if all(v >= 0 for v in vols) else None
    atr = atr14(completed)
    if atr is None:
        return res, ["atr uncomputable"]

    # --- current price ---
    try:
        price = (quote_map or {}).get(symbol)
        if price is None:
            q = mcp_call("get_quotes", {"symbols": [symbol],
                                        "account_id": ACCT})
            # reuse walk logic inline
            found = [None]

            def walk(o):
                if isinstance(o, dict):
                    s = o.get("instrument", {}).get("symbol")
                    if s == symbol and found[0] is None:
                        for k in ("last", "price", "mark"):
                            try:
                                v = float(o.get(k))
                            except (TypeError, ValueError):
                                continue
                            if math.isfinite(v) and v > 0:
                                found[0] = v
                                return
                    for v in o.values():
                        walk(v)
                elif isinstance(o, list):
                    for v in o:
                        walk(v)
            walk(q)
            price = found[0]
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

    # --- intraday bars ---
    try:
        ibars = intraday_bars_today(symbol)
    except McpError as e:
        return res, [f"intraday bars failed: {e}"]
    if not ibars:
        return res, ["no intraday bars (market closed or no data)"]

    # --- opening range: session-aware "broke out and holding" ---
    # Old logic asked "is it breaking out THIS MINUTE" -- too narrow.
    # New: did it break the OR at any point today, and is it holding?
    or_end_min = MARKET_OPEN_MIN + OR_MINUTES
    or_bars = [b for b in ibars
               if b[0].hour * 60 + b[0].minute < or_end_min]
    if not or_bars:
        return res, ["opening range not yet formed"]
    orb_high = max(b[2] for b in or_bars)
    orb_low = min(b[3] for b in or_bars)
    res["orb_high"], res["orb_low"] = orb_high, orb_low
    buf = BREAKOUT_BUFFER_PCT / 100.0
    post_or = [b for b in ibars
               if b[0].hour * 60 + b[0].minute >= or_end_min]
    # holding tolerance: allow pullback up to 0.25x ATR inside the OR
    hold_tol = (0.25 * atr / orb_high) if orb_high > 0 else 0
    broke_up = any(b[2] > orb_high * (1 + buf) for b in post_or)
    holding_up = price > orb_high * (1 - hold_tol)
    broke_down = any(b[3] < orb_low * (1 - buf) for b in post_or)
    holding_down = price < orb_low * (1 + hold_tol)
    res["orb_broke_up"] = broke_up
    res["orb_broke_down"] = broke_down
    if broke_up and holding_up:
        res["orb_signal"] = "breakout_up_hold"
    elif broke_down and holding_down:
        res["orb_signal"] = "breakdown_down_hold"
    elif broke_up:
        res["orb_signal"] = "breakout_up_faded"
    elif broke_down:
        res["orb_signal"] = "breakdown_down_faded"

    # --- session VWAP: sustained position, not just the cross moment ---
    # Old logic only saw crosses in the last 30 min. New: what fraction of
    # the session has price held above/below the developing VWAP?
    vwap = session_vwap(ibars)
    res["vwap"] = vwap
    if vwap and vwap > 0:
        res["vwap_dist_pct"] = (price / vwap - 1) * 100.0
        # rolling VWAP position across post-OR bars
        above_ct = below_ct = 0
        num = den = 0.0
        for b in post_or:
            tp = (b[2] + b[3] + b[4]) / 3.0
            num += tp * b[5]
            den += b[5]
            rv = num / den if den > 0 else None
            if rv and rv > 0:
                if b[4] > rv:
                    above_ct += 1
                elif b[4] < rv:
                    below_ct += 1
        total = above_ct + below_ct
        res["vwap_above_pct"] = (100.0 * above_ct / total) if total else None
        if total >= 6:  # need a meaningful sample
            if above_ct / total >= 0.70:
                res["vwap_signal"] = "sustained_above"
            elif below_ct / total >= 0.70:
                res["vwap_signal"] = "sustained_below"
        # keep the cross signal too for fresh moves
        lookback = ibars[-VWAP_LOOKBACK_BARS:] if len(ibars) >= VWAP_LOOKBACK_BARS else ibars
        vw_early = session_vwap(lookback[:-1]) if len(lookback) > 1 else None
        if vw_early and not res["vwap_signal"]:
            was_below = lookback[0][4] < vw_early
            now_above = price > vwap
            was_above = lookback[0][4] > vw_early
            now_below = price < vwap
            if was_below and now_above:
                res["vwap_signal"] = "reclaim_up"
            elif was_above and now_below:
                res["vwap_signal"] = "loss_down"
    else:
        res["vwap_dist_pct"] = None

    # --- time-prorated relative volume ---
    elapsed_min = max(1, (now_et.hour * 60 + now_et.minute) - MARKET_OPEN_MIN)
    elapsed_min = min(elapsed_min, SESSION_MINUTES)
    today_vol = sum(b[5] for b in ibars)
    if avg20_vol and avg20_vol > 0:
        expected_so_far = avg20_vol * (elapsed_min / SESSION_MINUTES)
        rel_vol_tp = today_vol / expected_so_far if expected_so_far > 0 else None
    else:
        rel_vol_tp = None
    res["rel_vol_tp"] = rel_vol_tp
    res["elapsed_min"] = elapsed_min
    if rel_vol_tp is None:
        reasons.append("volume baseline unknown")
    elif rel_vol_tp < REL_VOL_MIN:
        reasons.append("volume too thin (time-prorated)")

    # --- signal gate: session-aware, with momentum-watch fallback ---
    # Strict: ORB breakout-and-hold or sustained VWAP position.
    # Fallback: strong volume + directional drift still earns a
    # "momentum_watch" row -- an intraday screen should never be blank.
    has_strict = bool(res["orb_signal"] in ("breakout_up_hold", "breakdown_down_hold")
                      or res["vwap_signal"] in ("sustained_above", "sustained_below",
                                                "reclaim_up", "loss_down"))
    if not has_strict:
        # fallback: notable volume with a clear directional drift
        drift = (res["vwap_dist_pct"] or 0)
        if (rel_vol_tp is not None and rel_vol_tp >= REL_VOL_MIN
                and abs(drift) >= 0.5):
            res["orb_signal"] = res["orb_signal"] or "momentum_watch"
            res["bias"] = ("bullish drift" if drift > 0
                           else "bearish drift")
            res["conviction"] = abs(drift) * rel_vol_tp
        else:
            reasons.append("no session momentum signal")

    # --- bias and conviction ---
    sigs = [s for s in (res["orb_signal"], res["vwap_signal"]) if s]
    if sigs and not res.get("conviction"):
        up = sum(1 for s in sigs if "up" in s or "above" in s)
        dn = sum(1 for s in sigs if "down" in s or "below" in s)
        if not res.get("bias"):
            res["bias"] = ("bullish momentum" if up > dn
                           else "bearish momentum" if dn > up else "mixed")
        dist = abs(res["vwap_dist_pct"] or 0)
        if res["orb_signal"] in ("breakout_up_hold", "breakout_up_faded"):
            dist = max(dist, (price / orb_high - 1) * 100.0)
        elif res["orb_signal"] in ("breakdown_down_hold", "breakdown_down_faded"):
            dist = max(dist, (orb_low / price - 1) * 100.0)
        res["conviction"] = (abs(dist) + 0.5) * (rel_vol_tp or 0)
    elif not sigs:
        res["bias"] = res.get("bias") or "no signal"
    return res, reasons


def main():
    ap = argparse.ArgumentParser(description="Intraday momentum screener (#27)")
    ap.add_argument("--json-out", default=None)
    ap.add_argument("--names", default=None,
                    help="comma-separated override (default: Nasdaq-100)")
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
    else:
        names = list(NASDAQ100)
        universe_tag = "nasdaq100"
    if args.limit:
        names = names[:args.limit]

    now_et = datetime.now(ET)
    print(f"Intraday momentum screen -- run {RUN_TS} (America/New_York)")
    print(f"Universe: {universe_tag} ({len(names)} names)")
    print(f"Settings: OR {OR_MINUTES}min, breakout buffer {BREAKOUT_BUFFER_PCT}%, "
          f"rel_vol_tp >= {REL_VOL_MIN} (time-prorated), price >= ${PRICE_MIN:g}, "
          f"ATR% {ATR_PCT_MIN}-{ATR_PCT_MAX}, top {TOP_N}. "
          f"VWAP = session VWAP; rel_vol_tp = today's volume vs "
          f"20d avg prorated by elapsed session time.")

    # market-hours guard
    mins_now = now_et.hour * 60 + now_et.minute
    if not (MARKET_OPEN_MIN <= mins_now < MARKET_CLOSE_MIN):
        print(f"NOTE: outside regular session hours ({now_et:%H:%M} ET); "
              f"intraday signals need live session bars.")

    cands, rej = [], {}
    rej_notes = {}
    near = []

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
            res, reasons = screen_one(sym, quote_map, now_et)
            return (sym, res, reasons, None)
        except McpError as e:
            return (sym, None, [], f"mcp failure: {e}")
        except Exception as e:  # one bad name never kills the run
            return (sym, None, [], f"internal error: {e}")

    workers = max(1, args.workers)
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        results = list(ex.map(safe_screen, names))

    for sym, res, reasons, err in results:
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
            # near-miss: has a signal but missed volume gate
            if (res.get("orb_signal") or res.get("vwap_signal")) and res.get("rel_vol_tp"):
                near.append({"symbol": sym,
                             "signal": res.get("orb_signal") or res.get("vwap_signal"),
                             "rel_vol_tp": res.get("rel_vol_tp"),
                             "price": res.get("price"),
                             "vwap_dist_pct": res.get("vwap_dist_pct"),
                             "bias": res.get("bias"),
                             "missed": reasons})
        else:
            cands.append(res)

    cands.sort(key=lambda r: (r["conviction"] or 0), reverse=True)
    top = cands[:TOP_N]

    print(f"\n=== TOP {TOP_N} BY CONVICTION ({len(cands)} candidates / {len(names)} screened) ===")
    print(f"{'sym':6} {'price':>8} {'signal':>14} {'relVolTP':>9} {'vwapD%':>7} "
          f"{'atr%':>6} {'conv':>8}  bias")
    for r in top:
        vd = r["vwap_dist_pct"]
        vd_s = "   n/a" if vd is None else f"{vd:+.2f}"
        sig = r["orb_signal"] or r["vwap_signal"] or "-"
        print(f"{r['symbol']:6} {r['price']:8.2f} {sig:>14} "
              f"{(r['rel_vol_tp'] or 0):9.2f} {vd_s:>7} "
              f"{r['atr_pct']:6.2f} {(r['conviction'] or 0):8.1f}  "
              f"{r['bias']}")

    print("\nRejections (nothing silently dropped):")
    for k, v in sorted(rej.items(), key=lambda kv: -kv[1]):
        print(f"  {k} x{v}")

    print("\nREADOUT:")
    if not cands:
        print("- No names met the intraday gates.")
        if near:
            print("- Closest near-misses (signal fired, volume gate missed):")
            for n in near[:5]:
                print(f"  {n['symbol']}: {n['signal']}, "
                      f"vol {n['rel_vol_tp']:.2f}x (need {REL_VOL_MIN}x) — "
                      f"{'; '.join(n['missed'])}")
    else:
        ups = [r for r in cands if (r["bias"] or "").startswith("bullish")]
        dns = [r for r in cands if (r["bias"] or "").startswith("bearish")]
        orbs = [r for r in top if r["orb_signal"]]
        vws = [r for r in top if r["vwap_signal"] and not r["orb_signal"]]
        if orbs:
            o = orbs[0]
            print(f"- Strongest ORB: {o['symbol']} {o['orb_signal']} "
                  f"({o['rel_vol_tp']:.1f}x prorated vol).")
        if vws:
            w = vws[0]
            print(f"- Strongest VWAP cross: {w['symbol']} {w['vwap_signal']} "
                  f"({w['vwap_dist_pct']:+.2f}% vs VWAP).")
        print(f"- Tape read: {len(cands)} candidates from {len(names)} names; "
              f"{len(ups)} bullish, {len(dns)} bearish.")
    print("Bias is not a prediction -- check headlines, then manage risk.")

    if args.json_out:
        near_sorted = sorted(
            near, key=lambda n: (n["rel_vol_tp"] or 0), reverse=True)[:5]
        with open(args.json_out, "w") as f:
            json.dump({"run": RUN_TS, "universe": len(names),
                       "universe_tag": universe_tag,
                       "settings": {"or_minutes": OR_MINUTES,
                                    "breakout_buffer_pct": BREAKOUT_BUFFER_PCT,
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
