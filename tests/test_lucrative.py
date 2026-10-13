"""Tests for issue #28: the Lucrative verdict column on spread tables.

lucrative_label combines Win%, EV$, and Lossx into a single verdict:
Lucrative / Solid / Negative EV / High risk / Marginal / Unknown.
The renderer reads r['lucrative'] with a default, so a missing key must
not break the render path (partial-batch push safety).
"""
import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)),
                                  "..", "src"))

import os
os.environ.setdefault("PUBLIC_ACCOUNT_ID", "test-account")

import unittest

from spread_screener import lucrative_label
import render_report


class TestLucrativeLabel(unittest.TestCase):
    def test_lucrative_boundaries(self):
        # Exact thresholds: 70% win, positive EV, <=3x loss
        self.assertEqual(lucrative_label(0.70, 1.0, 3.0), "Lucrative")
        self.assertEqual(lucrative_label(0.99, 500.0, 1.5), "Lucrative")

    def test_solid_band(self):
        self.assertEqual(lucrative_label(0.60, 1.0, 4.0), "Solid")
        self.assertEqual(lucrative_label(0.69, 10.0, 3.5), "Solid")

    def test_negative_ev_dominates(self):
        # Negative EV is red-flagged even at high win rates
        self.assertEqual(lucrative_label(0.85, -1.0, 2.0), "Negative EV")
        self.assertEqual(lucrative_label(0.50, 0.0, 2.0), "Negative EV")

    def test_high_risk(self):
        self.assertEqual(lucrative_label(0.85, 10.0, 4.01), "High risk")
        self.assertEqual(lucrative_label(0.50, 10.0, 9.0), "High risk")

    def test_marginal_is_the_rest(self):
        self.assertEqual(lucrative_label(0.50, 5.0, 2.0), "Marginal")
        # 4.5x loss multiple is High risk even with positive EV (fail closed)
        self.assertEqual(lucrative_label(0.65, 5.0, 4.5), "High risk")

    def test_unknown_on_missing_inputs(self):
        self.assertEqual(lucrative_label(None, 5.0, 2.0), "Unknown")
        self.assertEqual(lucrative_label(0.75, None, 2.0), "Unknown")

    def test_missing_loss_mult_is_conservative(self):
        # None loss multiple -> treated as 99x -> High risk (fail closed)
        self.assertEqual(lucrative_label(0.80, 10.0, None), "High risk")


class TestLucrativeRender(unittest.TestCase):
    """Issue #17 lesson: the renderer must be executed, not just parsed."""

    def _row(self, **kw):
        base = {"expiration": "2026-11-13", "short_strike": 210,
                "long_strike": 205, "credit_total": 142.0,
                "max_loss_total": 358.0, "breakeven": 208.58,
                "return_on_risk": 0.397, "win_prob_est": 0.75,
                "expected_value": 25.0, "loss_multiple": 2.5,
                "events": [], "lucrative": "Lucrative"}
        base.update(kw)
        return base

    def test_verdict_cell_renders(self):
        data = {"asof": "2026-10-12", "readout": [],
                "results": {"bull_puts": {"NVDA": self._row()},
                            "iron_condors": {}, "asymmetric": {}}}
        html = render_report.spread_tables(data)
        self.assertIn(">Lucrative<", html)
        self.assertIn("Lucrative verdict", html)

    def test_missing_verdict_does_not_break_render(self):
        row = self._row()
        del row["lucrative"]
        data = {"asof": "2026-10-12", "readout": [],
                "results": {"bull_puts": {"NVDA": row},
                            "iron_condors": {}, "asymmetric": {}}}
        html = render_report.spread_tables(data)  # must not raise
        self.assertIn("\u2014", html)  # em-dash placeholder cell


if __name__ == "__main__":
    unittest.main()
