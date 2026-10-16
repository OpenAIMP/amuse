"""
Tests for src/compare.py (#114).

Tests the scoring logic and formatting with synthetic metrics
(no network calls). Live-data paths (extract_metrics via screen_stock)
are not tested here.
"""

import sys
import os
import unittest

# stock_screener requires PUBLIC_ACCOUNT_ID at import (#23).
# Set a dummy value — these tests never make network calls.
os.environ.setdefault("PUBLIC_ACCOUNT_ID", "test-dummy")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import compare


def _metrics(**overrides):
    base = {
        "symbol": "TEST",
        "price": 100.0,
        "ret_1d_pct": 1.0,
        "ret_30d_pct": 5.0,
        "ytd_ret_pct": 20.0,
        "score": 25.0,
        "verdict": "Go for it",
        "verdict_reason": "test",
        "trend": "UP",
        "bias": "bullish",
        "rsi14": 55.0,
        "dist_sma50_pct": 3.0,
        "off_high_pct": -2.0,
        "support": 95.0,
        "resistance": 105.0,
        "earnings_date": None,
    }
    base.update(overrides)
    return base


class TestScoreForView(unittest.TestCase):
    def test_bullish_uptrend_scores_high(self):
        m = _metrics(trend="UP", bias="bullish", score=28)
        s, reasons = compare._score_for_view(m, "bullish")
        self.assertGreater(s, 20)
        self.assertTrue(any("UP trend" in r for r in reasons))

    def test_bullish_downtrend_penalized(self):
        m = _metrics(trend="DN", bias="bearish", score=15)
        s_up, _ = compare._score_for_view(_metrics(trend="UP"), "bullish")
        s_dn, reasons = compare._score_for_view(m, "bullish")
        self.assertLess(s_dn, s_up)
        self.assertTrue(any("DN trend" in r for r in reasons))

    def test_bullish_overbought_penalized(self):
        m = _metrics(rsi14=75)
        s, reasons = compare._score_for_view(m, "bullish")
        self.assertTrue(any("overbought" in r for r in reasons))

    def test_bullish_pullback_bonus(self):
        m = _metrics(off_high_pct=-8.0)
        s, reasons = compare._score_for_view(m, "bullish")
        self.assertTrue(any("pullback" in r for r in reasons))

    def test_bearish_downtrend_scores_high(self):
        m = _metrics(trend="DN", bias="bearish", score=22)
        s, reasons = compare._score_for_view(m, "bearish")
        self.assertGreater(s, 15)
        self.assertTrue(any("DN trend" in r for r in reasons))

    def test_bearish_uptrend_penalized(self):
        m = _metrics(trend="UP")
        s, reasons = compare._score_for_view(m, "bearish")
        self.assertTrue(any("UP trend" in r for r in reasons))

    def test_bearish_oversold_penalized(self):
        m = _metrics(rsi14=25)
        s, reasons = compare._score_for_view(m, "bearish")
        self.assertTrue(any("oversold" in r for r in reasons))

    def test_neutral_range_scores_high(self):
        m = _metrics(trend="RNG", score=24)
        s, reasons = compare._score_for_view(m, "neutral")
        self.assertTrue(any("RNG trend" in r for r in reasons))

    def test_invalid_view_raises(self):
        with self.assertRaises(ValueError):
            compare.compare("A", "B", view="sideways")

    def test_earnings_flagged(self):
        m = _metrics(earnings_date="2026-10-28")
        _, reasons = compare._score_for_view(m, "bullish")
        self.assertTrue(any("earnings" in r for r in reasons))


class TestFormatTable(unittest.TestCase):
    def _result(self):
        return {
            "view": "bullish",
            "symbols": ["AAA", "BBB"],
            "errors": {},
            "a": _metrics(symbol="AAA", price=100.0),
            "b": _metrics(symbol="BBB", price=200.0),
            "a_score": 30.0,
            "a_reasons": ["UP trend (+10)"],
            "b_score": 25.0,
            "b_reasons": ["RNG trend (+3)"],
            "verdict": "AAA",
            "verdict_reason": "AAA scores 30.0 vs BBB 25.0",
        }

    def test_table_has_header(self):
        out = compare.format_table(self._result())
        self.assertIn("AAA vs BBB", out)
        self.assertIn("bullish view", out)

    def test_table_has_metrics(self):
        out = compare.format_table(self._result())
        self.assertIn("Price", out)
        self.assertIn("$100.00", out)
        self.assertIn("$200.00", out)

    def test_table_has_verdict(self):
        out = compare.format_table(self._result())
        self.assertIn("Verdict: AAA", out)

    def test_table_has_disclaimer(self):
        out = compare.format_table(self._result())
        self.assertIn("Not investment advice", out)

    def test_table_handles_missing_data(self):
        r = self._result()
        r["a"]["rsi14"] = None
        out = compare.format_table(r)
        self.assertIn("—", out)  # missing values render as em-dash

    def test_errors_shown(self):
        r = self._result()
        r["errors"] = {"BBB": "data error"}
        out = compare.format_table(r)
        self.assertIn("⚠️ BBB", out)


class TestViews(unittest.TestCase):
    def test_all_views_valid(self):
        self.assertEqual(set(compare.VIEWS), {"bullish", "bearish", "neutral"})


if __name__ == "__main__":
    unittest.main()
