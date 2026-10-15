"""Tests for issue #13: musellm second-opinion verification.

Covers:
- Evidence packaging
- Fail-closed behavior (dissent/abstain -> not actionable)
- Disabled mode (defers to primary)
- Both A2A and API interface stubs
"""

import unittest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ.setdefault("PUBLIC_ACCOUNT_ID", "test-account")

from second_opinion import (
    build_evidence,
    get_second_opinion,
    is_actionable,
    log_opinion,
)


def _make_candidate():
    return {
        "symbol": "TEST",
        "strategy": "bull_put_spread",
        "recommendation": "CONSIDER",
        "credit_total": 150.0,
        "max_loss_total": 350.0,
        "expected_value_delta_proxy": 45.0,
        "win_prob_est_delta_proxy": 0.72,
        "return_on_risk": 0.43,
        "dte": 36,
        "expiration": "2026-11-20",
        "steps": [
            {"step": 1, "name": "Regime", "status": "PASS", "detail": "trend=UP"},
            {"step": 2, "name": "Catalyst", "status": "PASS", "detail": "no events"},
        ],
        "reasons": [],
        "kelly_sizing": {"status": "SKIPPED"},
    }


class TestEvidence(unittest.TestCase):
    def test_build_evidence(self):
        ev = build_evidence(_make_candidate())
        self.assertEqual(ev["symbol"], "TEST")
        self.assertEqual(ev["strategy"], "bull_put_spread")
        self.assertEqual(len(ev["gates"]), 2)
        self.assertEqual(ev["gates"][0]["name"], "Regime")


class TestFailClosed(unittest.TestCase):
    def test_concur_is_actionable(self):
        so = {"verdict": "concur", "confidence": 0.85,
              "reasons": [], "mode": "api"}
        ok, reason = is_actionable(_make_candidate(), so)
        self.assertTrue(ok)
        self.assertIn("concurs", reason)

    def test_dissent_blocks(self):
        so = {"verdict": "dissent", "confidence": 0.7,
              "reasons": ["IV crush risk"], "mode": "api"}
        ok, reason = is_actionable(_make_candidate(), so)
        self.assertFalse(ok)
        self.assertIn("human review", reason)
        self.assertIn("IV crush", reason)

    def test_abstain_blocks(self):
        so = {"verdict": "abstain", "mode": "api",
              "reasons": ["timeout"], "error": "timeout"}
        ok, reason = is_actionable(_make_candidate(), so)
        self.assertFalse(ok)
        self.assertIn("human review", reason)

    def test_disabled_defers(self):
        so = {"verdict": "abstain", "mode": "disabled",
              "reasons": ["disabled"]}
        ok, reason = is_actionable(_make_candidate(), so)
        self.assertTrue(ok)
        self.assertIn("primary", reason)


class TestInterfaces(unittest.TestCase):
    def test_disabled_mode(self):
        cfg = {"mode": "disabled"}
        so = get_second_opinion(_make_candidate(), cfg=cfg)
        self.assertEqual(so["verdict"], "abstain")
        self.assertEqual(so["mode"], "disabled")

    def test_a2a_missing_config(self):
        cfg = {"mode": "a2a", "agent_id": ""}
        so = get_second_opinion(_make_candidate(), cfg=cfg)
        self.assertEqual(so["verdict"], "abstain")
        self.assertIn("error", so)

    def test_api_missing_config(self):
        cfg = {"mode": "api", "api_url": "", "api_key": ""}
        so = get_second_opinion(_make_candidate(), cfg=cfg)
        self.assertEqual(so["verdict"], "abstain")
        self.assertIn("error", so)

    def test_unknown_mode(self):
        cfg = {"mode": "bogus"}
        so = get_second_opinion(_make_candidate(), cfg=cfg)
        self.assertEqual(so["verdict"], "abstain")


class TestLogging(unittest.TestCase):
    def test_log_opinion(self):
        so = {"verdict": "concur", "mode": "api", "confidence": 0.9}
        rec = log_opinion(_make_candidate(), so)
        self.assertEqual(rec["symbol"], "TEST")
        self.assertEqual(rec["second_opinion"]["verdict"], "concur")
        self.assertIn("timestamp", rec)


if __name__ == "__main__":
    unittest.main()
