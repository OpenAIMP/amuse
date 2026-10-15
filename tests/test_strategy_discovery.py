"""Tests for issue #106: strategy discovery across all families.

Covers:
- Bear call spreads as standalone structures (Phase 1)
- Iron butterflies (Phase 2)
- Regime router in decision engine (Phase 3)
- Per-symbol best-strategy ranking (Phase 4)
"""

import unittest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from spread_screener import evaluate_vertical, evaluate_butterfly
from decision_engine import build_decisions


class TestBearCallSpread(unittest.TestCase):
    def _make_legs(self, short_strike, long_strike, spot=100.0):
        short_c = {
            "sym": "TEST", "strike": short_strike, "expiration": "2026-11-20",
            "delta": -0.15, "bid": 1.50, "ask": 1.60, "spread": 0.10,
        }
        long_c = {
            "sym": "TEST", "strike": long_strike, "expiration": "2026-11-20",
            "delta": -0.05, "bid": 0.50, "ask": 0.60, "spread": 0.10,
        }
        return short_c, long_c

    def test_bear_call_accepted(self):
        # Bear call: short call above spot, long call further OTM
        s, l = self._make_legs(105.0, 110.0, spot=100.0)
        r = evaluate_vertical(100.0, s, l, 5.0, "bear_call")
        self.assertTrue(r["accepted"], f"reasons: {r.get('reasons')}")
        self.assertEqual(r["kind"], "bear_call")

    def test_bear_call_rejects_itm_short(self):
        # Short call below spot = not OTM, should reject
        s, l = self._make_legs(95.0, 100.0, spot=100.0)
        r = evaluate_vertical(100.0, s, l, 5.0, "bear_call")
        self.assertFalse(r["accepted"])
        self.assertIn("short call not OTM", r["reasons"])

    def test_bull_put_still_works(self):
        s, l = self._make_legs(95.0, 90.0, spot=100.0)
        # For bull_put, need put legs (delta positive in our test setup)
        s["delta"] = 0.15
        l["delta"] = 0.05
        r = evaluate_vertical(100.0, s, l, 5.0, "bull_put")
        self.assertTrue(r["accepted"], f"reasons: {r.get('reasons')}")


class TestIronButterfly(unittest.TestCase):
    def _make_wing(self, short_strike, long_strike, is_put=True):
        delta = 0.15 if is_put else -0.15
        return {
            "short_strike": short_strike, "long_strike": long_strike,
            "expiration": "2026-11-20", "dte": 36,
            "short_delta": delta,
            "credit_per_share": 1.0, "credit_total": 100.0,
            "leg_spread_sum": 0.20, "net_delta": 0.10,
        }

    def test_butterfly_accepted_when_strikes_match(self):
        pw = self._make_wing(100.0, 95.0, is_put=True)
        cw = self._make_wing(100.0, 105.0, is_put=False)
        r = evaluate_butterfly(100.0, pw, cw, 5.0)
        self.assertTrue(r["accepted"], f"reasons: {r.get('reasons')}")
        self.assertEqual(r["kind"], "iron_butterfly")

    def test_butterfly_rejected_when_strikes_differ(self):
        pw = self._make_wing(95.0, 90.0, is_put=True)
        cw = self._make_wing(105.0, 110.0, is_put=False)
        r = evaluate_butterfly(100.0, pw, cw, 5.0)
        self.assertFalse(r["accepted"])
        self.assertIn("short strikes do not match", r["reasons"][0])


class TestRegimeRouter(unittest.TestCase):
    def _make_stock(self, trend):
        return {
            "symbol": "TEST",
            "score": 25,
            "price": 100.0,
            "indicators": {
                "structure": {"trend": trend},
                "bollinger": {"squeeze": False},
            },
        }

    def _make_spread(self, ev=50.0):
        return {
            "expiration": "2026-11-20",
            "dte": 36,
            "credit_total": 100.0,
            "max_loss_total": 400.0,
            "return_on_risk": 0.25,
            "win_prob_est": 0.70,
            "expected_value": ev,
            "events": [],
            "vol": {"decision": "NO_READ"},
        }

    def test_up_trend_routes_to_bullish(self):
        stock_data = {"passing": [self._make_stock("UP")]}
        spread_data = {"results": {
            "bull_puts": {"TEST": self._make_spread()},
            "bear_calls": {"TEST": self._make_spread()},
        }}
        result = build_decisions(stock_data, spread_data)
        strategies = [c["strategy"] for c in result["candidates"]]
        # UP trend should route to bull_put_spread, not bear_call_spread
        self.assertIn("bull_put_spread", strategies)
        self.assertNotIn("bear_call_spread", strategies)

    def test_dn_trend_routes_to_bearish(self):
        stock_data = {"passing": [self._make_stock("DN")]}
        spread_data = {"results": {
            "bull_puts": {"TEST": self._make_spread()},
            "bear_calls": {"TEST": self._make_spread()},
        }}
        result = build_decisions(stock_data, spread_data)
        strategies = [c["strategy"] for c in result["candidates"]]
        self.assertIn("bear_call_spread", strategies)
        self.assertNotIn("bull_put_spread", strategies)

    def test_rng_trend_routes_to_neutral(self):
        stock_data = {"passing": [self._make_stock("RNG")]}
        spread_data = {"results": {
            "iron_condors": {"TEST": self._make_spread()},
            "iron_butterflies": {"TEST": self._make_spread()},
            "bull_puts": {"TEST": self._make_spread()},
        }}
        result = build_decisions(stock_data, spread_data)
        strategies = [c["strategy"] for c in result["candidates"]]
        self.assertIn("iron_condor", strategies)
        self.assertIn("iron_butterfly", strategies)
        self.assertNotIn("bull_put_spread", strategies)


class TestBestBySymbol(unittest.TestCase):
    def _make_stock(self, trend="UP"):
        return {
            "symbol": "TEST",
            "score": 25,
            "price": 100.0,
            "indicators": {
                "structure": {"trend": trend},
                "bollinger": {"squeeze": False},
            },
        }

    def _make_spread(self, ev):
        return {
            "expiration": "2026-11-20",
            "dte": 36,
            "credit_total": 100.0,
            "max_loss_total": 400.0,
            "return_on_risk": 0.25,
            "win_prob_est": 0.70,
            "expected_value": ev,
            "events": [],
            "vol": {"decision": "NO_READ"},
        }

    def test_best_by_symbol_picks_highest_ev(self):
        stock_data = {"passing": [self._make_stock("UP")]}
        spread_data = {"results": {
            "bull_puts": {"TEST": self._make_spread(ev=30.0)},
            "asym_condors": {"TEST": self._make_spread(ev=80.0)},
        }}
        result = build_decisions(stock_data, spread_data)
        best = result["best_by_symbol"].get("TEST")
        self.assertIsNotNone(best)
        # asym_condor has higher EV (80 > 30), should be picked
        self.assertEqual(best["strategy"], "asym_condor")
        self.assertEqual(best["expected_value"], 80.0)
        self.assertEqual(best["alternatives"], 1)


if __name__ == "__main__":
    unittest.main()
