"""Unit tests for indicators.py (issue #36).

Pure math consolidated from stock_screener.py, premarket_screen.py, and
intraday_screen.py. Values cross-checked against the originals' behavior.
"""
import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)),
                                  "..", "src"))

import unittest

from indicators import (sma, ema, macd, sma_cross, rsi, atr, atr_pct,
                        bollinger, vwap, anchored_vwap, find_pivots,
                        gap_pct)


def _bars(n=60, start=100.0):
    return [{"open": start + i * 0.1, "high": start + i * 0.1 + 1,
             "low": start + i * 0.1 - 1, "close": start + i * 0.1,
             "volume": 1_000_000} for i in range(n)]


class TestAverages(unittest.TestCase):
    def test_sma(self):
        self.assertAlmostEqual(sma([1, 2, 3, 4, 5], 3), 4.0)

    def test_ema_seed(self):
        # seeded with SMA of first n, single point -> equals SMA
        self.assertAlmostEqual(ema([1, 2, 3], 3), 2.0)

    def test_ema_none_when_short(self):
        self.assertIsNone(ema([1, 2], 3))

    def test_macd_insufficient(self):
        self.assertEqual(macd([1.0] * 10), (None, None, None))

    def test_macd_flat_series_zero_hist(self):
        line, sig, hist = macd([100.0] * 60)
        self.assertAlmostEqual(line, 0.0, places=9)
        self.assertAlmostEqual(hist, 0.0, places=9)

    def test_sma_cross_golden(self):
        # long downtrend then sharp V-recovery -> fast crosses above slow
        closes = [100 - i * 0.3 for i in range(60)] + \
                 [82 + i * 3.0 for i in range(12)]
        self.assertEqual(sma_cross(closes, 5, 20, 12), "golden")

    def test_sma_cross_none_when_flat(self):
        self.assertIsNone(sma_cross([100.0] * 60, 5, 20, 10))


class TestRsiAtr(unittest.TestCase):
    def test_rsi_all_gains(self):
        self.assertEqual(rsi([i * 1.0 for i in range(20)], 14), 100.0)

    def test_rsi_none_when_short(self):
        self.assertIsNone(rsi([1.0] * 10, 14))

    def test_atr_flat(self):
        n = 20
        highs = [101.0] * n
        lows = [99.0] * n
        closes = [100.0] * n
        self.assertAlmostEqual(atr(highs, lows, closes), 2.0, places=9)

    def test_atr_none_when_short(self):
        self.assertIsNone(atr([1.0] * 10, [1.0] * 10, [1.0] * 10))

    def test_atr_pct(self):
        n = 20
        self.assertAlmostEqual(
            atr_pct([101.0] * n, [99.0] * n, [100.0] * n, 100.0), 2.0,
            places=9)


class TestBollinger(unittest.TestCase):
    def test_bands_centered_on_flat(self):
        bb = bollinger([100.0] * 30, period=20, mult=2.0)
        self.assertAlmostEqual(bb["middle"], 100.0)
        self.assertAlmostEqual(bb["upper"], 100.0)
        self.assertIsNone(bb["squeeze"])  # not enough bars

    def test_insufficient_bars(self):
        bb = bollinger([100.0] * 10)
        self.assertIsNone(bb["middle"])


class TestVwap(unittest.TestCase):
    def test_vwap_math(self):
        bars = [
            {"high": 102, "low": 98, "close": 100, "volume": 1000},
            {"high": 104, "low": 100, "close": 102, "volume": 1000},
        ]
        # tp1 = 100, tp2 = 102 -> (100*1000 + 102*1000)/2000 = 101
        self.assertAlmostEqual(vwap(bars), 101.0, places=9)

    def test_vwap_none_when_no_volume(self):
        self.assertIsNone(vwap([]))

    def test_anchored_vwap(self):
        bars = _bars(260)
        vw, dist = anchored_vwap(bars)
        self.assertIsNotNone(vw)
        self.assertGreater(vw, 0)


class TestPivots(unittest.TestCase):
    def test_find_pivots(self):
        # single peak in the middle
        highs = [1, 2, 3, 5, 3, 2, 1]
        lows = [1, 1, 1, 1, 1, 1, 1]
        ph, pl = find_pivots(highs, lows, n=2)
        self.assertEqual([p for _, p in ph], [5])

    def test_gap_pct(self):
        self.assertAlmostEqual(gap_pct(100.0, 103.0), 3.0)
        self.assertIsNone(gap_pct(100.0, None))
        self.assertIsNone(gap_pct(0, 103.0))


if __name__ == "__main__":
    unittest.main()
