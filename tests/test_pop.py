"""Tests for distribution-based POP and expected-move candidates (#77)."""
import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)),
                                  "..", "src"))
_os.environ.setdefault("PUBLIC_ACCOUNT_ID", "TEST")

import unittest
from datetime import date, timedelta

from options_math import (estimate_pop, expected_move,
                          expected_move_candidates,
                          lognormal_probability_between)
import spread_screener as ss


def _leg(strike, bid, ask, delta, iv, exp):
    return {"sym": f"X{strike}", "strike": strike, "bid": bid, "ask": ask,
            "spread": ask - bid, "delta": delta, "iv": iv, "expiration": exp}


class PopTests(unittest.TestCase):
    def test_monotonic_in_breakeven(self):
        ps = [lognormal_probability_between(100, .3, 30, lower=b)
              for b in (80, 90, 95, 100, 110)]
        self.assertEqual(ps, sorted(ps, reverse=True))

    def test_monotonic_in_vol(self):
        lo = lognormal_probability_between(100, .2, 30, 90, 110)
        hi = lognormal_probability_between(100, .5, 30, 90, 110)
        self.assertGreater(lo, hi)

    def test_boundaries(self):
        self.assertAlmostEqual(lognormal_probability_between(100, .3, 30), 1.0)
        self.assertEqual(lognormal_probability_between(100, .3, 30, lower=1e9), 0.0)
        self.assertEqual(lognormal_probability_between(100, 0, 30, 90, 110), 1.0)
        self.assertEqual(lognormal_probability_between(100, .3, 0, 101, 110), 0.0)
        with self.assertRaises(ValueError):
            lognormal_probability_between(100, .3, 30, 110, 90)

    def test_condor_not_above_either_wing(self):
        both = estimate_pop(100, .3, 30, 90, 110)["pop"]
        put = estimate_pop(100, .3, 30, breakeven_low=90)["pop"]
        call = estimate_pop(100, .3, 30, breakeven_high=110)["pop"]
        self.assertLess(both, min(put, call))
        self.assertAlmostEqual(both, put + call - 1, places=9)

    def test_report_fields(self):
        r = estimate_pop(100, .3, 30, 90, 110, rate=.04, dividend_yield=.02)
        for k in ("method", "assumptions", "expected_move", "limitations"):
            self.assertTrue(r[k])
        self.assertEqual(r["assumptions"]["rate"], .04)


class ExpectedMoveTests(unittest.TestCase):
    def test_move(self):
        em = expected_move(100, .365, 365 / 4)
        self.assertAlmostEqual(em["move"], 100 * .365 * .5)

    def test_candidates_grid(self):
        grid = [float(k) for k in range(60, 141)]
        c = expected_move_candidates(100, .4, 30, grid)
        move = c["expected_move"]["move"]
        self.assertTrue(c["put_short_strikes"])
        for k in c["put_short_strikes"]:
            self.assertLess(k, 100 - move + 1e-9)
        for k in c["call_short_strikes"]:
            self.assertGreater(k, 100 + move - 1e-9)
        self.assertTrue(all(w >= 1 and w == int(w) for w in c["widths"]))

    def test_candidates_no_grid(self):
        c = expected_move_candidates(100, .2, 30, short_multiples=(1.0,))
        move = c["expected_move"]["move"]
        self.assertEqual(c["put_short_strikes"], [round(100 - move, 2)])
        self.assertEqual(c["call_short_strikes"], [round(100 + move, 2)])


class ScreenerPopTests(unittest.TestCase):
    def setUp(self):
        self.exp = (date.today() + timedelta(days=30)).isoformat()

    def test_vertical_uses_distribution_and_keeps_credit(self):
        s = _leg(90, 1.00, 1.10, -.15, .30, self.exp)
        l = _leg(85, .40, .50, -.08, .32, self.exp)
        r = ss.evaluate_vertical(100, s, l, 5, "bull_put")
        self.assertTrue(r["accepted"], r)
        self.assertAlmostEqual(r["credit_per_share"], 0.50)  # bid - ask
        self.assertIn("lognormal", r["pop_method"])
        self.assertTrue(r["expected_move"] and r["pop_limitations"])
        self.assertAlmostEqual(r["breakeven"], 89.5)
        self.assertEqual(r["best_case_range"], [89.5, "and up"])

    def test_vertical_falls_back_without_iv(self):
        s = _leg(90, 1.00, 1.10, -.15, None, self.exp)
        l = _leg(85, .40, .50, -.08, None, self.exp)
        r = ss.evaluate_vertical(100, s, l, 5, "bull_put")
        self.assertEqual(r["pop_method"], "delta_approximation")
        self.assertAlmostEqual(r["win_prob_est"], .85)

    def test_condor_pop(self):
        put = ss.evaluate_vertical(100, _leg(90, 1.0, 1.1, -.15, .3, self.exp),
                                   _leg(85, .4, .5, -.08, .3, self.exp), 5,
                                   "bull_put")
        call = ss.evaluate_vertical(100, _leg(110, 1.0, 1.1, .15, .3, self.exp),
                                    _leg(115, .4, .5, .08, .3, self.exp), 5,
                                    "bear_call")
        c = ss.evaluate_condor(100, put, call, 5)
        self.assertTrue(c["accepted"], c)
        self.assertIn("lognormal", c["pop_method"])
        self.assertLessEqual(c["win_prob_est"], min(put["win_prob_est"],
                                                    call["win_prob_est"]))


if __name__ == "__main__":
    unittest.main()
