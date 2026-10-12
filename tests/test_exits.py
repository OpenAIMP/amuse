"""Tests for exits.py: bull put spread exit rules (issue #9)."""
import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)),
                                  "..", "src"))


import unittest

from exits import (evaluate, describe, HOLD, TAKE_PROFIT, STOP_LOSS,
                   TIME_EXIT, EXPIRATION_RISK)

STD = {"profit_target_pct": 0.50, "stop_loss_mult": 2.0,
       "min_dte_exit": 7, "assignment_dte": 2, "no_assignment": True}


class TestExits(unittest.TestCase):
    def test_hold_mid(self):
        # Credit 1.00, buy-back 0.80 at 30 DTE: nothing hit.
        action, _ = evaluate(1.00, 0.80, 30, cfg=STD)
        self.assertEqual(action, HOLD)

    def test_take_profit(self):
        # Buy-back at 0.50 keeps 50% of a 1.00 credit.
        action, reason = evaluate(1.00, 0.50, 30, cfg=STD)
        self.assertEqual(action, TAKE_PROFIT)
        self.assertIn("50%", reason)

    def test_take_profit_better(self):
        action, _ = evaluate(1.00, 0.20, 30, cfg=STD)
        self.assertEqual(action, TAKE_PROFIT)

    def test_stop_loss(self):
        # Buy-back at 2.00 = 2x the 1.00 credit.
        action, reason = evaluate(1.00, 2.00, 30, cfg=STD)
        self.assertEqual(action, STOP_LOSS)
        self.assertIn("2.0x", reason)

    def test_stop_before_max_loss(self):
        # Stop triggers well before the spread's full width is lost:
        # 2x credit on a width-5 spread is a fraction of max loss.
        action, _ = evaluate(1.00, 2.50, 30, cfg=STD)
        self.assertEqual(action, STOP_LOSS)

    def test_time_exit(self):
        action, reason = evaluate(1.00, 0.80, 7, cfg=STD)
        self.assertEqual(action, TIME_EXIT)
        action, _ = evaluate(1.00, 0.80, 3, cfg=STD)
        self.assertEqual(action, TIME_EXIT)

    def test_time_exit_beats_profit(self):
        # At 5 DTE with profit available, time exit wins (no holding through).
        action, _ = evaluate(1.00, 0.40, 5, cfg=STD)
        self.assertEqual(action, TIME_EXIT)

    def test_expiration_risk(self):
        action, reason = evaluate(1.00, 3.00, 1, short_itm=True, cfg=STD)
        self.assertEqual(action, EXPIRATION_RISK)
        self.assertIn("assignment", reason)

    def test_expiration_risk_beats_stop(self):
        action, _ = evaluate(1.00, 2.00, 1, short_itm=True, cfg=STD)
        self.assertEqual(action, EXPIRATION_RISK)

    def test_otm_near_expiry_no_assignment_panic(self):
        # Short OTM at 1 DTE with profit: time exit, not expiration risk.
        action, _ = evaluate(1.00, 0.10, 1, short_itm=False, cfg=STD)
        self.assertEqual(action, TIME_EXIT)

    def test_custom_config(self):
        cfg = dict(STD, profit_target_pct=0.75)
        action, _ = evaluate(1.00, 0.50, 30, cfg=cfg)  # only 50% kept
        self.assertEqual(action, HOLD)
        action, _ = evaluate(1.00, 0.25, 30, cfg=cfg)  # 75% kept
        self.assertEqual(action, TAKE_PROFIT)

    def test_bad_inputs_hold(self):
        action, _ = evaluate(0, 0.50, 30, cfg=STD)
        self.assertEqual(action, HOLD)
        action, _ = evaluate(1.00, -0.10, 30, cfg=STD)
        self.assertEqual(action, HOLD)

    def test_describe(self):
        self.assertIn("50%", describe(STD))
        self.assertIn("7 DTE", describe(STD))


if __name__ == "__main__":
    unittest.main(verbosity=2)
