"""
Tests for src/recommendation_analyzer.py.

Tests analysis logic with synthetic data (no network calls).
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import recommendation_analyzer as ra


class TestRsiReading(unittest.TestCase):
    def test_overbought(self):
        level, desc = ra.rsi_reading(75)
        self.assertEqual(level, "overbought")
        self.assertIn("75", desc)

    def test_oversold(self):
        level, desc = ra.rsi_reading(25)
        self.assertEqual(level, "oversold")

    def test_neutral(self):
        level, desc = ra.rsi_reading(50)
        self.assertEqual(level, "neutral")

    def test_none(self):
        level, desc = ra.rsi_reading(None)
        self.assertEqual(level, "unknown")


class TestPullbackRisk(unittest.TestCase):
    def test_high_risk_overbought(self):
        level, desc = ra.pullback_risk({"rsi14": 75, "off_high_pct": -1})
        self.assertEqual(level, "high")

    def test_low_risk_neutral(self):
        level, desc = ra.pullback_risk({"rsi14": 50, "off_high_pct": -15})
        self.assertEqual(level, "low")


class TestAnalyzePmcc(unittest.TestCase):
    def _pmcc_data(self):
        return {
            "pairs": {
                "AMZN": {
                    "long_strike": 215, "short_strike": 275,
                    "premium_to_debit_30d": 12.40,
                    "capital": 5905, "breach_vs_spot": 0.048,
                }
            },
            "evaluated_pairs": {
                "AMZN": [
                    {"qualification_status": "qualified"},
                    {"qualification_status": "rejected",
                     "qualification_reasons": ["P/D too low"]},
                ]
            },
        }

    def _stock_map(self):
        return {
            "AMZN": {
                "rsi14": 49.3, "trend": "UP",
                "sma50_dist_pct": -1.2, "sma200_dist_pct": 5.1,
                "atr_pct": 2.3, "off_high_pct": -11.3,
            }
        }

    def test_generates_analysis(self):
        result = ra.analyze_pmcc(self._pmcc_data(), self._stock_map())
        self.assertEqual(result["type"], "pmcc")
        self.assertEqual(len(result["recommendations"]), 1)

    def test_monthly_income_calculated(self):
        result = ra.analyze_pmcc(self._pmcc_data(), self._stock_map())
        rec = result["recommendations"][0]
        # 12.40% * $5905 = ~$732
        self.assertAlmostEqual(rec["monthly_income_est"], 732, delta=5)

    def test_technical_included(self):
        result = ra.analyze_pmcc(self._pmcc_data(), self._stock_map())
        rec = result["recommendations"][0]
        self.assertEqual(rec["technical"]["rsi_level"], "neutral")
        self.assertIn("Uptrend", rec["technical"]["trend"])

    def test_screening_transparency(self):
        result = ra.analyze_pmcc(self._pmcc_data(), self._stock_map())
        rec = result["recommendations"][0]
        self.assertEqual(rec["screening"]["combinations_evaluated"], 2)
        self.assertEqual(rec["screening"]["combinations_rejected"], 1)

    def test_summary_counts(self):
        result = ra.analyze_pmcc(self._pmcc_data(), self._stock_map())
        self.assertEqual(result["summary"]["qualifying_pairs"], 1)
        self.assertEqual(result["summary"]["total_combinations_evaluated"], 2)


class TestBuildStockMap(unittest.TestCase):
    def test_list_format(self):
        data = {"results": [{"symbol": "amzn", "rsi14": 50}]}
        m = ra.build_stock_map(data)
        self.assertIn("AMZN", m)

    def test_dict_format(self):
        data = {"by_symbol": {"GOOGL": {"rsi14": 55}}}
        m = ra.build_stock_map(data)
        self.assertIn("GOOGL", m)


if __name__ == "__main__":
    unittest.main()
