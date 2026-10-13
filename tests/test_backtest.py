"""Tests for backtest.py: historical calibration of screened structures."""
import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)),
                                  "..", "src"))

import unittest
from datetime import date, timedelta

import backtest as bt


def rec(i, entry, close_exp, kind="bull_put", **kw):
    e = date.fromisoformat(entry)
    r = {"id": i, "symbol": "XYZ", "strategy": kind,
         "entry_date": entry, "expiry": (e + timedelta(days=30)).isoformat(),
         "credit": 1.0, "short_put": 95, "long_put": 90,
         "short_call": 105, "long_call": 110,
         "modeled_pop": 0.8, "modeled_ev": 10.0, "iv_rank": 60,
         "short_delta": -0.15, "regime": "bullish"}
    r.update(kw)
    return r


def closes_for(recs, price):
    out = {}
    for r in recs:
        e = (date.fromisoformat(r["entry_date"]) + timedelta(days=30)).isoformat()
        out.setdefault("XYZ", {})[e] = price(r)
    return out


class TestBacktest(unittest.TestCase):
    def test_settlement_and_metrics(self):
        recs = [rec(1, "2024-01-01"), rec(2, "2024-01-10"), rec(3, "2024-01-20")]
        px = {1: 100, 2: 100, 3: 85}
        res = bt.run_backtest(recs, closes_for(recs, lambda r: px[r["id"]]))
        pnl = [t["pnl"] for t in res["trades"]]
        self.assertEqual(pnl, [100.0, 100.0, -400.0])
        m = bt.metrics(res["trades"])
        self.assertAlmostEqual(m["win_rate"], 2 / 3)
        self.assertEqual(m["avg_win"], 100.0)
        self.assertEqual(m["avg_loss"], -400.0)
        self.assertAlmostEqual(m["profit_factor"], 0.5)
        self.assertEqual(m["max_drawdown"], 400.0)
        self.assertEqual(m["r_multiple"]["min"], -1.0)
        self.assertAlmostEqual(m["pop_gap"], 2 / 3 - 0.8)
        self.assertAlmostEqual(m["ev_gap"], -66.6666667 / 1 - 10.0, places=3)

    def test_iron_condor_call_side_loss(self):
        r = rec(1, "2024-01-01", None, kind="iron_condor", credit=2.0)
        res = bt.run_backtest([r], closes_for([r], lambda _: 112))
        self.assertAlmostEqual(res["trades"][0]["pnl"], -300.0)
        self.assertAlmostEqual(res["trades"][0]["r_multiple"], -1.0)

    def test_missing_and_lookahead_skipped(self):
        good = rec(1, "2024-01-01")
        bad = [rec(2, "2024-01-02", as_of="2024-01-05"),
               rec(3, "2024-01-03", credit=None),
               rec(4, "2024-01-04", short_put=None),
               rec(5, "2024-01-05"), "junk"]
        closes = closes_for([good], lambda _: 100)
        res = bt.run_backtest([good] + bad, closes)
        self.assertEqual(len(res["trades"]), 1)
        self.assertEqual(len(res["skipped"]), 5)
        self.assertEqual(bt.run_backtest(None, None),
                         {"trades": [], "skipped": []})
        self.assertEqual(bt.metrics([]), {"n": 0})

    def test_segments(self):
        recs = [rec(1, "2024-01-01", iv_rank=20), rec(2, "2024-01-02", iv_rank=80,
                 regime="bearish"), rec(3, "2024-01-03", iv_rank=None)]
        res = bt.run_backtest(recs, closes_for(recs, lambda _: 100))
        seg = bt.segment(res["trades"])
        self.assertEqual(seg["iv_rank"]["0-25"]["n"], 1)
        self.assertEqual(seg["iv_rank"]["unknown"]["n"], 1)
        self.assertEqual(seg["regime"]["bearish"]["n"], 1)
        self.assertEqual(seg["short_delta"]["0.15-0.20"]["n"], 3)
        self.assertEqual(seg["spread_width"]["5-<10"]["n"], 3)
        self.assertEqual(set(seg), set(bt.SEGMENTS))

    def test_out_of_sample_and_walk_forward(self):
        recs = [rec(i, (date(2024, 1, 1) + timedelta(days=5 * i)).isoformat())
                for i in range(20)]
        res = bt.run_backtest(recs, closes_for(recs, lambda _: 100))
        oos = bt.out_of_sample(res["trades"], 0.5)
        self.assertEqual(oos["in_sample"]["n"], 10)
        self.assertEqual(oos["out_of_sample"]["n"], 10)
        folds = bt.walk_forward(res["trades"], 30, 20)
        self.assertTrue(folds)
        for f in folds:
            self.assertLessEqual(f["train_start"], f["test_start"])
        self.assertEqual(bt.walk_forward([], 30, 20), [])
        with self.assertRaises(ValueError):
            bt.walk_forward(res["trades"], 0, 20)
        out = bt.report(recs, closes_for(recs, lambda _: 100),
                        wf_train_days=30, wf_test_days=20)
        self.assertIn("walk_forward", out)


if __name__ == "__main__":
    unittest.main()
