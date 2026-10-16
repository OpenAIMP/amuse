"""
Tests for src/tastytrade_backtest.py (#111).

Tests cover payload builders and result summarization (no network calls).
Network-dependent functions (auth, API calls) are not tested here —
they require Tastytrade credentials.
"""

import sys
import os
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import tastytrade_backtest as tt


class TestBuildBacktest(unittest.TestCase):
    def test_bull_put_payload_structure(self):
        payload = tt.build_backtest(
            symbol="SPY",
            strategy="bull_put",
            start_date="2022-01-01",
            end_date="2026-10-01",
        )
        self.assertEqual(payload["symbol"], "SPY")
        self.assertEqual(payload["startDate"], "2022-01-01")
        self.assertEqual(payload["endDate"], "2026-10-01")
        self.assertEqual(len(payload["legs"]), 2)
        # Short put leg
        self.assertEqual(payload["legs"][0]["direction"], "short")
        self.assertEqual(payload["legs"][0]["side"], "put")
        # Long put leg
        self.assertEqual(payload["legs"][1]["direction"], "long")
        self.assertEqual(payload["legs"][1]["side"], "put")

    def test_iron_condor_has_four_legs(self):
        payload = tt.build_backtest(
            symbol="QQQ", strategy="iron_condor",
            start_date="2022-01-01", end_date="2026-01-01",
        )
        self.assertEqual(len(payload["legs"]), 4)
        sides = sorted(l["side"] for l in payload["legs"])
        self.assertEqual(sides, ["call", "call", "put", "put"])

    def test_exit_conditions(self):
        payload = tt.build_backtest(
            symbol="SPY", strategy="bull_put",
            start_date="2022-01-01", end_date="2026-01-01",
            dte_target=45, profit_target=0.50, exit_dte=21,
        )
        exits = payload["exitConditions"]
        self.assertEqual(exits["profitTarget"], 0.50)
        self.assertEqual(exits["atDaysToExpiration"], 21)
        self.assertEqual(payload["entryConditions"]["daysToExpiration"], 45)

    def test_stop_loss_optional(self):
        payload = tt.build_backtest(
            symbol="SPY", strategy="bull_put",
            start_date="2022-01-01", end_date="2026-01-01",
            stop_loss=2.0,
        )
        self.assertEqual(payload["exitConditions"]["stopLoss"], 2.0)

        payload_no_sl = tt.build_backtest(
            symbol="SPY", strategy="bull_put",
            start_date="2022-01-01", end_date="2026-01-01",
        )
        self.assertNotIn("stopLoss", payload_no_sl["exitConditions"])

    def test_unknown_strategy_raises(self):
        with self.assertRaises(ValueError):
            tt.build_backtest(
                symbol="SPY", strategy="not_a_strategy",
                start_date="2022-01-01", end_date="2026-01-01",
            )


class TestSummarizeResults(unittest.TestCase):
    def _make_result(self, pnls):
        return {
            "statistics": {"profitFactor": 1.5, "maxDrawdown": -200},
            "trials": [{"pnl": p} for p in pnls],
        }

    def test_basic_summary(self):
        result = self._make_result([100, 150, -50, 200, -75])
        summary = tt.summarize_results(result)
        self.assertEqual(summary["trade_count"], 5)
        self.assertEqual(summary["win_count"], 3)
        self.assertEqual(summary["loss_count"], 2)
        self.assertAlmostEqual(summary["win_rate"], 0.6)
        self.assertEqual(summary["total_pnl"], 325)

    def test_avg_win_loss(self):
        result = self._make_result([100, 200, -50])
        summary = tt.summarize_results(result)
        self.assertAlmostEqual(summary["avg_win"], 150.0)
        self.assertAlmostEqual(summary["avg_loss"], -50.0)

    def test_empty_trials(self):
        summary = tt.summarize_results({"statistics": {}, "trials": []})
        self.assertEqual(summary["trade_count"], 0)
        self.assertEqual(summary["win_rate"], 0)
        self.assertEqual(summary["total_pnl"], 0)

    def test_server_stats_merged(self):
        result = self._make_result([100])
        summary = tt.summarize_results(result)
        self.assertEqual(summary["profitFactor"], 1.5)
        self.assertEqual(summary["maxDrawdown"], -200)


class TestStrategyLegs(unittest.TestCase):
    def test_all_strategies_have_legs(self):
        for name, legs in tt.STRATEGY_LEGS.items():
            self.assertTrue(len(legs) >= 2, f"{name} has no legs")
            for leg in legs:
                self.assertIn("type", leg)
                self.assertIn("side", leg)
                self.assertIn("direction", leg)


if __name__ == "__main__":
    unittest.main()
