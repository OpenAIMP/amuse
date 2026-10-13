#!/usr/bin/env python3
"""
Pre-market gap and opening-range screener over a configurable equity universe.

Designed to run ~9:00am ET before the open. For each name it computes:
  gap_pct      - (current price - prior regular-session close) / prior close
  mode         - premarket before 9:30 ET; opening_range at/after the open
  rel_vol      - unavailable premarket without a time-matched history baseline;
                 after open, regular volume vs time-prorated average daily volume
  vwap_dist    - distance % from premarket or regular-session VWAP by mode
  atr_pct      - 14-day ATR as % of price (expected daily range)
  gap_atr      - absolute gap normalized by ATR percentage

Premarket mode gates on gap, price, and ATR, then ranks by |gap| / ATR%;
same-time premarket RVOL is accumulated from cached prior-run snapshots because
Public provides no historical premarket bars. Until 20 same-time samples exist,
the premarket volume gate is disabled and ranking falls back to |gap| / ATR%.
Opening-range mode gates on those metrics plus regular-session volume versus
the elapsed-time-prorated 20-day average (1.5x minimum), then ranks by
(|gap| / ATR%) x relative volume. Direction is a bias, never a prediction.

HONEST LIMITATION: the MCP has no news/catalyst feed, so gaps driven by
news cannot be classified -- treat every gap here as technical-only and
check headlines before trading any candidate.

The default universe is NASDAQ-100; index universes are embedded and frozen
under src/universes/. No web fetch happens at runtime.
"""
import argparse
import concurrent.futures
import json
import os
import statistics
import sys
import time
from datetime import datetime, time as wall_time, timedelta
from zoneinfo import ZoneInfo


ACCT = os.environ.get("PUBLIC_ACCOUNT_ID") or ""
if not ACCT:
    raise SystemExit("PUBLIC_ACCOUNT_ID is not set; set the environment variable locally or configure the GitHub Actions repository secret (#23)")

# ---- screening configuration (design choices, printed in every report) ----
# Tunables live in gates.yaml; this block binds them to module constants.
import gates as _gates_mod
from mcp_client import McpError
from market_data import daily_bars, intraday_bars, quotes
from market_data import quote as quote_one
from indicators import atr as calc_atr
from indicators import vwap as calc_vwap
from screening_common import evaluation_record, qualification_counts, rank_qualified


def _apply_gates(path=None):
    global GAP_MIN_PCT, PREMARKET_REL_VOL_MIN, PREMARKET_LOOKBACK, PREMARKET_BUCKET
    global OPEN_REL_VOL_MIN, PRICE_MIN
    global ATR_PCT_MIN, ATR_PCT_MAX, TOP_N, MIN_DAILY_BARS
    config = _gates_mod.load(path)
    G = config["premarket"]
    GAP_MIN_PCT = G["gap_min_pct"]
    PREMARKET_REL_VOL_MIN = G["rel_vol_min"]
    PREMARKET_LOOKBACK = G["rel_vol_lookback_sessions"]
    PREMARKET_BUCKET = G["rel_vol_bucket_minutes"]
    OPEN_REL_VOL_MIN = config["intraday"]["rel_vol_min"]
    PRICE_MIN = G["price_min"]
    ATR_PCT_MIN, ATR_PCT_MAX = G["atr_pct_min"], G["atr_pct_max"]
    TOP_N = G["top_n"]
    MIN_DAILY_BARS = G["min_daily_bars"]


_apply_gates()
PACE_S = 0.2             # seconds between MCP calls

ET = ZoneInfo("America/New_York")
RUN_DT_ET = datetime.now(ET)
RUN_TS = RUN_DT_ET.isoformat(timespec="seconds")
RUN_DATE_ET = RUN_DT_ET.date()
MODE = "premarket" if RUN_DT_ET.time() < wall_time(9, 30) else "opening_range"


def _in_mode_window(bar, mode):
    ts = bar["ts"]
    ts = ts.replace(tzinfo=ET) if ts.tzinfo is None else ts.astimezone(ET)
    if ts.date() != RUN_DATE_ET:
        return False
    minute = ts.hour * 60 + ts.minute
    if mode == "premarket":
        return 4 * 60 <= minute < 9 * 60 + 30
    return 9 * 60 + 30 <= minute < 16 * 60


def _time_bucket(now_et, bucket_minutes):
    minute = now_et.hour * 60 + now_et.minute
    return (minute // bucket_minutes) * bucket_minutes


def _load_premarket_history(path):
    try:
        with open(path) as f:
            data = json.load(f)
        samples = data.get("samples") if isinstance(data, dict) else None
        return {"version": 1, "samples": samples if isinstance(samples, dict) else {}}
    except FileNotFoundError:
        return {"version": 1, "samples": {}}
    except (OSError, ValueError) as e:
        print(f"warning: premarket volume history unavailable ({e}); "
              "using gap/ATR mode until a baseline is available", file=sys.stderr)
        return {"version": 1, "samples": {}}


def _premarket_baseline(history, symbol, bucket_minute):
    """Return (mean volume, sample count) from distinct prior days, same bucket."""
    by_date = {}
    for sample in history["samples"].get(symbol, []):
        if not isinstance(sample, dict) or sample.get("bucket_minute") != bucket_minute:
            continue
        date = sample.get("date")
        if not isinstance(date, str) or date >= RUN_DATE_ET.isoformat():
            continue
        try:
            volume = float(sample["volume"])
        except (KeyError, TypeError, ValueError):
            continue
        if volume >= 0:
            by_date[date] = volume
    recent = sorted(by_date.items())[-PREMARKET_LOOKBACK:]
    baseline = (statistics.fmean(volume for _, volume in recent)
                if recent else None)
    return baseline, len(recent)


def _save_premarket_history(path, history, rows):
    """Store one cumulative-volume observation per symbol/date/time bucket."""
    bucket = _time_bucket(RUN_DT_ET, PREMARKET_BUCKET)
    date = RUN_DATE_ET.isoformat()
    for row in rows:
        symbol = row.get("symbol")
        volume = row.get("premarket_volume")
        if not symbol or not isinstance(volume, (int, float)) or volume < 0:
            continue
        samples = history["samples"].get(symbol)
        if not isinstance(samples, list):
            samples = []
            history["samples"][symbol] = samples
        samples[:] = [s for s in samples if isinstance(s, dict)
                      and not (s.get("date") == date
                               and s.get("bucket_minute") == bucket)]
        samples.append({"date": date, "bucket_minute": bucket,
                        "volume": volume})
        samples.sort(key=lambda s: (s.get("date", ""),
                                    s.get("bucket_minute", -1)))
        # Bound state size while retaining enough observations per time bucket.
        history["samples"][symbol] = samples[-(PREMARKET_LOOKBACK * 24):]
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        temp_path = path + ".tmp"
        with open(temp_path, "w") as f:
            json.dump(history, f, separators=(",", ":"))
        os.replace(temp_path, path)
    except OSError as e:
        print(f"warning: could not save premarket volume history ({e})",
              file=sys.stderr)


def screen_one(symbol, quote_map=None, mode=None, premarket_baseline=None,
               premarket_baseline_samples=0):
    """Compute all pre-market signals. Returns (result_dict, [reasons]).

    quote_map: optional {symbol: price} from a batched get_quotes call.
    When provided, no per-symbol quote call is made (issue #14). When None,
    falls back to the single-symbol market_data.quote.

    result_dict has metrics when computable; reasons lists rejection
    categories (empty when the name qualifies). Never raises for data
    problems -- unknown metrics become rejection reasons, not crashes.
    """
    mode = mode or MODE
    reasons = []
    res = {"symbol": symbol, "mode": mode, "gap_pct": None, "rel_vol": None,
           "premarket_rel_vol": None, "regular_rel_vol": None,
           "premarket_baseline_volume": premarket_baseline,
           "expected_regular_volume": None,
           "vwap_dist_pct": None, "atr_pct": None, "range_atr": None,
           "gap_atr": None, "bias": None, "conviction": None, "price": None,
           "prior_close": None, "session": None,
           "premarket_volume": None, "regular_volume": None,
           "premarket_baseline_samples": premarket_baseline_samples,
           "volume_note": None}

    try:
        bars = daily_bars(symbol, ACCT)
    except McpError as e:
        return res, [f"daily bars failed: {e}"]
    # Drop an in-progress today: prior close = last COMPLETED daily bar.
    completed = [b for b in bars if b["date"] < RUN_DATE_ET] or bars
    if len(completed) < MIN_DAILY_BARS:
        return res, ["insufficient daily history"]
    prior_close = completed[-1]["close"]
    res["prior_close"] = prior_close
    vols = [b["volume"] for b in completed[-20:]]
    avg20_vol = statistics.fmean(vols) if all(v >= 0 for v in vols) else None

    atr = calc_atr([b["high"] for b in completed],
              [b["low"] for b in completed],
              [b["close"] for b in completed])
    if atr is None:
        return res, ["atr uncomputable"]

    try:
        if quote_map is not None:
            price = quote_map.get(symbol)
        else:
            price = quote_one(symbol, ACCT)
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
        ibars, _expected = intraday_bars(symbol, ACCT)
    except McpError as e:
        return res, [f"intraday bars failed: {e}"]
    if not ibars:
        return res, ["no intraday bars"]
    today_bars = [b for b in ibars
                  if _in_mode_window(b, "premarket")
                  or _in_mode_window(b, "opening_range")]
    res["session"] = RUN_DATE_ET.isoformat()
    premarket_bars = [b for b in today_bars if _in_mode_window(b, "premarket")]
    regular_bars = [
        b for b in today_bars
        if _in_mode_window(b, "opening_range")
        and (b["ts"].replace(tzinfo=ET) if b["ts"].tzinfo is None
             else b["ts"].astimezone(ET)) <= RUN_DT_ET - timedelta(minutes=5)
    ]
    pm_volume = sum(b["volume"] for b in premarket_bars)
    regular_volume = sum(b["volume"] for b in regular_bars)
    res["premarket_volume"] = pm_volume if premarket_bars else None
    res["regular_volume"] = regular_volume if regular_bars else None

    if mode == "premarket":
        session_bars = premarket_bars
        if not session_bars or pm_volume <= 0:
            rel_vol = None
            res["volume_note"] = (
                "premarket volume unavailable; volume gate disabled, "
                "using gap/ATR score"
            )
        elif premarket_baseline_samples >= PREMARKET_LOOKBACK:
            if premarket_baseline is None or premarket_baseline <= 0:
                rel_vol = None
                reasons.append("premarket volume baseline unknown")
                res["volume_note"] = "same-time premarket baseline has no positive volume"
            else:
                rel_vol = pm_volume / premarket_baseline
                res["premarket_rel_vol"] = rel_vol
                res["volume_note"] = (
                    f"same-time premarket RVOL {rel_vol:.2f}x "
                    f"({premarket_baseline_samples} prior sessions)"
                )
                if rel_vol < PREMARKET_REL_VOL_MIN:
                    reasons.append("premarket RVOL below same-time minimum")
        else:
            rel_vol = None
            baseline_note = (
                f"same-time premarket baseline building "
                f"({premarket_baseline_samples}/{PREMARKET_LOOKBACK} sessions)"
            )
            res["volume_note"] = (
                f"{baseline_note}; volume gate disabled, using gap/ATR score"
            )
    else:
        session_bars = regular_bars
        if not session_bars:
            reasons.append("no regular-session bars")
        elif regular_volume <= 0:
            reasons.append("no reported regular-session volume")
        market_open = RUN_DT_ET.replace(hour=9, minute=30, second=0, microsecond=0)
        elapsed_minutes = max(0.0, min(
            (RUN_DT_ET - market_open).total_seconds() / 60.0, 390.0))
        expected_vol = (avg20_vol * elapsed_minutes / 390.0
                        if avg20_vol and avg20_vol > 0 else None)
        res["expected_regular_volume"] = expected_vol
        regular_rel_vol = (regular_volume / expected_vol
                           if expected_vol and expected_vol > 0 else None)
        res["regular_rel_vol"] = regular_rel_vol
        rel_vol = regular_rel_vol
        if rel_vol is None and session_bars and regular_volume > 0:
            reasons.append("volume baseline unknown")
        elif rel_vol is not None and rel_vol < OPEN_REL_VOL_MIN:
            reasons.append("regular-session volume below time-normalized minimum")
        pm_rel_vol = (pm_volume / premarket_baseline
                      if (premarket_bars and pm_volume > 0
                          and premarket_baseline_samples >= PREMARKET_LOOKBACK
                          and premarket_baseline and premarket_baseline > 0)
                      else None)
        res["premarket_rel_vol"] = pm_rel_vol
        pm_note = (f"; premarket same-time RVOL {pm_rel_vol:.2f}x"
                   if pm_rel_vol is not None else
                   f"; premarket RVOL baseline {premarket_baseline_samples}/"
                   f"{PREMARKET_LOOKBACK}")
        res["volume_note"] = (
            (f"time-normalized regular-session RVOL {rel_vol:.2f}x"
             if rel_vol is not None else "time-normalized regular-session RVOL unavailable")
            + pm_note
        )

    res["rel_vol"] = rel_vol
    if mode == "opening_range":
        res["rel_vol_min"] = OPEN_REL_VOL_MIN

    # Keep premarket and regular-session VWAP separate; never blend the two.
    vwap = calc_vwap(session_bars)
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

    gap_atr = abs(gap_pct) / max(atr_pct, 0.01)
    res["gap_atr"] = gap_atr
    res["conviction"] = gap_atr * rel_vol if rel_vol is not None else gap_atr
    return res, reasons


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json-out", default=None)
    ap.add_argument("--names", default=None,
                    help="comma-separated override (default: Nasdaq-100)")
    ap.add_argument("--universe", default=None,
                    help="index universe from universes.py: sp500, sp100, nasdaq100, dow30 (--names wins)")
    ap.add_argument("--limit", type=int, default=None,
                    help="cap universe size (for tests)")
    ap.add_argument("--config", default=None,
                    help="path to gates.yaml (default: gates.yaml next to the script)")
    ap.add_argument("--volume-history", default="state/premarket_volume_history.json",
                    help="persistent snapshots for same-time premarket RVOL")
    ap.add_argument("--workers", type=int, default=8,
                    help="concurrent MCP workers (default 8; 1 = sequential)")
    args = ap.parse_args()
    if args.config:
        _apply_gates(args.config)
    volume_history = _load_premarket_history(args.volume_history)
    premarket_bucket = _time_bucket(RUN_DT_ET, PREMARKET_BUCKET)
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
        names = list(NASDAQ100)
        universe_tag = "nasdaq100"
    if args.limit:
        names = names[:args.limit]

    print(f"Pre-market gap / opening-range screen ({MODE}) -- run {RUN_TS} (America/New_York)")
    print(f"Universe: {universe_tag} ({len(names)} names)")
    if MODE == "premarket":
        volume_method = ("Premarket volume is shown as raw shares; same-time historical "
                         f"RVOL uses a {PREMARKET_BUCKET}-minute time bucket and "
                         f"{PREMARKET_LOOKBACK} prior sessions. Until available, the "
                         "volume gate is disabled. Conviction = |gap| / ATR% when "
                         "the baseline is unavailable.")
    else:
        volume_method = (f"Regular-session volume is normalized against 20-day average "
                         f"daily volume prorated by elapsed minutes / 390; gate >= "
                         f"{OPEN_REL_VOL_MIN}x. Conviction = (|gap| / ATR%) x RVOL.")
    print("Settings: "
          f"|gap| >= {GAP_MIN_PCT}%, price >= ${PRICE_MIN:g}, "
          f"ATR% {ATR_PCT_MIN}-{ATR_PCT_MAX}, top {TOP_N}. "
          f"Gap = quote vs prior regular-session close; {volume_method} "
          f"VWAP uses {'premarket' if MODE == 'premarket' else 'regular-session'} bars. "
          "LIMITATION: no news/catalyst feed via the MCP -- gaps are "
          "technical-only; check headlines before trading any candidate.")
    if MODE == "premarket":
        ready = sum(1 for symbol in names
                    if _premarket_baseline(volume_history, symbol,
                                           premarket_bucket)[1] >= PREMARKET_LOOKBACK)
        print(f"Premarket same-time RVOL baseline ready for {ready}/{len(names)} names; "
              f"other names use gap/ATR fallback.")

    cands, rej = [], {}
    rej_notes = {}
    near = []  # near-misses for the report (#26)
    screened = []

    # One batched quote call for the whole universe (issue #14) instead of
    # one call per name. On batch failure, screen_one falls back per-name.
    quote_map = None
    try:
        quote_map = quotes(names, ACCT)
        print(f"batched quotes: {len(quote_map)}/{len(names)} names priced",
              file=sys.stderr)
    except McpError as e:
        print(f"batched quotes failed ({e}); falling back to per-name quotes",
              file=sys.stderr)

    def safe_screen(sym):
        try:
            baseline, baseline_samples = _premarket_baseline(
                volume_history, sym, premarket_bucket)
            res, reasons = screen_one(sym, quote_map, MODE, baseline,
                                      baseline_samples)
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
            screened.append(evaluation_record({"symbol": sym}, error=err))
            continue
        screened.append(evaluation_record(res, reasons))
        if reasons:
            for r in reasons:
                key = r.split(":")[0]
                rej[key] = rej.get(key, 0) + 1
            rej_notes[sym] = reasons
            # Near-miss: rejected but close on the key gates — show what
            # almost qualified so an empty report explains itself (#26).
            gap = abs(res.get("gap_pct") or 0)
            if gap >= 0.5 * GAP_MIN_PCT:
                near.append({"symbol": sym,
                             "gap_pct": res.get("gap_pct"),
                             "rel_vol": res.get("rel_vol"),
                             "premarket_volume": res.get("premarket_volume"),
                             "premarket_baseline_volume": res.get("premarket_baseline_volume"),
                             "premarket_baseline_samples": res.get("premarket_baseline_samples"),
                             "premarket_rel_vol": res.get("premarket_rel_vol"),
                             "regular_volume": res.get("regular_volume"),
                             "expected_regular_volume": res.get("expected_regular_volume"),
                             "regular_rel_vol": res.get("regular_rel_vol"),
                             "gap_atr": res.get("gap_atr"),
                             "conviction": res.get("conviction"),
                             "volume_note": res.get("volume_note"),
                             "price": res.get("price"),
                             "atr_pct": res.get("atr_pct"),
                             "bias": res.get("bias"),
                             "missed": reasons})
        else:
            cands.append(res)
        if workers == 1 and i < len(names) - 1:
            time.sleep(PACE_S)

    cands.sort(key=lambda r: (r["conviction"] or 0), reverse=True)
    _save_premarket_history(args.volume_history, volume_history, screened)
    top = rank_qualified(screened, cands, TOP_N, score_key="conviction")

    print(f"\n=== TOP {TOP_N} BY CONVICTION ({len(cands)} candidates / {len(names)} screened) ===")
    print(f"{'sym':6} {'price':>8} {'gap%':>7} {'gapATR':>7} {'pmVol':>9} {'rthVol':>9} "
          f"{'RVOL':>7} {'vwapD%':>7} "
          f"{'atr%':>6} {'rngATR':>7} {'conv':>8}  bias")
    for r in top:
        vd = r["vwap_dist_pct"]
        vd_s = "   n/a" if vd is None else f"{vd:+.2f}"
        pm_vol_s = "n/a" if r["premarket_volume"] is None else f"{r['premarket_volume']:.0f}"
        rth_vol_s = "n/a" if r["regular_volume"] is None else f"{r['regular_volume']:.0f}"
        rv_s = "n/a" if r["rel_vol"] is None else f"{r['rel_vol']:.2f}x"
        print(f"{r['symbol']:6} {r['price']:8.2f} {r['gap_pct']:+7.2f} "
              f"{r['gap_atr']:7.2f} {pm_vol_s:>9} {rth_vol_s:>9} {rv_s:>7} {vd_s:>7} "
              f"{r['atr_pct']:6.2f} {r['range_atr']:+7.2f} {r['conviction']:8.1f}  "
              f"{r['bias']}")

    print("\nRejections (nothing silently dropped):")
    for k, v in sorted(rej.items(), key=lambda kv: -kv[1]):
        print(f"  {k} x{v}")

    # ---- plain-English readout ----
    print("\nREADOUT:")
    if not cands:
        print(f"- No names met the {MODE.replace('_', ' ')} gates.")
        if near:
            print("- Closest near-misses:")
            for n in near[:5]:
                gap_pct = n.get("gap_pct")
                rel_vol = n.get("rel_vol")
                gap_text = (f"{gap_pct:+.2f}%" if isinstance(gap_pct, (int, float))
                            else "n/a")
                volume_text = (f"{rel_vol:.2f}x RVOL"
                               if isinstance(rel_vol, (int, float)) else "RVOL n/a")
                pm_rel_vol = n.get("premarket_rel_vol")
                rth_rel_vol = n.get("regular_rel_vol")
                mode_volume_text = (
                    f"same-time premarket RVOL {pm_rel_vol:.2f}x"
                    if MODE == "premarket" and isinstance(pm_rel_vol, (int, float)
                    ) else
                    f"time-normalized RTH RVOL {rth_rel_vol:.2f}x"
                    if MODE == "opening_range" and isinstance(rth_rel_vol, (int, float)
                    ) else volume_text
                )
                print(f"  {n['symbol']}: gap {gap_text}, "
                      f"premarket {n.get('premarket_volume') or 0:.0f} shares, "
                      f"regular {n.get('regular_volume') or 0:.0f} shares, "
                      f"{n.get('volume_note') or mode_volume_text} — missed: "
                      f"{'; '.join(n['missed'])}")
    else:
        ups = [r for r in cands if r["gap_pct"] > 0]
        dns = [r for r in cands if r["gap_pct"] < 0]
        gng = [r for r in top if "gap-and-go" in (r["bias"] or "")]
        fade = [r for r in top if "fade risk" in (r["bias"] or "")]
        if gng:
            g = gng[0]
            rv_desc = (g.get("volume_note") or
                       (f"{g['rel_vol']:.2f}x RVOL" if g.get("rel_vol") is not None
                        else f"{g.get('premarket_volume') or 0:.0f} premarket shares; RVOL unavailable"))
            print(f"- Strongest gap-and-go: {g['symbol']} "
                  f"({g['gap_pct']:+.1f}% gap, {rv_desc}, "
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
        # Keep the closest near-misses using the same score as candidates.
        near_sorted = sorted(
            near,
            key=lambda n: n.get("conviction") or 0,
            reverse=True)[:5]
        with open(args.json_out, "w") as f:
            volume_method = ("premarket_same_time_bucket_baseline_with_gap_atr_fallback"
                             if MODE == "premarket" else
                             "regular_session_time_prorated_daily_average")
            json.dump({"run": RUN_TS, "mode": MODE, "universe": len(names),
                       "settings": {"gap_min_pct": GAP_MIN_PCT,
                                    "volume_method": volume_method,
                                    "rel_vol_min": (OPEN_REL_VOL_MIN
                                                    if MODE == "opening_range"
                                                    else PREMARKET_REL_VOL_MIN),
                                    "premarket_rel_vol_lookback_sessions": PREMARKET_LOOKBACK,
                                    "premarket_rel_vol_bucket_minutes": PREMARKET_BUCKET,
                                    "price_min": PRICE_MIN,
                                    "atr_pct_min": ATR_PCT_MIN,
                                    "atr_pct_max": ATR_PCT_MAX},
                       "candidates": top,
                       "screened": screened,
                       "qualification_counts": qualification_counts(screened),
                       "near_misses": near_sorted,
                       "rejections": rej}, f, indent=1)
        print(f"\nwrote {args.json_out}")


if __name__ == "__main__":
    main()
