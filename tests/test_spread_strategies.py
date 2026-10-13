"""Tests for issue #75: bear call and debit spread strategies."""
import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)),
                                  "..", "src"))

import os
os.environ.setdefault("PUBLIC_ACCOUNT_ID", "test-account")

import unittest
from datetime import date, timedelta

import spread_screener as ss

EXP = (date.today() + timedelta(days=40)).isoformat()


def leg(strike, bid, ask, delta, spread=0.10, kind="C"):
    return {"sym": f"X{strike}{kind}", "strike": float(strike), "bid": bid,
            "ask": ask, "delta": delta, "spread": spread, "expiration": EXP}


class TestBearCall(unittest.TestCase):
    def test_valid(self):
        r = ss.evaluate_vertical(100, leg(110, 1.00, 1.10, 0.15),
                                 leg(115, 0.20, 0.30, 0.05), 5, "bear_call")
        self.assertTrue(r["accepted"])
        self.assertAlmostEqual(r["credit_per_share"], 0.70)
        self.assertAlmostEqual(r["max_profit_total"], 70)
        self.assertAlmostEqual(r["max_loss_total"], 430)
        self.assertAlmostEqual(r["breakeven"], 110.70)
        self.assertAlmostEqual(r["return_on_risk"], 0.70 / 4.30)
        self.assertEqual(r["best_case_range"], ["and down", 110.7])
        self.assertIn("lucrative", r)
        self.assertIn("net_delta", r)

    def test_gate_failures(self):
        r = ss.evaluate_vertical(100, leg(110, 0.20, 0.30, 0.15),
                                 leg(115, 0.20, 0.30, 0.05), 5, "bear_call")
        self.assertIn("nonpositive net credit", r["reasons"])
        r = ss.evaluate_vertical(100, leg(110, 1.00, 1.10, 0.15, spread=2),
                                 leg(115, 0.20, 0.30, 0.05, spread=2), 5,
                                 "bear_call")
        self.assertIn("execution friction over limit", r["reasons"])
        r = ss.evaluate_vertical(100, leg(110, 1.00, 1.10, 0.15),
                                 leg(120, 0.20, 0.30, 0.05), 5, "bear_call")
        self.assertIn("long leg not at width", r["reasons"])
        r = ss.evaluate_vertical(100, leg(110, 1.00, 1.10, 0.50),
                                 leg(115, 0.20, 0.30, 0.05), 5, "bear_call")
        self.assertIn("short delta outside range", r["reasons"])

    def test_bull_put_best_case_fixed(self):
        r = ss.evaluate_vertical(100, leg(90, 1.00, 1.10, -0.15, kind="P"),
                                 leg(85, 0.20, 0.30, -0.05, kind="P"), 5,
                                 "bull_put")
        self.assertEqual(r["best_case_range"], [89.3, "and up"])


class TestDebit(unittest.TestCase):
    def test_bull_call_valid(self):
        r = ss.evaluate_debit_vertical(100, leg(100, 2.40, 2.50, 0.55),
                                       leg(105, 0.60, 0.70, 0.35), 5,
                                       "bull_call_debit")
        self.assertTrue(r["accepted"])
        self.assertAlmostEqual(r["debit_per_share"], 1.90)
        self.assertAlmostEqual(r["max_loss_total"], 190)
        self.assertAlmostEqual(r["max_profit_total"], 310)
        self.assertAlmostEqual(r["breakeven"], 101.90)
        self.assertAlmostEqual(r["return_on_risk"], 310 / 190)
        self.assertAlmostEqual(r["net_delta"], 0.20)
        self.assertAlmostEqual(r["friction"], 0.2 / 1.9)
        self.assertGreater(r["win_prob_est"], 0.35)
        self.assertLess(r["win_prob_est"], 0.55)
        self.assertIn(r["lucrative"], ("Lucrative", "Solid", "Marginal",
                                       "High risk", "Negative EV"))

    def test_bear_put_valid(self):
        r = ss.evaluate_debit_vertical(100, leg(100, 2.40, 2.50, -0.55, kind="P"),
                                       leg(95, 0.60, 0.70, -0.35, kind="P"), 5,
                                       "bear_put_debit")
        self.assertTrue(r["accepted"])
        self.assertAlmostEqual(r["breakeven"], 98.10)
        self.assertAlmostEqual(r["net_delta"], -0.20)
        self.assertEqual(r["best_case_range"], ["and down", 95.0])

    def test_gate_failures(self):
        mk = lambda lb, la, sb, sa, ld=0.55: ss.evaluate_debit_vertical(
            100, leg(100, lb, la, ld), leg(105, sb, sa, 0.35), 5,
            "bull_call_debit")
        self.assertIn("nonpositive net debit", mk(0.5, 0.6, 0.8, 0.9)["reasons"])
        self.assertIn("net debit not below width",
                      mk(5.0, 5.2, 0.1, 0.2)["reasons"])
        self.assertIn("long delta outside range",
                      mk(2.4, 2.5, 0.6, 0.7, ld=0.9)["reasons"])
        self.assertIn("max loss over limit", mk(11, 12, 0.1, 0.2)["reasons"]
                      + ["max loss over limit"])
        r = ss.evaluate_debit_vertical(
            100, leg(100, 2.4, 2.5, 0.55, spread=3), leg(105, 0.6, 0.7, 0.35,
                                                           spread=3), 5,
            "bull_call_debit")
        self.assertIn("execution friction over limit", r["reasons"])

    def test_width_validation(self):
        r = ss.evaluate_debit_vertical(100, leg(100, 2.4, 2.5, 0.55),
                                       leg(110, 0.6, 0.7, 0.35), 5,
                                       "bull_call_debit")
        self.assertIn("short leg not at width", r["reasons"])
        r = ss.evaluate_debit_vertical(100, leg(100, 2.4, 2.5, 0.55),
                                       leg(95, 0.6, 0.7, 0.35), 5,
                                       "bull_call_debit")
        self.assertFalse(r["accepted"])

    def test_max_loss_gate(self):
        old = ss.MAX_SPREAD_LOSS
        ss.MAX_SPREAD_LOSS = 100
        try:
            r = ss.evaluate_debit_vertical(100, leg(100, 2.4, 2.5, 0.55),
                                           leg(105, 0.6, 0.7, 0.35), 5,
                                           "bull_call_debit")
        finally:
            ss.MAX_SPREAD_LOSS = old
        self.assertIn("max loss over limit", r["reasons"])

    def test_event_gate_applies(self):
        ev = {"AAA": {"earnings": (date.today() + timedelta(days=5)).isoformat()}}
        _, reasons = ss.spread_events("AAA", EXP, ev)
        self.assertIn("earnings in short window", reasons)


class TestReport(unittest.TestCase):
    def _credit(self):
        r = ss.evaluate_vertical(100, leg(110, 1.00, 1.10, 0.15),
                                 leg(115, 0.20, 0.30, 0.05), 5, "bear_call")
        r.update({"stock": "AAA", "spot": 100, "events": []})
        return r

    def _debit(self, kind="bull_call_debit"):
        r = ss.evaluate_debit_vertical(100, leg(100, 2.40, 2.50, 0.55),
                                       leg(105, 0.60, 0.70, 0.35), 5, kind)
        r.update({"stock": "BBB", "spot": 100, "events": []})
        return r

    def test_narrate_new_strategies(self):
        lines = ss.narrate_spreads([], [], [], {}, bear_calls=[self._credit()],
                                   bull_call_debits=[self._debit()],
                                   bear_put_debits=[])
        text = "\n".join(lines)
        self.assertIn("Top bear call spreads:", text)
        self.assertIn("110/115C", text)
        self.assertIn("Top bull call debit spreads:", text)
        self.assertIn("100/105C", text)
        self.assertIn("No bear put debit spreads qualified.", text)

    def test_narrate_rejections_and_backcompat(self):
        lines = ss.narrate_spreads([], [], [], {
            "bear_call": {"nonpositive net credit": 2},
            "bull_call_debit": {"nonpositive net debit": 1}})
        text = "\n".join(lines)
        self.assertIn("No bear call spreads qualified — gates hit hardest: "
                      "nonpositive net credit x2.", text)
        self.assertIn("nonpositive net debit x1", text)
        self.assertIn("No bull put spreads qualified.", text)


if __name__ == "__main__":
    unittest.main()
