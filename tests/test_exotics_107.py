"""Tests for issue #107: exotic strategies (Phases G-I).

Covers:
- Phase G: Call/Put Ratio Backspreads, Broken Wing Butterflies, Inverse Broken Wings
- Phase H: Bull/Bear Call/Put Ladders, Jade Lizard, Reverse Jade Lizard
- Phase I: Synthetic Futures, Combos, Strip/Strap, Guts, Double Diagonal
"""

import unittest
import sys
import os

os.environ.setdefault("PUBLIC_ACCOUNT_ID", "test-account")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from spread_screener import (
    evaluate_call_backspread,
    evaluate_put_backspread,
    evaluate_broken_wing_butterfly,
    evaluate_inverse_broken_wing,
    evaluate_call_ladder,
    evaluate_put_ladder,
    evaluate_jade_lizard,
    evaluate_reverse_jade_lizard,
    evaluate_synthetic_future,
    evaluate_combo,
    evaluate_strip_strap,
    evaluate_guts,
    evaluate_double_diagonal,
)


def _make_opt(strike, expiration="2026-11-20", bid=1.0, ask=1.1, delta=0.3):
    return {
        "sym": "TEST", "strike": strike, "expiration": expiration,
        "delta": delta, "bid": bid, "ask": ask, "spread": ask - bid,
    }


class TestBackspreads(unittest.TestCase):
    def test_call_backspread_accepted(self):
        # Sell 1 ATM call (95), Buy 2 OTM calls (100)
        short_c = _make_opt(95, bid=5.0, ask=5.1)
        long_c = _make_opt(100, bid=3.0, ask=3.1)
        r = evaluate_call_backspread(100.0, short_c, long_c, long_c)
        self.assertTrue(r["accepted"], f"reasons: {r.get('reasons')}")
        self.assertEqual(r["kind"], "call_backspread")
        self.assertEqual(r["ratio"], "1x2")

    def test_call_backspread_rejects_bad_order(self):
        # Strikes not ordered correctly
        short_c = _make_opt(100, bid=3.0, ask=3.1)
        long_c = _make_opt(95, bid=5.0, ask=5.1)
        r = evaluate_call_backspread(100.0, short_c, long_c, long_c)
        self.assertFalse(r["accepted"])

    def test_put_backspread_accepted(self):
        # Sell 1 ATM put (105), Buy 2 OTM puts (100)
        short_p = _make_opt(105, bid=5.0, ask=5.1)
        long_p = _make_opt(100, bid=3.0, ask=3.1)
        r = evaluate_put_backspread(100.0, short_p, long_p, long_p)
        self.assertTrue(r["accepted"], f"reasons: {r.get('reasons')}")
        self.assertEqual(r["kind"], "put_backspread")


class TestBrokenWingButterfly(unittest.TestCase):
    def test_call_bwb_accepted(self):
        # Buy 95 call, Sell 2x 100 calls, Buy 110 call (broken wing: 10pt upper)
        w1 = _make_opt(95, bid=6.0, ask=6.1)
        body = _make_opt(100, bid=3.0, ask=3.1)
        w2 = _make_opt(110, bid=1.0, ask=1.1)
        r = evaluate_broken_wing_butterfly(100.0, w1, body, w2, "call_broken_wing")
        self.assertTrue(r["accepted"], f"reasons: {r.get('reasons')}")
        self.assertEqual(r["kind"], "call_broken_wing")
        self.assertEqual(r["wing_width_high"], 10)

    def test_put_bwb_accepted(self):
        # Buy 105 put, Sell 2x 100 puts, Buy 90 put
        w1 = _make_opt(105, bid=6.0, ask=6.1)
        body = _make_opt(100, bid=3.0, ask=3.1)
        w2 = _make_opt(90, bid=1.0, ask=1.1)
        r = evaluate_broken_wing_butterfly(100.0, w1, body, w2, "put_broken_wing")
        self.assertTrue(r["accepted"], f"reasons: {r.get('reasons')}")
        self.assertEqual(r["kind"], "put_broken_wing")

    def test_inverse_bwb_accepted(self):
        w1 = _make_opt(95, bid=6.0, ask=6.1)
        body = _make_opt(100, bid=3.0, ask=3.1)
        w2 = _make_opt(110, bid=1.0, ask=1.1)
        r = evaluate_inverse_broken_wing(100.0, w1, body, w2, "inverse_call_broken_wing")
        self.assertTrue(r["accepted"], f"reasons: {r.get('reasons')}")


class TestLadders(unittest.TestCase):
    def test_bull_call_ladder(self):
        # Buy 95 call, Sell 100 call, Sell 105 call
        l1 = _make_opt(95, bid=6.0, ask=6.1)
        l2 = _make_opt(100, bid=3.0, ask=3.1)
        l3 = _make_opt(105, bid=1.5, ask=1.6)
        r = evaluate_call_ladder(100.0, l1, l2, l3, "bull_call_ladder")
        self.assertTrue(r["accepted"], f"reasons: {r.get('reasons')}")
        self.assertTrue(r["risk_warning"])  # Undefined risk

    def test_bear_call_ladder(self):
        l1 = _make_opt(95, bid=6.0, ask=6.1)
        l2 = _make_opt(100, bid=3.0, ask=3.1)
        l3 = _make_opt(105, bid=1.5, ask=1.6)
        r = evaluate_call_ladder(100.0, l1, l2, l3, "bear_call_ladder")
        self.assertTrue(r["accepted"], f"reasons: {r.get('reasons')}")
        self.assertNotIn("risk_warning", r)  # Defined risk

    def test_bull_put_ladder(self):
        # Sell 105 put, Buy 100 put, Buy 95 put (descending)
        l1 = _make_opt(105, bid=6.0, ask=6.1)
        l2 = _make_opt(100, bid=3.0, ask=3.1)
        l3 = _make_opt(95, bid=1.5, ask=1.6)
        r = evaluate_put_ladder(100.0, l1, l2, l3, "bull_put_ladder")
        self.assertTrue(r["accepted"], f"reasons: {r.get('reasons')}")

    def test_bear_put_ladder_undefined_risk(self):
        l1 = _make_opt(105, bid=6.0, ask=6.1)
        l2 = _make_opt(100, bid=3.0, ask=3.1)
        l3 = _make_opt(95, bid=1.5, ask=1.6)
        r = evaluate_put_ladder(100.0, l1, l2, l3, "bear_put_ladder")
        self.assertTrue(r["accepted"], f"reasons: {r.get('reasons')}")
        self.assertTrue(r["risk_warning"])


class TestJadeLizard(unittest.TestCase):
    def test_jade_lizard_accepted(self):
        # Sell 95 put (naked), Sell 105 call / Buy 110 call
        short_put = _make_opt(95, bid=2.0, ask=2.1, delta=0.20)
        short_call = _make_opt(105, bid=1.5, ask=1.6, delta=-0.15)
        long_call = _make_opt(110, bid=0.5, ask=0.6, delta=-0.05)
        r = evaluate_jade_lizard(100.0, short_put, short_call, long_call)
        self.assertTrue(r["accepted"], f"reasons: {r.get('reasons')}")
        self.assertEqual(r["kind"], "jade_lizard")
        self.assertTrue(r["risk_warning"])

    def test_jade_lizard_rejects_itm_put(self):
        # Short put must be OTM
        short_put = _make_opt(105, bid=2.0, ask=2.1)  # ITM!
        short_call = _make_opt(105, bid=1.5, ask=1.6)
        long_call = _make_opt(110, bid=0.5, ask=0.6)
        r = evaluate_jade_lizard(100.0, short_put, short_call, long_call)
        self.assertFalse(r["accepted"])

    def test_reverse_jade_lizard_accepted(self):
        short_call = _make_opt(105, bid=1.5, ask=1.6)
        short_put = _make_opt(95, bid=2.0, ask=2.1)
        long_put = _make_opt(90, bid=0.5, ask=0.6)
        r = evaluate_reverse_jade_lizard(100.0, short_call, short_put, long_put)
        self.assertTrue(r["accepted"], f"reasons: {r.get('reasons')}")
        self.assertEqual(r["kind"], "reverse_jade_lizard")


class TestSynthetics(unittest.TestCase):
    def test_long_synthetic(self):
        call_c = _make_opt(100, bid=3.0, ask=3.1)
        put_c = _make_opt(100, bid=3.0, ask=3.1)
        r = evaluate_synthetic_future(100.0, call_c, put_c, "long_synthetic")
        self.assertTrue(r["accepted"])
        self.assertTrue(r["risk_warning"])

    def test_short_synthetic(self):
        call_c = _make_opt(100, bid=3.0, ask=3.1)
        put_c = _make_opt(100, bid=3.0, ask=3.1)
        r = evaluate_synthetic_future(100.0, call_c, put_c, "short_synthetic")
        self.assertTrue(r["accepted"])

    def test_synthetic_rejects_different_strikes(self):
        call_c = _make_opt(100, bid=3.0, ask=3.1)
        put_c = _make_opt(95, bid=3.0, ask=3.1)
        r = evaluate_synthetic_future(100.0, call_c, put_c, "long_synthetic")
        self.assertFalse(r["accepted"])


class TestCombos(unittest.TestCase):
    def test_long_combo(self):
        # Buy 105 call, Sell 95 put
        long_c = _make_opt(105, bid=1.5, ask=1.6)
        short_c = _make_opt(95, bid=2.0, ask=2.1)
        r = evaluate_combo(100.0, long_c, short_c, "long_combo")
        self.assertTrue(r["accepted"], f"reasons: {r.get('reasons')}")

    def test_short_combo(self):
        long_c = _make_opt(95, bid=2.0, ask=2.1)  # put
        short_c = _make_opt(105, bid=1.5, ask=1.6)  # call
        r = evaluate_combo(100.0, long_c, short_c, "short_combo")
        self.assertTrue(r["accepted"], f"reasons: {r.get('reasons')}")


class TestStripStrap(unittest.TestCase):
    def test_strip(self):
        p1 = _make_opt(100, bid=3.0, ask=3.1)
        p2 = _make_opt(100, bid=3.0, ask=3.1)
        c1 = _make_opt(100, bid=3.0, ask=3.1)
        r = evaluate_strip_strap(100.0, p1, p2, c1, "strip")
        self.assertTrue(r["accepted"])
        self.assertEqual(r["kind"], "strip")

    def test_strap(self):
        c1 = _make_opt(100, bid=3.0, ask=3.1)
        c2 = _make_opt(100, bid=3.0, ask=3.1)
        p1 = _make_opt(100, bid=3.0, ask=3.1)
        r = evaluate_strip_strap(100.0, c1, c2, p1, "strap")
        self.assertTrue(r["accepted"])


class TestGuts(unittest.TestCase):
    def test_long_guts(self):
        # Buy 95 call (ITM), Buy 105 put (ITM)
        call_c = _make_opt(95, bid=6.0, ask=6.1)
        put_c = _make_opt(105, bid=6.0, ask=6.1)
        r = evaluate_guts(100.0, call_c, put_c, "long_guts")
        self.assertTrue(r["accepted"], f"reasons: {r.get('reasons')}")

    def test_short_guts_undefined_risk(self):
        call_c = _make_opt(95, bid=6.0, ask=6.1)
        put_c = _make_opt(105, bid=6.0, ask=6.1)
        r = evaluate_guts(100.0, call_c, put_c, "short_guts")
        self.assertTrue(r["accepted"])
        self.assertTrue(r["risk_warning"])


class TestDoubleDiagonal(unittest.TestCase):
    def test_double_diagonal(self):
        near_call = _make_opt(105, expiration="2026-11-20", bid=1.5, ask=1.6)
        far_call = _make_opt(105, expiration="2026-12-18", bid=2.5, ask=2.6)
        near_put = _make_opt(95, expiration="2026-11-20", bid=1.5, ask=1.6)
        far_put = _make_opt(95, expiration="2026-12-18", bid=2.5, ask=2.6)
        r = evaluate_double_diagonal(100.0, near_call, far_call, near_put, far_put)
        self.assertTrue(r["accepted"], f"reasons: {r.get('reasons')}")
        self.assertEqual(r["kind"], "double_diagonal")


if __name__ == "__main__":
    unittest.main()
