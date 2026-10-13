#!/usr/bin/env python3
"""Shared indicator math (issue #36). All functions are pure — no I/O.

Consolidates the per-screener copies from stock_screener.py,
premarket_screen.py, and intraday_screen.py. Math is byte-identical to the
originals; only the calling convention changed: indicators take explicit
sequences (or bar dicts from market_data) instead of per-file tuple layouts.
"""
import math
import statistics


def sma(values, n):
    """Simple moving average of the last n values."""
    return sum(values[-n:]) / n


def ema(values, n):
    """Exponential moving average over the last n values (seeded with SMA)."""
    if len(values) < n:
        return None
    k = 2.0 / (n + 1.0)
    e = sum(values[:n]) / n
    for v in values[n:]:
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


def adx(bars, period=14):
    """Wilder ADX and +DI/-DI for OHLCV bar dicts; ADX is strength, not direction."""
    if len(bars) < 2 * period + 1:
        return None
    tr, plus_dm, minus_dm = [], [], []
    for prev, cur in zip(bars, bars[1:]):
        up = cur["high"] - prev["high"]
        down = prev["low"] - cur["low"]
        tr.append(max(cur["high"] - cur["low"],
                      abs(cur["high"] - prev["close"]),
                      abs(cur["low"] - prev["close"])))
        plus_dm.append(up if up > down and up > 0 else 0.0)
        minus_dm.append(down if down > up and down > 0 else 0.0)

    def smooth(values):
        current = sum(values[:period])
        result = [current]
        for value in values[period:]:
            current = current - current / period + value
            result.append(current)
        return result

    tr_s, plus_s, minus_s = smooth(tr), smooth(plus_dm), smooth(minus_dm)
    dx = []
    for t, p, m in zip(tr_s, plus_s, minus_s):
        pdi, mdi = (100 * p / t, 100 * m / t) if t else (0.0, 0.0)
        dx.append(100 * abs(pdi - mdi) / (pdi + mdi) if pdi + mdi else 0.0)
    if len(dx) < period:
        return None
    value = sum(dx[:period]) / period
    for item in dx[period:]:
        value = (value * (period - 1) + item) / period
    t, p, m = tr_s[-1], plus_s[-1], minus_s[-1]
    return {"adx": value, "plus_di": 100 * p / t if t else 0.0,
            "minus_di": 100 * m / t if t else 0.0}


def stochastic(bars, period=14, smooth=3):
    """Slow Stochastic %K/%D from daily OHLC bars."""
    if len(bars) < period + smooth - 1:
        return None
    ks = []
    for end in range(len(bars) - smooth + 1, len(bars) + 1):
        window = bars[end - period:end]
        low = min(b["low"] for b in window)
        high = max(b["high"] for b in window)
        close = bars[end - 1]["close"]
        ks.append(100 * (close - low) / (high - low) if high > low else 50.0)
    return {"k": ks[-1], "d": sum(ks[-smooth:]) / smooth}


def volume_confirmations(bars, period=14, lookback=20):
    """MFI(14) and 20-day OBV / Accumulation-Distribution directions."""
    if len(bars) < max(period + 1, lookback + 1):
        return None
    obv = [0.0]
    ad = []
    positive, negative = [], []
    for prev, cur in zip(bars, bars[1:]):
        close, high, low, volume = (cur["close"], cur["high"],
                                    cur["low"], cur["volume"])
        obv.append(obv[-1] + (volume if close > prev["close"]
                              else -volume if close < prev["close"] else 0.0))
        ad.append(((2 * close - high - low) / (high - low) * volume)
                  if high > low else 0.0)
        typical = (close + high + low) / 3.0
        prev_typical = (prev["close"] + prev["high"] + prev["low"]) / 3.0
        (positive if typical > prev_typical else negative).append(typical * volume)
    pos, neg = sum(positive[-period:]), sum(negative[-period:])
    mfi = 100.0 if neg == 0 and pos else 50.0 if neg == 0 else 100 - 100 / (1 + pos / neg)
    ad_line = []
    for flow in ad:
        ad_line.append(flow + (ad_line[-1] if ad_line else 0.0))

    def direction(series):
        old, new = series[-lookback - 1], series[-1]
        return "rising" if new > old else "falling" if new < old else "flat"

    return {"mfi": mfi, "obv_direction": direction(obv),
            "ad_direction": direction(ad_line)}


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


def atr(highs, lows, closes, period=14):
    """Wilder's ATR in price units. Returns None if insufficient data."""
    if len(closes) < period + 1:
        return None
    trs = []
    for i in range(1, len(closes)):
        h, l, pc = highs[i], lows[i], closes[i - 1]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    a = sum(trs[:period]) / period
    for tr in trs[period:]:
        a = (a * (period - 1) + tr) / period
    return a if math.isfinite(a) and a > 0 else None


def atr_pct(highs, lows, closes, price, period=14):
    """Wilder's ATR as % of price. Returns None if insufficient data."""
    a = atr(highs, lows, closes, period)
    if a is None or not price or price <= 0:
        return None
    return a / price * 100.0


def bollinger(closes, period=20, mult=2.0, squeeze_lookback=125,
              min_bars_squeeze=130):
    """Return dict with pct_b, bandwidth_pct, squeeze (or None fields).

    squeeze is True when current bandwidth is the squeeze_lookback-day
    minimum; it needs min_bars_squeeze bars, otherwise squeeze is None
    (unknown, never a gate).
    """
    out = {"pct_b": None, "bandwidth_pct": None, "squeeze": None,
           "upper": None, "middle": None, "lower": None}
    if len(closes) < period:
        return out
    window = closes[-period:]
    mid = statistics.fmean(window)
    sd = statistics.stdev(window)  # sample stdev
    upper, lower = mid + mult * sd, mid - mult * sd
    out.update({"upper": upper, "middle": mid, "lower": lower})
    width = upper - lower
    if width > 0 and math.isfinite(width):
        close = closes[-1]
        out["pct_b"] = (close - lower) / width
        out["bandwidth_pct"] = width / mid * 100.0 if mid > 0 else None
    if len(closes) >= min_bars_squeeze and out["bandwidth_pct"] is not None:
        bws = []
        m2 = 2.0 * mult  # keep in sync with bandwidth_pct above
        for i in range(len(closes) - squeeze_lookback, len(closes)):
            w = closes[i - period + 1:i + 1]
            m = statistics.fmean(w)
            s = statistics.stdev(w)
            bw = (m2 * s) / m * 100.0 if m > 0 else None
            bws.append(bw)
        if all(b is not None and math.isfinite(b) for b in bws):
            out["squeeze"] = (bws[-1] == min(bws))
    return out


def vwap(bars):
    """Cumulative VWAP over bar dicts (high/low/close/volume). None if no volume."""
    num = den = 0.0
    for b in bars:
        tp = (b["high"] + b["low"] + b["close"]) / 3.0
        num += tp * b["volume"]
        den += b["volume"]
    return num / den if den > 0 else None


def anchored_vwap(bars, lookback=252):
    """VWAP anchored at the lookback-window low bar.

    bars: list of dicts (high/low/close/volume). Returns (vwap, dist_pct)
    where dist_pct is the last close's distance from the anchored VWAP,
    or (None, None).
    """
    n = min(lookback, len(bars))
    if n < 2:
        return None, None
    window = bars[-n:]
    anchor = min(range(n), key=lambda i: window[i]["low"])
    num = den = 0.0
    for b in window[anchor:]:
        tp = (b["high"] + b["low"] + b["close"]) / 3.0
        num += tp * b["volume"]
        den += b["volume"]
    if den <= 0:
        return None, None
    vw = num / den
    close = bars[-1]["close"]
    if not (math.isfinite(vw) and vw > 0):
        return None, None
    return vw, (close / vw - 1) * 100.0


def find_pivots(highs, lows, n=5):
    """Fractal pivots: index i is a swing high if highs[i] strictly exceeds
    the n bars on each side (swing low analogously). Returns two lists of
    (index, price), oldest first."""
    ph, pl = [], []
    for i in range(n, len(highs) - n):
        h, l = highs[i], lows[i]
        if all(h > highs[j] for j in range(i - n, i + n + 1) if j != i):
            ph.append((i, h))
        if all(l < lows[j] for j in range(i - n, i + n + 1) if j != i):
            pl.append((i, l))
    return ph, pl


def gap_pct(prev_close, open_price):
    """Gap % vs prior close. None if inputs invalid."""
    if not prev_close or not open_price or prev_close <= 0:
        return None
    return (open_price - prev_close) / prev_close * 100.0
