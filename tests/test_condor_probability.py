"""Regression test for issue #99: iron condor probability fields must be populated."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

os.environ.setdefault("PUBLIC_ACCOUNT_ID", "test")


class TestCondorProbability(unittest.TestCase):
    def test_accepted_condor_has_probability_fields(self):
        from spread_screener import evaluate_condor
        put_wing = {
            "expiration": "2026-11-20", "dte": 38,
            "short_strike": 90, "long_strike": 85,
            "credit_per_share": 1.00, "credit_total": 100,
            "leg_spread_sum": 0.02, "net_delta": -0.15, "short_delta": -0.15,
        }
        call_wing = {
            "expiration": "2026-11-20", "dte": 38,
            "short_strike": 110, "long_strike": 115,
            "credit_per_share": 0.80, "credit_total": 80,
            "leg_spread_sum": 0.02, "net_delta": 0.15, "short_delta": 0.15,
        }
        result = evaluate_condor(100, put_wing, call_wing, 5)
        self.assertTrue(result["accepted"])
        # These fields were missing due to dead code after return (#99)
        for field in ("win_prob_est", "expected_value", "loss_multiple", "lucrative"):
            self.assertIn(field, result, f"missing {field}")
            self.assertIsNotNone(result[field], f"{field} is None")
        # Sanity: 0.15-delta wings -> p_win ~0.72
        self.assertGreater(result["win_prob_est"], 0.5)
        self.assertLessEqual(result["win_prob_est"], 1.0)
        # expected_value must be numeric for decision engine step 5
        self.assertIsInstance(result["expected_value"], (int, float))

    def test_rejected_condor_unchanged(self):
        from spread_screener import evaluate_condor
        put_wing = {
            "expiration": "2026-11-20", "dte": 38,
            "short_strike": 90, "long_strike": 85,
            "credit_per_share": 1.00, "credit_total": 100,
            "leg_spread_sum": 0.02, "net_delta": -0.15, "short_delta": -0.15,
        }
        call_wing = {
            "expiration": "2026-12-18", "dte": 66,  # different expiry
            "short_strike": 110, "long_strike": 115,
            "credit_per_share": 0.80, "credit_total": 80,
            "leg_spread_sum": 0.02, "net_delta": 0.15, "short_delta": 0.15,
        }
        result = evaluate_condor(100, put_wing, call_wing, 5)
        self.assertFalse(result["accepted"])
        self.assertIn("wings on different expirations", result["reasons"])


if __name__ == "__main__":
    unittest.main()
