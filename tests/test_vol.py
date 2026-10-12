"""Tests for vol.py: cheap-vs-expensive framework (issue #7)."""
import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)),
                                  "..", "src"))


import math
import os
import tempfile
import unittest

from vol import (realized_vol, iv_rank, iv_vs_hv, skew, term_structure,
                 assess, record_snapshot, load_history,
                 SELL_PREMIUM, STAND_DOWN, NO_READ)


class TestRealizedVol(unittest.TestCase):
    def test_flat_series_zero_vol(self):
        self.assertAlmostEqual(realized_vol([100.0] * 60, 20), 0.0)

    def test_known_vol(self):
        # Alternating +-1% daily moves: daily stdev ~0.01 -> annualized ~0.1587
        closes = [100.0]
        for i in range(60):
            closes.append(closes[-1] * (1.01 if i % 2 == 0 else 0.99))
        hv = realized_vol(closes, 20)
        self.assertAlmostEqual(hv, 0.01 * math.sqrt(252), delta=0.02)

    def test_insufficient_bars(self):
        self.assertIsNone(realized_vol([100.0] * 10, 20))

    def test_longer_window_smoother(self):
        closes = [100.0]
        for i in range(100):
            closes.append(closes[-1] * (1 + 0.005 * math.sin(i)))
        hv20 = realized_vol(closes, 20)
        hv60 = realized_vol(closes, 60)
        self.assertIsNotNone(hv20)
        self.assertIsNotNone(hv60)


class TestIVRank(unittest.TestCase):
    def test_rank(self):
        hist = [0.20, 0.25, 0.30, 0.35, 0.40]
        self.assertAlmostEqual(iv_rank(0.30, hist), 40.0)  # 2 of 5 below
        self.assertAlmostEqual(iv_rank(0.50, hist), 100.0)
        self.assertAlmostEqual(iv_rank(0.10, hist), 0.0)

    def test_empty_history(self):
        self.assertIsNone(iv_rank(0.30, []))


class TestComponents(unittest.TestCase):
    def test_iv_vs_hv(self):
        self.assertAlmostEqual(iv_vs_hv(0.30, 0.20), 1.5)
        self.assertIsNone(iv_vs_hv(0.30, 0.0))
        self.assertIsNone(iv_vs_hv(None, 0.20))

    def test_skew(self):
        self.assertAlmostEqual(skew(0.35, 0.25), 0.10)  # crash premium
        self.assertIsNone(skew(None, 0.25))

    def test_term_structure(self):
        self.assertAlmostEqual(term_structure(0.25, 0.30), 0.05)   # contango
        self.assertAlmostEqual(term_structure(0.40, 0.30), -0.10)  # backwardation


class TestAssess(unittest.TestCase):
    CFG = {"ivr_sell": 50, "ivr_stand_down": 25, "min_iv_history": 30}

    def _hist(self, n=40, lo=0.15, hi=0.35):
        return [lo + (hi - lo) * i / (n - 1) for i in range(n)]

    def test_sell_premium(self):
        hist = self._hist()          # median ~0.25
        r = assess(0.34, 0.20, hist, cfg=self.CFG)  # high rank, IV > HV
        self.assertEqual(r["decision"], SELL_PREMIUM)
        self.assertGreater(r["iv_rank"], 50)
        self.assertGreater(r["iv_vs_hv"], 1.0)

    def test_stand_down(self):
        hist = self._hist()
        r = assess(0.16, 0.30, hist, cfg=self.CFG)  # low rank
        self.assertEqual(r["decision"], STAND_DOWN)

    def test_no_read_mid(self):
        hist = self._hist()
        r = assess(0.25, 0.24, hist, cfg=self.CFG)  # rank ~50, ratio ~1
        self.assertEqual(r["decision"], NO_READ)

    def test_no_read_insufficient_history(self):
        r = assess(0.34, 0.20, [0.2, 0.3], cfg=self.CFG)
        self.assertEqual(r["decision"], NO_READ)
        self.assertIsNone(r["iv_rank"])

    def test_no_read_missing_hv(self):
        r = assess(0.34, None, self._hist(), cfg=self.CFG)
        self.assertEqual(r["decision"], NO_READ)


class TestSnapshots(unittest.TestCase):
    def test_record_and_load(self):
        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as f:
            path = f.name
        try:
            record_snapshot(path, "XOM", 0.25, day="2026-10-01")
            record_snapshot(path, "XOM", 0.28, day="2026-10-02")
            record_snapshot(path, "AAPL", 0.30, day="2026-10-02")
            hist = load_history(path, "XOM")
            self.assertEqual(hist, [0.25, 0.28])
            self.assertEqual(load_history(path, "AAPL"), [0.30])
            self.assertEqual(load_history(path, "NOPE"), [])
        finally:
            os.unlink(path)

    def test_missing_file(self):
        self.assertEqual(load_history("/tmp/not-here-xyz.jsonl", "XOM"), [])

    def test_max_points(self):
        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as f:
            path = f.name
        try:
            for i in range(10):
                record_snapshot(path, "XOM", 0.20 + i * 0.01)
            self.assertEqual(len(load_history(path, "XOM", max_points=5)), 5)
        finally:
            os.unlink(path)


if __name__ == "__main__":
    unittest.main(verbosity=2)
