"""Payoff unit tests for the asymmetric iron condor (spread_screener.py).

Verifies the structure's expiration P&L at every strike boundary and at
extreme underlying prices, plus the rejection gates. Run:
    python3 test_payoffs.py
"""
import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)),
                                  "..", "src"))
# Screener modules require PUBLIC_ACCOUNT_ID at import time (#23); unit
# tests never hit the API, so a dummy value suffices.
_os.environ.setdefault("PUBLIC_ACCOUNT_ID", "TEST")


import unittest

from spread_screener import evaluate_asym_condor


def make_wing(short_strike, long_strike, credit_per_share, expiration="2026-11-20",
              width=5, dte=40, leg_spread_sum=0.02, short_delta=0.15):
    return {
        "expiration": expiration,
        "short_strike": short_strike,
        "long_strike": long_strike,
        "width": width,
        "credit_per_share": credit_per_share,
        "credit_total": credit_per_share * 100,
        "leg_spread_sum": leg_spread_sum,
        "net_delta": 0.0,
        "short_delta": short_delta,
        "dte": dte,
    }


def expiration_pnl(price, legs, total_credit):
    """Hand-rolled expiration P&L per share. legs: list of (kind, strike)
    where kind is +1 for long, -1 for short; puts pay max(K-S,0),
    calls pay max(S-K,0)."""
    pnl = total_credit
    for kind, opt_type, strike in legs:
        if opt_type == "P":
            pnl += kind * max(strike - price, 0)
        else:
            pnl += kind * max(price - strike, 0)
    return pnl


# Canonical fixture: spot 100, 95/90P + 110/115C, $1.80 total credit.
LEGS = [(-1, "P", 95), (+1, "P", 90), (-1, "C", 110), (+1, "C", 115)]
CREDIT = 1.80


class TestAsymCondorPayoff(unittest.TestCase):
    def setUp(self):
        self.put = make_wing(95, 90, 1.00, short_delta=-0.15)
        self.call = make_wing(110, 115, 0.80)
        self.res = evaluate_asym_condor(100, self.put, self.call, 5)
        self.assertTrue(self.res["accepted"], self.res.get("reasons"))

    def test_accepted_shape(self):
        self.assertEqual(self.res["kind"], "asym_condor")
        self.assertAlmostEqual(self.res["max_loss_total"], 320.0)
        self.assertAlmostEqual(self.res["breakeven_put"], 93.20)
        self.assertAlmostEqual(self.res["breakeven_call"], 111.80)

    def test_max_loss_matches_worst_wing(self):
        # Both wings are width 5; worst wing loss = (5 - 1.80) * 100.
        self.assertAlmostEqual(self.res["max_loss_total"], (5 - CREDIT) * 100)

    def test_payoff_below_put_wing(self):
        # S=85: put spread loses full width; P&L = -(width - credit).
        self.assertAlmostEqual(expiration_pnl(85, LEGS, CREDIT), -(5 - CREDIT))

    def test_payoff_at_put_breakeven(self):
        self.assertAlmostEqual(expiration_pnl(93.20, LEGS, CREDIT), 0.0, places=6)

    def test_payoff_between_wings_is_max_profit(self):
        # S=100: everything expires worthless; keep the full credit.
        self.assertAlmostEqual(expiration_pnl(100, LEGS, CREDIT), CREDIT)

    def test_payoff_at_call_breakeven(self):
        self.assertAlmostEqual(expiration_pnl(111.80, LEGS, CREDIT), 0.0, places=6)

    def test_payoff_above_call_wing(self):
        # S=120: call spread loses full width; P&L = -(width - credit).
        self.assertAlmostEqual(expiration_pnl(120, LEGS, CREDIT), -(5 - CREDIT))

    def test_payoff_at_extremes_is_bounded(self):
        # Defined risk: far tails converge to -max_loss, never worse.
        for s in (50, 200):
            self.assertAlmostEqual(expiration_pnl(s, LEGS, CREDIT),
                                   -self.res["max_loss_total"] / 100)

    def test_call_wing_too_close_rejected(self):
        # 105C is only 5% above spot 100; skew gate requires >= 8%.
        call = make_wing(105, 110, 0.80)
        res = evaluate_asym_condor(100, self.put, call, 5)
        self.assertFalse(res["accepted"])
        self.assertIn("call wing too close", res["reasons"])

    def test_overlapping_wings_rejected(self):
        call = make_wing(94, 99, 0.80)  # call short below put short
        res = evaluate_asym_condor(100, self.put, call, 5)
        self.assertFalse(res["accepted"])
        self.assertIn("wings overlap or inverted", res["reasons"])

    def test_different_expirations_rejected(self):
        call = make_wing(110, 115, 0.80, expiration="2026-12-18")
        res = evaluate_asym_condor(100, self.put, call, 5)
        self.assertFalse(res["accepted"])
        self.assertIn("wings on different expirations", res["reasons"])

    def test_max_loss_gate(self):
        # Width 15 with thin credit -> (15 - 1.80) * 100 = $1320 > $1000 cap.
        put = make_wing(95, 80, 1.00, width=15)
        call = make_wing(115, 130, 0.80, width=15)
        res = evaluate_asym_condor(100, put, call, 15)
        self.assertFalse(res["accepted"])
        self.assertIn("asym condor max loss over limit", res["reasons"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
