"""Tests for ledger.py (issue #10), including an end-to-end lifecycle test."""

import os
import tempfile
import unittest

import gates
from exits import evaluate
from ledger import (new_ledger, open_position, close_position, realized_pnl,
                    stats, open_heat, max_contracts, can_open, save, load)

LEGS = [{"side": "short", "type": "put", "strike": 150, "expiry": "2026-12-18"},
        {"side": "long", "type": "put", "strike": 145, "expiry": "2026-12-18"}]
CFG = {"max_loss_pct": 0.02, "heat_cap_pct": 0.35}


def open_spread(ledger, credit=1.00, contracts=1, max_loss=4.00):
    return open_position(ledger, "XOM", "bull_put_spread", LEGS, credit,
                         contracts, max_loss, dte=45,
                         fill_note="short bid - long ask", opened="2026-10-11")


class TestLedger(unittest.TestCase):
    def test_open_and_close_winner(self):
        l = new_ledger()
        p = open_spread(l)
        _, pnl = close_position(l, p["id"], close_cost=0.50,
                                reason="TAKE_PROFIT", closed="2026-11-01")
        # (1.00 - 0.50) * 100 * 1 - 0.65 - 0.65 = 48.70
        self.assertAlmostEqual(pnl, 48.70)
        self.assertEqual(p["status"], "closed")

    def test_close_loser(self):
        l = new_ledger()
        p = open_spread(l)
        _, pnl = close_position(l, p["id"], close_cost=2.00,
                                reason="STOP_LOSS", closed="2026-11-01")
        # (1.00 - 2.00) * 100 - 1.30 = -101.30
        self.assertAlmostEqual(pnl, -101.30)

    def test_close_unknown_id(self):
        l = new_ledger()
        with self.assertRaises(KeyError):
            close_position(l, "nope", 0.50, "MANUAL")

    def test_stats(self):
        l = new_ledger()
        p1 = open_spread(l, credit=1.00)
        close_position(l, p1["id"], 0.50, "TAKE_PROFIT", closed="2026-11-01")
        p2 = open_spread(l, credit=1.00)
        close_position(l, p2["id"], 2.00, "STOP_LOSS", closed="2026-11-02")
        s = stats(l)
        self.assertEqual(s["trades"], 2)
        self.assertEqual(s["win_rate"], 0.5)
        self.assertAlmostEqual(s["total"], 48.70 - 101.30)
        self.assertIn("bull_put_spread", s["by_strategy"])

    def test_stats_empty(self):
        s = stats(new_ledger())
        self.assertEqual(s["trades"], 0)
        self.assertEqual(s["win_rate"], 0.0)

    def test_open_heat(self):
        l = new_ledger()
        open_spread(l, contracts=1, max_loss=4.00)   # $400 at risk
        open_spread(l, contracts=2, max_loss=4.00)   # $800 at risk
        self.assertEqual(open_heat(l), 1200.00)

    def test_max_contracts(self):
        # $30k account, 2% = $600; $400 max loss per spread -> 1 contract
        self.assertEqual(max_contracts(4.00, 30000, 0.02), 1)
        # $600 max loss per spread -> 1 contract; $700 -> 0
        self.assertEqual(max_contracts(6.00, 30000, 0.02), 1)
        self.assertEqual(max_contracts(7.00, 30000, 0.02), 0)

    def test_can_open_ok(self):
        l = new_ledger()
        ok, reason = can_open(l, 4.00, 1, 30000, CFG)
        self.assertTrue(ok)
        self.assertIn("within", reason)

    def test_can_open_trade_too_big(self):
        l = new_ledger()
        ok, reason = can_open(l, 4.00, 5, 30000, CFG)  # $2000 > $600
        self.assertFalse(ok)
        self.assertIn("max 1 contracts", reason)

    def test_can_open_heat_cap(self):
        l = new_ledger()
        # Fill heat to near the 35% cap ($10,500 on $30k): 26 x $400 = $10,400
        open_spread(l, contracts=26, max_loss=4.00)
        ok, reason = can_open(l, 4.00, 1, 30000, CFG)
        self.assertFalse(ok)
        self.assertIn("heat cap", reason)

    def test_save_load_roundtrip(self):
        l = new_ledger()
        p = open_spread(l)
        close_position(l, p["id"], 0.50, "TAKE_PROFIT", closed="2026-11-01")
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        try:
            save(l, path)
            l2 = load(path)
            self.assertAlmostEqual(realized_pnl(l2), 48.70)
        finally:
            os.unlink(path)


class TestLifecycleEndToEnd(unittest.TestCase):
    """Entry -> mark -> exit signal -> ledger close -> P&L, using real gates."""

    def test_winner_lifecycle(self):
        g = gates.load()
        exits_cfg = g["exits"]["bull_put_spread"]
        ledger_cfg = g["ledger"]
        account = 30000

        l = new_ledger()
        ok, _ = can_open(l, 4.00, 1, account, ledger_cfg)
        self.assertTrue(ok)
        p = open_spread(l)  # credit 1.00, 45 DTE

        # Days pass; mark falls to 0.45 at 30 DTE -> exit module says take profit.
        action, reason = evaluate(p["credit"], 0.45, 30, cfg=exits_cfg)
        self.assertEqual(action, "TAKE_PROFIT")

        _, pnl = close_position(l, p["id"], 0.45, action, closed="2026-11-10",
                                note=reason)
        self.assertGreater(pnl, 0)
        self.assertAlmostEqual(realized_pnl(l), pnl)
        self.assertEqual(open_heat(l), 0)

    def test_loser_lifecycle(self):
        g = gates.load()
        exits_cfg = g["exits"]["bull_put_spread"]
        l = new_ledger()
        p = open_spread(l)
        action, _ = evaluate(p["credit"], 2.10, 30, cfg=exits_cfg)
        self.assertEqual(action, "STOP_LOSS")
        _, pnl = close_position(l, p["id"], 2.10, action, closed="2026-11-10")
        self.assertLess(pnl, 0)
        s = stats(l)
        self.assertEqual(s["win_rate"], 0.0)

    def test_time_exit_lifecycle(self):
        g = gates.load()
        exits_cfg = g["exits"]["bull_put_spread"]
        l = new_ledger()
        p = open_spread(l)
        action, _ = evaluate(p["credit"], 0.80, 6, cfg=exits_cfg)
        self.assertEqual(action, "TIME_EXIT")
        _, pnl = close_position(l, p["id"], 0.80, action, closed="2026-11-10")
        self.assertGreater(pnl, 0)  # small winner closed early


if __name__ == "__main__":
    unittest.main(verbosity=2)
