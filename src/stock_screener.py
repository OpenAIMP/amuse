#!/usr/bin/env python3
"""
Generalized technical stock screener (watchlist-based).

Screens a watchlist of tickers on technical gates computed from one year of
daily bars, then ranks survivors by a simple composite score. This is a
ranking tool, not a market-wide discovery engine: it cannot find names you
did not give it (the MCP has no fundamentals endpoint and no market-wide
scan). Pair it with a universe filter (e.g. a thinkScript scan) upstream.

Gates are module constants and are printed in every report.
"""
import argparse
import concurrent.futures
import json
import os
import math
import statistics
import subprocess
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

CLI = os.environ.get("PUBLIC_MCP_CLI", "/home/hatch/workspace/skills/public-mcp/bin/public-mcp")
ACCT = os.environ.get("PUBLIC_ACCOUNT_ID") or ""
if not ACCT:
    raise SystemExit("PUBLIC_ACCOUNT_ID is not set; configure it as a repo variable/secret (#23)")

DEFAULT_NAMES = ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "AVGO",
                 "JPM", "V", "XOM", "JNJ", "PG", "HD", "BAC", "DIS"]

# ---- screening configuration (design choices, printed in every report) ----
# Tunables live in gates.yaml; this block binds them to module constants.
import gates as _gates_mod


def _apply_gates(path=None):
    global PRICE_MIN, PRICE_MAX, RSI_PERIOD, RSI_MIN, RSI_MAX
    global SMA_FAST, SMA_SLOW, REQUIRE_ABOVE_SMA_FAST, REQUIRE_ABOVE_SMA_SLOW
    global ATR_PCT_MIN, ATR_PCT_MAX, VOL_RATIO_MIN, MAX_OFF_HIGH_PCT, MIN_BARS
    global BB_PERIOD, BB_MULT, BB_PCTB_MIN, BB_PCTB_MAX
    global SQUEEZE_LOOKBACK, MIN_BARS_SQUEEZE, REQUIRE_ABOVE_ANCHORED_VWAP
    global REJECT_DOWNTREND, PIVOT_N, SWING_LOOKBACK_BARS
    global EMA_FAST, EMA_SLOW, MACD_FAST, MACD_SLOW, MACD_SIGNAL
    global CROSS_LOOKBACK, REJECT_DEATH_CROSS
    global GAP_LABEL_ABS_PCT, RSI_OVERSOLD, RSI_OVERBOUGHT
    global VALUE_UNDER_MAX_PCT, VALUE_OVER_MIN_PCT
    global BIAS_BULL_MIN, BIAS_BEAR_MAX
    G = _gates_mod.load(path)["stock"]
    PRICE_MIN, PRICE_MAX = G["price_min"], G["price_max"]
    RSI_PERIOD = G["rsi_period"]
    RSI_MIN, RSI_MAX = G["rsi_min"], G["rsi_max"]
    SMA_FAST, SMA_SLOW = G["sma_fast"], G["sma_slow"]
    REQUIRE_ABOVE_SMA_FAST = G["require_above_sma_fast"]
    REQUIRE_ABOVE_SMA_SLOW = G["require_above_sma_slow"]
    ATR_PCT_MIN, ATR_PCT_MAX = G["atr_pct_min"], G["atr_pct_max"]
    VOL_RATIO_MIN = G["vol_ratio_min"]
    MAX_OFF_HIGH_PCT = G["max_off_high_pct"]
    MIN_BARS = G["min_bars"]
    BB_PERIOD, BB_MULT = G["bb_period"], G["bb_mult"]
    BB_PCTB_MIN, BB_PCTB_MAX = G["bb_pctb_min"], G["bb_pctb_max"]
    SQUEEZE_LOOKBACK = G["squeeze_lookback"]
    MIN_BARS_SQUEEZE = G["min_bars_squeeze"]
    REQUIRE_ABOVE_ANCHORED_VWAP = G["require_above_anchored_vwap"]
    REJECT_DOWNTREND = G["reject_downtrend"]
    PIVOT_N = G["pivot_n"]
    SWING_LOOKBACK_BARS = G["swing_lookback_bars"]
    EMA_FAST, EMA_SLOW = G["ema_fast"], G["ema_slow"]
    MACD_FAST, MACD_SLOW, MACD_SIGNAL = G["macd_fast"], G["macd_slow"], G["macd_signal"]
    CROSS_LOOKBACK = G["cross_lookback"]
    REJECT_DEATH_CROSS = G["reject_death_cross"]
    GAP_LABEL_ABS_PCT = G["gap_label_abs_pct"]
    RSI_OVERSOLD, RSI_OVERBOUGHT = G["rsi_oversold"], G["rsi_overbought"]
    VALUE_UNDER_MAX_PCT = G["value_under_max_pct"]
    VALUE_OVER_MIN_PCT = G["value_over_min_pct"]
    BIAS_BULL_MIN, BIAS_BEAR_MAX = G["bias_bull_min"], G["bias_bear_max"]


_apply_gates()
PERIOD = "YEAR"
INTRADAY_PERIOD = "DAY"
INTRADAY_AGG = "FIFTEEN_MINUTES"
FIB_LEVELS = (0.382, 0.50, 0.618)

RUN_DATE = datetime.now(ZoneInfo("America/New_York")).date()
RUN_TS = datetime.now(ZoneInfo("America/New_York")).isoformat(timespec="seconds")


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


def bars_for(symbol):
    """Return list of (close, high, low, volume, open), validated finite/positive.
    open may be None when the feed omits it (gap is then unknown)."""
    p = mcp_call("get_price_history",
                 {"symbol": symbol, "account_id": ACCT,
                  "period": PERIOD, "aggregation": "ONE_DAY"})
    if not isinstance(p, dict):
        raise McpError(f"get_price_history: expected object payload for {symbol}")
    raw = p.get("regularMarket", {}).get("bars", [])
    bars = []
    for b in raw:
        try:
            c, h, l, v = (float(b["close"]), float(b["high"]),
                          float(b["low"]), float(b["volume"]))
            o = float(b["open"]) if b.get("open") is not None else None
        except (KeyError, TypeError, ValueError):
            continue
        if not all(math.isfinite(x) for x in (c, h, l, v)):
            continue
        if c <= 0 or h <= 0 or l <= 0 or v < 0:
            continue
        if o is not None and (not math.isfinite(o) or o <= 0):
            o = None
        bars.append((c, h, l, v, o))
    return bars


def sma(vals, n):
    return sum(vals[-n:]) / n


def ema(vals, n):
    """Exponential moving average over the last n values (seeded with SMA)."""
    if len(vals) < n:
        return None
    k = 2.0 / (n + 1.0)
    e = sum(vals[:n]) / n
    for v in vals[n:]:
        e = v * k + e * (1.0 - k)
    return e


def macd(closes, fast=12, slow=26, signal=9):
    """MACD line, signal line, histogram. Returns (None, None, None) if
    insufficient data. Standard 12/26/9, tunable via gates."""
    if len(closes) < slow + signal:
        return None, None, None
    k_fast, k_slow = 2.0 / (fast + 1.0), 2.0 / (slow + 1.0)
    ef = sum(closes[:fast]) / fast
    es = sum(closes[:slow]) / slow
    macd_line = None
    hist = []
    for v in closes[slow:]:
        ef = v * k_fast + ef * (1.0 - k_fast)
        es = v * k_slow + es * (1.0 - k_slow)
        macd_line = ef - es
        hist.append(macd_line)
    if len(hist) < signal:
        return macd_line, None, None
    k_sig = 2.0 / (signal + 1.0)
    sig = sum(hist[:signal]) / signal
    for m in hist[signal:]:
        sig = m * k_sig + sig * (1.0 - k_sig)
    return macd_line, sig, macd_line - sig


def sma_cross(closes, fast_n, slow_n, lookback):
    """Detect SMA fast/slow cross within the last `lookback` sessions.

    Returns "golden" (fast crossed above slow), "death" (fast crossed
    below slow), or None. Classic trend-regime event.
    """
    if len(closes) < slow_n + lookback:
        return None
    prev = None
    for i in range(len(closes) - lookback, len(closes)):
        w = closes[:i + 1]
        f, s = sma(w, fast_n), sma(w, slow_n)
        cur = "above" if f > s else ("below" if f < s else "even")
        if prev == "below" and cur == "above":
            return "golden"
        if prev == "above" and cur == "below":
            return "death"
        if cur != "even":
            prev = cur
    return None


def rsi(closes, period=14):
    """Wilder's RSI. Returns None if insufficient data."""
    if len(closes) < period + 1:
        return None
    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gains = [max(d, 0.0) for d in deltas]
    losses = [max(-d, 0.0) for d in deltas]
    ag = sum(gains[:period]) / period
    al = sum(losses[:period]) / period
    for g, l in zip(gains[period:], losses[period:]):
        ag = (ag * (period - 1) + g) / period
        al = (al * (period - 1) + l) / period
    if al == 0:
        return 100.0
    return 100.0 - 100.0 / (1.0 + ag / al)


def atr14_pct(bars, price):
    """Wilder's ATR(14) as % of price. Returns None if insufficient data."""
    if len(bars) < 15:
        return None
    trs = []
    for i in range(1, len(bars)):
        h, l, _c = bars[i][1], bars[i][2], bars[i][0]
        pc = bars[i - 1][0]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    atr = sum(trs[:14]) / 14
    for tr in trs[14:]:
        atr = (atr * 13 + tr) / 14
    return atr / price * 100.0


# ---------------- indicator pack: Bollinger / VWAP / pivots ----------------

def bollinger(closes):
    """Return dict with pct_b, bandwidth_pct, squeeze (or None fields).

    squeeze is True when current bandwidth is the 125-day minimum; it needs
    MIN_BARS_SQUEEZE bars, otherwise squeeze is None (unknown, never a gate).
    """
    out = {"pct_b": None, "bandwidth_pct": None, "squeeze": None,
           "upper": None, "middle": None, "lower": None}
    if len(closes) < BB_PERIOD:
        return out
    window = closes[-BB_PERIOD:]
    mid = statistics.fmean(window)
    sd = statistics.stdev(window)  # sample stdev
    upper, lower = mid + BB_MULT * sd, mid - BB_MULT * sd
    out.update({"upper": upper, "middle": mid, "lower": lower})
    width = upper - lower
    if width > 0 and math.isfinite(width):
        close = closes[-1]
        out["pct_b"] = (close - lower) / width
        out["bandwidth_pct"] = width / mid * 100.0 if mid > 0 else None
    if len(closes) >= MIN_BARS_SQUEEZE and out["bandwidth_pct"] is not None:
        bws = []
        mult = 2.0 * BB_MULT  # keep in sync with bandwidth_pct above (issue #16)
        for i in range(len(closes) - SQUEEZE_LOOKBACK, len(closes)):
            w = closes[i - BB_PERIOD + 1:i + 1]
            m = statistics.fmean(w)
            s = statistics.stdev(w)
            bw = (mult * s) / m * 100.0 if m > 0 else None
            bws.append(bw)
        if all(b is not None and math.isfinite(b) for b in bws):
            # bws[-1] is today's bandwidth on the same formula as the rest,
            # so == is exact here (issue #16: comparing against the separately
            # computed bandwidth_pct could miss by 1 ulp).
            out["squeeze"] = (bws[-1] == min(bws))
    return out


def intraday_bars_for(symbol):
    """Return (bars, expected_bars) for the DAY session, or raise McpError.

    bars: list of (date, open, high, low, close, volume), validated.
    """
    p = mcp_call("get_price_history",
                 {"symbol": symbol, "account_id": ACCT,
                  "period": INTRADAY_PERIOD, "aggregation": INTRADAY_AGG,
                  "trading_session_toggle": "REGULAR_HOURS"})
    if not isinstance(p, dict):
        raise McpError(f"get_price_history intraday: bad payload for {symbol}")
    rm = p.get("regularMarket", {})
    expected = rm.get("expectedBars")
    bars = []
    for b in rm.get("bars", []):
        try:
            ts = b["timestamp"]
            o, h, l, c = (float(b["open"]), float(b["high"]),
                          float(b["low"]), float(b["close"]))
            v = float(b["volume"])
        except (KeyError, TypeError, ValueError):
            continue
        if not all(math.isfinite(x) for x in (o, h, l, c, v)):
            continue
        if o <= 0 or h <= 0 or l <= 0 or c <= 0 or v < 0:
            continue
        try:
            day = datetime.fromisoformat(ts).date()
        except ValueError:
            continue
        bars.append((day, o, h, l, c, v))
    return bars, expected


def session_vwap(symbol):
    """Return dict with session VWAP info, or all-None on any problem.

    Uses the last COMPLETED regular session: if the newest bars belong to an
    in-progress today, they are dropped in favour of the prior session.
    Never raises for data problems (caller treats unknown as a flag).
    """
    out = {"vwap": None, "dist_pct": None, "session": None, "note": "unknown"}
    try:
        bars, expected = intraday_bars_for(symbol)
    except McpError:
        return out
    if not bars:
        return out
    by_day = {}
    for b in bars:
        by_day.setdefault(b[0], []).append(b)
    days = sorted(by_day)
    use = days[-1]
    today = datetime.now(ZoneInfo("America/New_York")).date()
    if use == today:
        exp = expected if isinstance(expected, (int, float)) and expected > 0 else 26
        if len(by_day[use]) < 0.9 * exp:
            if len(days) < 2:
                return out  # only an in-progress session exists
            use = days[-2]
            out["note"] = "prior session (today in progress)"
        else:
            out["note"] = "complete"
    else:
        out["note"] = "complete"
    num = den = 0.0
    for (_d, o, h, l, c, v) in by_day[use]:
        tp = (h + l + c) / 3.0
        num += tp * v
        den += v
    if den <= 0:
        return out
    vwap = num / den
    try:
        last_close = by_day[use][-1][4]
        dist = (last_close / vwap - 1) * 100.0
    except (IndexError, ZeroDivisionError):
        return out
    if not (math.isfinite(vwap) and math.isfinite(dist) and vwap > 0):
        return out
    out.update({"vwap": vwap, "dist_pct": dist, "session": use.isoformat()})
    return out


def anchored_vwap(bars):
    """VWAP anchored at the 52-week-low bar. Returns (vwap, dist_pct) or Nones."""
    n = min(252, len(bars))
    if n < 2:
        return None, None
    window = bars[-n:]
    anchor = min(range(n), key=lambda i: window[i][2])  # lowest low
    num = den = 0.0
    for (c, h, l, v, _o) in window[anchor:]:
        tp = (h + l + c) / 3.0
        num += tp * v
        den += v
    if den <= 0:
        return None, None
    vwap = num / den
    close = bars[-1][0]
    if not (math.isfinite(vwap) and vwap > 0):
        return None, None
    return vwap, (close / vwap - 1) * 100.0


def find_pivots(bars):
    """Fractal pivots: bar i is a swing high if high[i] strictly exceeds the
    PIVOT_N bars on each side (swing low analogously). Returns two lists of
    (index, price), oldest first."""
    highs, lows = [], []
    n = PIVOT_N
    for i in range(n, len(bars) - n):
        h, l = bars[i][1], bars[i][2]
        if all(h > bars[j][1] for j in range(i - n, i + n + 1) if j != i):
            highs.append((i, h))
        if all(l < bars[j][2] for j in range(i - n, i + n + 1) if j != i):
            lows.append((i, l))
    return highs, lows


# ---- issue #18: gap / momentum / value / bias readouts ----
# Labels, not gates: they describe the tape; they never reject a name.

def gap_pct(bars):
    """Overnight gap: (open_t / close_{t-1} - 1) * 100. None if open missing."""
    if len(bars) < 2:
        return None
    o, prev_c = bars[-1][4], bars[-2][0]
    if o is None or prev_c <= 0:
        return None
    return (o / prev_c - 1) * 100


def gap_label(g):
    if g is None:
        return None
    if g >= GAP_LABEL_ABS_PCT:
        return "gap up"
    if g <= -GAP_LABEL_ABS_PCT:
        return "gap down"
    return "no gap"


def rsi_state(rsi14):
    """Oversold < 30, overbought > 70, else neutral. State, not a signal."""
    if rsi14 is None:
        return None
    if rsi14 < RSI_OVERSOLD:
        return "oversold"
    if rsi14 > RSI_OVERBOUGHT:
        return "overbought"
    return "neutral"


def value_position(price, lo52, hi52):
    """Where price sits in its 52-week range, 0-100. Purely technical —
    the MCP has no fundamentals, so this is NOT intrinsic-value analysis."""
    if lo52 is None or hi52 is None or hi52 <= lo52 or price is None:
        return None
    return (price - lo52) / (hi52 - lo52) * 100


def value_label(vp):
    if vp is None:
        return None
    if vp <= VALUE_UNDER_MAX_PCT:
        return "undervalued"
    if vp >= VALUE_OVER_MIN_PCT:
        return "overvalued"
    return "mid-range"


def bias_votes(price, s50, s200, macd_hist, rsi14, trend):
    """Six trend votes; returns (bullish_votes, total)."""
    votes = [
        price is not None and s50 is not None and price > s50,
        price is not None and s200 is not None and price > s200,
        s50 is not None and s200 is not None and s50 > s200,
        macd_hist is not None and macd_hist > 0,
        rsi14 is not None and rsi14 > 50,
        trend == "UP",
    ]
    return sum(1 for v in votes if v), len(votes)


def bias_label(bull_votes):
    if bull_votes is None:
        return None
    if bull_votes >= BIAS_BULL_MIN:
        return "bullish"
    if bull_votes <= BIAS_BEAR_MAX:
        return "bearish"
    return "neutral"


def market_structure(bars):
    """Pivot/Fib structure. Returns dict; trend None when indeterminable."""
    out = {"trend": None, "ref_high": None, "ref_low": None,
           "fib_levels": {}, "nearest_fib": None, "nearest_fib_dist_pct": None}
    highs, lows = find_pivots(bars)
    # trend from the last 3 swing highs/lows
    if len(highs) >= 3 and len(lows) >= 3:
        h3 = [p for _, p in highs[-3:]]
        l3 = [p for _, p in lows[-3:]]
        hh = h3[0] < h3[1] < h3[2]
        hl = l3[0] < l3[1] < l3[2]
        lh = h3[0] > h3[1] > h3[2]
        ll = l3[0] > l3[1] > l3[2]
        if hh and hl:
            out["trend"] = "UP"
        elif lh and ll:
            out["trend"] = "DN"
        else:
            out["trend"] = "RNG"
    # reference swing: highest high / lowest low of the last ~6 months
    cut = len(bars) - SWING_LOOKBACK_BARS
    rh = [p for p in highs if p[0] >= cut]
    rl = [p for p in lows if p[0] >= cut]
    if not rh or not rl:
        return out
    hi_idx, hi_px = max(rh, key=lambda p: p[1])
    lo_idx, lo_px = min(rl, key=lambda p: p[1])
    if hi_px <= lo_px:
        return out
    out["ref_high"], out["ref_low"] = round(hi_px, 2), round(lo_px, 2)
    rng = hi_px - lo_px
    if hi_idx > lo_idx:  # upswing: retracements measured down from the high
        levels = {f: hi_px - f * rng for f in FIB_LEVELS}
    else:                # downswing: retracements measured up from the low
        levels = {f: lo_px + f * rng for f in FIB_LEVELS}
    out["fib_levels"] = {f"{f * 100:.1f}%": round(px, 2)
                         for f, px in levels.items()}
    close = bars[-1][0]
    name, px = min(levels.items(), key=lambda kv: abs(close - kv[1]))
    if px > 0 and math.isfinite(px):
        out["nearest_fib"] = f"{name * 100:.1f}%"
        out["nearest_fib_dist_pct"] = round((close / px - 1) * 100.0, 1)
    return out


def evaluate(sym, bars):
    """Return (accepted, metrics, reasons). Reasons use stable categories.

    Indicator-pack gates: %B inside bands, close above anchored VWAP,
    no downtrend pivot structure. Any indicator that cannot be computed is
    a flag in metrics['flags'], never a rejection.
    """
    reasons = []
    flags = []
    if len(bars) < MIN_BARS:
        return False, {}, ["insufficient history"]
    closes = [b[0] for b in bars]
    price = closes[-1]
    if not (PRICE_MIN <= price <= PRICE_MAX):
        reasons.append("price out of range")
    rsi14 = rsi(closes, RSI_PERIOD)
    if rsi14 is None or not (RSI_MIN <= rsi14 <= RSI_MAX):
        reasons.append("rsi out of range")
    s50, s200 = sma(closes, SMA_FAST), sma(closes, SMA_SLOW)
    vs50 = (price / s50 - 1) * 100
    vs200 = (price / s200 - 1) * 100
    if REQUIRE_ABOVE_SMA_FAST and price < s50:
        reasons.append("below 50-day SMA")
    if REQUIRE_ABOVE_SMA_SLOW and price < s200:
        reasons.append("below 200-day SMA")
    atrp = atr14_pct(bars, price)
    if atrp is None or not (ATR_PCT_MIN <= atrp <= ATR_PCT_MAX):
        reasons.append("ATR% out of range")
    vol20 = sum(b[3] for b in bars[-20:]) / 20
    vol60 = sum(b[3] for b in bars[-60:]) / 60
    vratio = vol20 / vol60 if vol60 > 0 else 0.0
    if vratio < VOL_RATIO_MIN:
        reasons.append("volume trend weak")
    hi52 = max(b[1] for b in bars)
    lo52 = min(b[2] for b in bars)
    off_hi = (price / hi52 - 1) * 100
    if off_hi < -MAX_OFF_HIGH_PCT:
        reasons.append("too far below 52w high")

    # ---- indicator pack ----
    bb = bollinger(closes)
    if bb["pct_b"] is None:
        flags.append("bollinger unknown")
    elif not (BB_PCTB_MIN <= bb["pct_b"] <= BB_PCTB_MAX):
        reasons.append("pctB outside bands")

    avwap, avwap_dist = anchored_vwap(bars)
    if avwap is None:
        flags.append("anchored vwap unknown")
    elif REQUIRE_ABOVE_ANCHORED_VWAP and avwap_dist < 0:
        reasons.append("below anchored VWAP")

    sess = session_vwap(sym)
    if sess["vwap"] is None:
        flags.append("session vwap unknown")

    struct = market_structure(bars)
    if struct["trend"] is None:
        flags.append("trend structure unknown")
    elif REJECT_DOWNTREND and struct["trend"] == "DN":
        reasons.append("downtrend structure")

    # ---- trend pack: EMA, golden/death cross, MACD ----
    ema_fast_v = ema(closes, EMA_FAST)
    ema_slow_v = ema(closes, EMA_SLOW)
    cross = sma_cross(closes, SMA_FAST, SMA_SLOW, CROSS_LOOKBACK)
    if cross == "death" and REJECT_DEATH_CROSS:
        reasons.append("death cross (SMA50<SMA200)")
    elif cross is None:
        flags.append("cross unknown")
    macd_line, macd_sig, macd_hist = macd(closes, MACD_FAST, MACD_SLOW,
                                          MACD_SIGNAL)
    if macd_hist is None:
        flags.append("macd unknown")

    def ret(n):
        return (price / closes[-n - 1] - 1) * 100 if len(closes) > n else 0.0

    r2 = lambda x: round(x, 2) if x is not None else None
    r1 = lambda x: round(x, 1) if x is not None else None
    indicators = {
        "bollinger": {
            "pct_b": r2(bb["pct_b"]),
            "bandwidth_pct": r1(bb["bandwidth_pct"]),
            "squeeze": bb["squeeze"],
        },
        "vwap": {
            "session_vwap": r2(sess["vwap"]),
            "session_dist_pct": r1(sess["dist_pct"]),
            "session": sess["session"],
            "anchored_vwap": r2(avwap),
            "anchored_dist_pct": r1(avwap_dist),
        },
        "structure": struct,
        "trend": {
            "ema50": r2(ema_fast_v),
            "ema200": r2(ema_slow_v),
            "cross": cross,  # "golden" | "death" | None
        },
        "macd": {
            "line": r2(macd_line),
            "signal": r2(macd_sig),
            "hist": r2(macd_hist),
        },
    }
    # ---- issue #18 readouts ----
    g = gap_pct(bars)
    vp = value_position(price, lo52, hi52)
    bull_votes, _nvotes = bias_votes(price, s50, s200, macd_hist, rsi14,
                                     struct["trend"])
    indicators["tape"] = {
        "gap_pct": r1(g),
        "gap": gap_label(g),
        "momentum": rsi_state(rsi14),
        "value_pct": r1(vp),
        "value": value_label(vp),
        "bias_votes": bull_votes,
        "bias": bias_label(bull_votes),
    }
    metrics = {
        "price": round(price, 2), "rsi14": round(rsi14, 1),
        "vs_sma50_pct": round(vs50, 1), "vs_sma200_pct": round(vs200, 1),
        "atr_pct": round(atrp, 2), "vol_ratio": round(vratio, 2),
        "off_52w_high_pct": round(off_hi, 1),
        "ret_1m_pct": round(ret(21), 1), "ret_3m_pct": round(ret(63), 1),
        "indicators": indicators,
        "flags": flags,
    }
    return (not reasons), metrics, reasons


def composite(m):
    """0-30 score: ideal 0-5% above 50-day (10) + RSI 50-65 sweet spot (10)
    + volume expansion (10). Simple and explainable by design."""
    s50 = max(0.0, 10.0 - abs(m["vs_sma50_pct"] - 2.5))
    rsi = m["rsi14"]
    if 50 <= rsi <= 65:
        s_rsi = 10.0
    elif rsi < 50:
        s_rsi = max(0.0, 10.0 - (50 - rsi) * 0.5)
    else:
        s_rsi = max(0.0, 10.0 - (rsi - 65) * 0.5)
    s_vol = min(10.0, max(0.0, m["vol_ratio"] * 6.67))
    return round(s50 + s_rsi + s_vol, 1)


def signal_score(m):
    """0-10 indicator-pack score: %B in [0.5,0.9] +2,
    anchored-VWAP distance 0-3% above +2 (else +1 if known), uptrend +3,
    golden cross +2, MACD histogram positive +1.

    A squeeze scores 0 by design (issue #16): the documented stance is
    "wait or size down" — a volatility coil means premium is cheap, the
    worst time for a premium seller to get paid. It stays ranking-only
    (never a gate), contributing nothing rather than a reward.
    """
    s = 0.0
    detail = {}
    ind = m.get("indicators", {})
    bb = ind.get("bollinger", {})
    if bb.get("squeeze"):
        detail["squeeze"] = 0.0
    pb = bb.get("pct_b")
    if pb is not None and 0.5 <= pb <= 0.9:
        s += 2.0
        detail["pct_b_sweet_spot"] = 2.0
    av = ind.get("vwap", {}).get("anchored_dist_pct")
    if av is not None and av >= 0:
        pts = 2.0 if av <= 3.0 else 1.0
        s += pts
        detail["anchored_vwap"] = pts
    if ind.get("structure", {}).get("trend") == "UP":
        s += 3.0
        detail["uptrend"] = 3.0
    if ind.get("trend", {}).get("cross") == "golden":
        s += 2.0
        detail["golden_cross"] = 2.0
    mh = ind.get("macd", {}).get("hist")
    if mh is not None and mh > 0:
        s += 1.0
        detail["macd_bullish"] = 1.0
    return round(s, 1), detail


def narrate_stock(passing, rejected, names):
    """Plain-English readout. Every claim comes from computed values.

    Returns a list of lines; empty theme groups are skipped.
    """
    lines = []

    def trend_of(ind):
        try:
            return (ind or {}).get("structure", {}).get("trend")
        except AttributeError:
            return None

    census = {"UP": 0, "RNG": 0, "DN": 0}
    for m in passing:
        t = trend_of(m.get("indicators"))
        if t in census:
            census[t] += 1
    for r in rejected.values():
        t = trend_of((r or {}).get("indicators"))
        if t in census:
            census[t] += 1

    if not passing:
        lines.append("No names passed all gates — the screen found no "
                     "tradeable setups today.")
    else:
        lead = passing[0]
        det = (lead.get("score_breakdown", {}) or {}).get("detail", {}) or {}
        up_leaders = [m["symbol"] for m in passing
                      if trend_of(m.get("indicators")) == "UP"]
        only_up = len(up_leaders) == 1 and up_leaders[0] == lead["symbol"]
        # decisive reason: biggest signal contributor, regime first on ties
        prio = ["uptrend", "squeeze", "pct_b_sweet_spot", "anchored_vwap"]
        best = None
        for k in prio:
            if det.get(k, 0) > 0 and (best is None
                                     or det[k] > det.get(best, 0)):
                best = k
        if best == "uptrend" and only_up:
            reason = ("the only name with UP trend structure — regime filter "
                      "doing its job")
        elif best == "uptrend":
            reason = "uptrend structure with the strongest signal stack"
        elif best == "squeeze":
            reason = "coiling into a volatility squeeze"
        elif best == "pct_b_sweet_spot":
            reason = "%B in the sweet spot — extended neither hot nor cold"
        elif best == "anchored_vwap":
            reason = "holding above anchored VWAP with momentum intact"
        else:
            reason = "the strongest base technicals on the watchlist"
        lines.append(f"{lead['symbol']} {lead['score']:.1f} leads — {reason}.")

    # ---- rejection themes ----
    OLD = {"price out of range", "rsi out of range", "below 50-day SMA",
           "below 200-day SMA", "ATR% out of range", "volume trend weak",
           "too far below 52w high", "insufficient history"}
    NEW = {"pctB outside bands", "below anchored VWAP", "downtrend structure"}
    extended, underwater, stayaway, oldonly, other_new, dataerr = \
        [], [], [], [], [], []
    for sym in names:
        r = rejected.get(sym)
        if not r:
            continue
        reasons = r.get("reasons", []) or []
        ind = r.get("indicators") or {}
        pb = (ind.get("bollinger") or {}).get("pct_b")
        new_hits = [x for x in reasons if x in NEW]
        if any(x.startswith(("data error", "evaluation error",
                             "unexpected error")) for x in reasons):
            dataerr.append(sym)
        elif len(reasons) >= 3 and new_hits:
            stayaway.append(sym)
        elif "below anchored VWAP" in reasons:
            underwater.append(sym)
        elif ("pctB outside bands" in reasons
              and pb is not None and pb > 1.0):
            extended.append(sym)
        elif all(x in OLD for x in reasons):
            oldonly.append(sym)
        else:
            other_new.append((sym, reasons))

    if extended:
        verb = "rides" if len(extended) == 1 else "ride"
        lines.append(f"{', '.join(extended)} passed the classic gates but "
                     f"{verb} above the upper band (%B > 1.0) — extended, "
                     f"don't chase.")
    if underwater:
        pron = "it" if len(underwater) == 1 else "them"
        lines.append(f"{', '.join(underwater)} failed the anchored-VWAP gate "
                     f"— institutional money is underwater on {pron}.")
    if stayaway:
        verb = "trips" if len(stayaway) == 1 else "trip"
        lines.append(f"{', '.join(stayaway)} {verb} multiple gates at once — "
                     f"the screen is saying stay away, loudly.")
    if other_new:
        bits = "; ".join(f"{s} ({', '.join(rs)})" for s, rs in other_new)
        lines.append(f"Other new-gate rejections: {bits}.")
    if oldonly:
        lines.append(f"Rejected on classic gates alone: "
                     f"{', '.join(oldonly)}.")
    if dataerr:
        lines.append(f"Data issues, not screened: {', '.join(dataerr)}.")

    lines.append(f"Regime census: {census['UP']} UP / {census['RNG']} RNG / "
                 f"{census['DN']} DN across the watchlist.")
    if passing:
        n_up = sum(1 for m in passing
                   if trend_of(m.get("indicators")) == "UP")
        if n_up == 0:
            lines.append("No uptrend names qualified — premium selling has no "
                         "regime tailwind today.")
        else:
            lines.append(f"{n_up} uptrend "
                         f"{'name' if n_up == 1 else 'names'} qualified — "
                         f"regime favors bullish premium structures today.")
    return lines


def screen_stock(sym):
    """Fetch + evaluate one name. Returns (sym, ok, metrics, reasons).

    metrics is None when bars could not be fetched/evaluated at all.
    Pure per-symbol work; safe to run in a thread pool (issue #14).
    """
    try:
        bars = bars_for(sym)
    except McpError as e:
        return (sym, False, None, [f"data error: {e}"])
    except Exception as e:  # never let one ticker kill the run
        return (sym, False, None, [f"unexpected error: {type(e).__name__}"])
    try:
        ok, metrics, reasons = evaluate(sym, bars)
    except Exception as e:
        return (sym, False, None, [f"evaluation error: {type(e).__name__}"])
    if ok:
        base = composite(metrics)
        sig, detail = signal_score(metrics)
        metrics["score"] = round(base + sig, 1)
        metrics["score_breakdown"] = {"base": base, "signals": sig,
                                      "detail": detail}
        metrics["symbol"] = sym
    return (sym, ok, metrics, reasons)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--names", default=None,
                    help="comma-separated watchlist, e.g. AAPL,MSFT,NVDA")
    ap.add_argument("--universe", default=None,
                    help="index universe from universes.py: sp500, sp100, nasdaq100, dow30 (--names wins if both given)")
    ap.add_argument("--json-out", default=None,
                    help="write machine-readable ranked results to FILE")
    ap.add_argument("--config", default=None,
                    help="path to gates.yaml (default: gates.yaml next to the script)")
    ap.add_argument("--workers", type=int, default=8,
                    help="concurrent MCP workers (default 8; 1 = sequential)")
    args = ap.parse_args()
    if args.config:
        _apply_gates(args.config)
    if args.names:
        names = [n.strip().upper() for n in args.names.split(",") if n.strip()]
        universe_tag = "custom"
    elif args.universe:
        from universes import UNIVERSES
        key = args.universe.strip().lower()
        if key not in UNIVERSES:
            raise SystemExit(f"unknown universe {key!r}; choose from {sorted(UNIVERSES)}")
        names = list(UNIVERSES[key])
        universe_tag = key
    else:
        names = DEFAULT_NAMES
        universe_tag = "default"

    print(f"Technical stock screen -- run {RUN_TS} (America/New_York) [{universe_tag}, {len(names)} names]")
    print(f"Settings: price ${PRICE_MIN:.0f}-${PRICE_MAX:.0f}, "
          f"RSI14 {RSI_MIN:.0f}-{RSI_MAX:.0f}, "
          f"above SMA{SMA_FAST}={'yes' if REQUIRE_ABOVE_SMA_FAST else 'no'}, "
          f"above SMA{SMA_SLOW}={'yes' if REQUIRE_ABOVE_SMA_SLOW else 'no'}, "
          f"ATR% {ATR_PCT_MIN:.1f}-{ATR_PCT_MAX:.1f}, "
          f"vol20/60 >= {VOL_RATIO_MIN}, "
          f"within {MAX_OFF_HIGH_PCT:.0f}% of 52w high, "
          f"daily bars ({PERIOD}).")
    print(f"Indicator pack: BB {BB_PERIOD}x{BB_MULT} %B in "
          f"[{BB_PCTB_MIN:.1f},{BB_PCTB_MAX:.1f}], squeeze = {SQUEEZE_LOOKBACK}d "
          f"bandwidth min (ranking only); anchored-VWAP gate="
          f"{'yes' if REQUIRE_ABOVE_ANCHORED_VWAP else 'no'}; "
          f"downtrend reject={'yes' if REJECT_DOWNTREND else 'no'}; "
          f"score 0-40 = base 0-30 + signals 0-10.")

    # Thread pool over names (issue #14): screen_stock is pure per-symbol
    # work. Merge in submission order in the main thread -- no locks,
    # deterministic output regardless of worker count.
    passing, rejected = [], {}
    with concurrent.futures.ThreadPoolExecutor(
            max_workers=max(1, args.workers)) as ex:
        results = list(ex.map(screen_stock, names))
    for sym, ok, metrics, reasons in results:
        if metrics is None:
            rejected[sym] = {"reasons": reasons, "indicators": None}
        elif ok:
            passing.append(metrics)
        else:
            rejected[sym] = {"reasons": reasons,
                             "indicators": metrics.get("indicators")}

    passing.sort(key=lambda m: -m["score"])

    def fmt_ind(m):
        ind = m["indicators"]
        bb, vw, st = ind["bollinger"], ind["vwap"], ind["structure"]
        pctb = f"{bb['pct_b']:.2f}" if bb["pct_b"] is not None else " n/a"
        bw = f"{bb['bandwidth_pct']:.1f}" if bb["bandwidth_pct"] is not None else " n/a"
        sqz = "*" if bb["squeeze"] else " "
        av = f"{vw['anchored_dist_pct']:+.1f}" if vw["anchored_dist_pct"] is not None else "  n/a"
        tr = {"UP": "UP", "DN": "DN", "RNG": "RNG"}.get(st["trend"], " ?")
        return pctb, bw, sqz, av, tr

    print(f"\n{'sym':<6}{'price':>9}{'RSI14':>7}{'vs50d%':>8}{'vs200d%':>9}"
          f"{'ATR%':>7}{'vol':>6}{'offHi%':>8}{'1m%':>7}{'3m%':>7}"
          f"{'%B':>6}{'BWk%':>6}{'SQZ':>4}{'aVWP%':>7}{'TRND':>5}{'score':>16}")
    for m in passing:
        pctb, bw, sqz, av, tr = fmt_ind(m)
        bd = m["score_breakdown"]
        print(f"{m['symbol']:<6}{m['price']:>9.2f}{m['rsi14']:>7.1f}"
              f"{m['vs_sma50_pct']:>8.1f}{m['vs_sma200_pct']:>9.1f}"
              f"{m['atr_pct']:>7.2f}{m['vol_ratio']:>6.2f}"
              f"{m['off_52w_high_pct']:>8.1f}{m['ret_1m_pct']:>7.1f}"
              f"{m['ret_3m_pct']:>7.1f}{pctb:>6}{bw:>6}{sqz:>4}{av:>7}{tr:>5}"
              f"{m['score']:>7.1f} ({bd['base']:.1f}+{bd['signals']:.1f})")
    if not passing:
        print("(no names passed all gates)")
    print("\nRejections:")
    if rejected:
        for sym in names:
            if sym in rejected:
                r = rejected[sym]
                fl = ""
                ind = r.get("indicators")
                if ind:
                    flgs = []
                    bb, vw, st = ind["bollinger"], ind["vwap"], ind["structure"]
                    if bb["squeeze"]:
                        flgs.append("squeezing")
                    if vw["anchored_dist_pct"] is not None:
                        flgs.append(f"aVWP {vw['anchored_dist_pct']:+.1f}%")
                    if st["trend"]:
                        flgs.append(f"trend {st['trend']}")
                    if flgs:
                        fl = " [" + ", ".join(flgs) + "]"
                print(f"  {sym}: {'; '.join(r['reasons'])}{fl}")
    else:
        print("  none -- every name passed")

    print("\n=== READOUT ===")
    readout = []
    try:
        readout = narrate_stock(passing, rejected, names)
        for line in readout:
            print(line)
    except Exception:
        print("readout unavailable")

    if args.json_out:
        with open(args.json_out, "w") as f:
            json.dump({"asof": RUN_DATE.isoformat(),
                       "settings": {
                           "price_range": [PRICE_MIN, PRICE_MAX],
                           "rsi_range": [RSI_MIN, RSI_MAX],
                           "rsi_period": RSI_PERIOD,
                           "require_above_sma_fast": REQUIRE_ABOVE_SMA_FAST,
                           "require_above_sma_slow": REQUIRE_ABOVE_SMA_SLOW,
                           "sma_fast": SMA_FAST,
                           "sma_slow": SMA_SLOW,
                           "atr_pct_range": [ATR_PCT_MIN, ATR_PCT_MAX],
                           "vol_ratio_min": VOL_RATIO_MIN,
                           "max_off_high_pct": MAX_OFF_HIGH_PCT,
                           "period": PERIOD,
                           "bollinger": {"period": BB_PERIOD, "mult": BB_MULT,
                                          "pct_b_range": [BB_PCTB_MIN, BB_PCTB_MAX],
                                          "squeeze_lookback": SQUEEZE_LOOKBACK},
                           "require_above_anchored_vwap": REQUIRE_ABOVE_ANCHORED_VWAP,
                           "reject_downtrend": REJECT_DOWNTREND,
                           "score": "0-40 = base 0-30 + signals 0-10",
                           "universe": universe_tag},
                       "passing": passing,
                       "rejected": rejected,
                       "readout": readout}, f, indent=1)
        print(f"\nwrote {args.json_out}", file=sys.stderr)


if __name__ == "__main__":
    main()
