"""Unit tests for intraday_screen.py (issue #27).

Tests the pure signal logic without MCP access:
  - opening-range breakout/breakdown detection
  - VWAP reclaim/loss cross detection
  - time-prorated relative volume math
  - gate loading from gates.yaml
"""
import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)),
                                  "..", "src"))
_os.environ.setdefault("PUBLIC_ACCOUNT_ID", "TEST")

import unittest
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import intraday_screen as ids
from indicators import vwap

ET = ZoneInfo("America/New_York")


def _daily_bars(n=60, close=100.0):
    base = date.today() - timedelta(days=n + 10)
    out = []
    for i in range(n):
        c = close + 2.0 * (1 if i % 2 == 0 else -1)
        out.append({"date": base + timedelta(days=i), "open": c,
                    "high": c * 1.01, "low": c * 0.99, "close": c,
                    "volume": 1_000_000})
    return out


def _intraday_bar(ts, o, h, l, c, v):
    return {"ts": ts, "open": o, "high": h, "low": l, "close": c,
            "volume": v}


def _today_at(h, m):
    return datetime.now(ET).replace(hour=h, minute=m, second=0,
                                    microsecond=0)


class TestORB(unittest.TestCase):
    def test_breakout_up(self):
        # OR 9:30-9:45: high 102, low 100. Price 103 clears buffer.
        bars = [
            _intraday_bar(_today_at(9, 30), 100, 101, 100, 100.5, 50_000),
            _intraday_bar(_today_at(9, 35), 100.5, 102, 100.2, 101.5, 60_000),
            _intraday_bar(_today_at(9, 40), 101.5, 101.8, 101, 101.2, 40_000),
            _intraday_bar(_today_at(11, 0), 101.2, 103.5, 101, 103.2, 200_000),
        ]
        # monkeypatch the data sources
        ids.daily_bars = lambda s, acct: _daily_bars()
        ids.intraday_bars_today = lambda s: bars
        res, reasons = ids.screen_one("TEST", quote_map={"TEST": 103.2},
                                      now_et=_today_at(11, 0))
        self.assertEqual(res["orb_signal"], "breakout_up_hold")
        self.assertEqual(res["orb_high"], 102)
        self.assertEqual(res["orb_low"], 100)

    def test_breakdown_down(self):
        bars = [
            _intraday_bar(_today_at(9, 30), 100, 101, 99, 100, 50_000),
            _intraday_bar(_today_at(9, 35), 100, 100.5, 99.5, 99.8, 60_000),
            _intraday_bar(_today_at(11, 0), 99.8, 100, 98.5, 98.7, 200_000),
        ]
        ids.daily_bars = lambda s, acct: _daily_bars()
        ids.intraday_bars_today = lambda s: bars
        res, reasons = ids.screen_one("TEST", quote_map={"TEST": 98.7},
                                      now_et=_today_at(11, 0))
        self.assertEqual(res["orb_signal"], "breakdown_down_hold")

    def test_no_breakout_inside_range(self):
        bars = [
            _intraday_bar(_today_at(9, 30), 100, 102, 99, 100.5, 50_000),
            _intraday_bar(_today_at(9, 35), 100.5, 101.5, 99.5, 100.8, 60_000),
            _intraday_bar(_today_at(11, 0), 100.8, 101, 100.2, 100.5, 80_000),
        ]
        ids.daily_bars = lambda s, acct: _daily_bars()
        ids.intraday_bars_today = lambda s: bars
        res, reasons = ids.screen_one("TEST", quote_map={"TEST": 100.5},
                                      now_et=_today_at(11, 0))
        self.assertIsNone(res["orb_signal"])
        self.assertIn("no session momentum signal", reasons)


class TestVWAP(unittest.TestCase):
    def test_reclaim_up(self):
        # Early bars below VWAP, price now above
        bars = [
            _intraday_bar(_today_at(9, 30), 100, 100.5, 99.5, 99.8, 100_000),
            _intraday_bar(_today_at(9, 35), 99.8, 100, 99.3, 99.5, 100_000),
            _intraday_bar(_today_at(10, 0), 99.5, 100.2, 99.4, 100.0, 100_000),
            _intraday_bar(_today_at(11, 0), 100.0, 101.5, 100.0, 101.2, 300_000),
        ]
        ids.daily_bars = lambda s, acct: _daily_bars()
        ids.intraday_bars_today = lambda s: bars
        res, reasons = ids.screen_one("TEST", quote_map={"TEST": 101.2},
                                      now_et=_today_at(11, 0))
        # price 101.2 vs VWAP ~100 -> reclaim
        self.assertEqual(res["vwap_signal"], "reclaim_up")
        self.assertGreater(res["vwap_dist_pct"], 0)

    def test_session_vwap_math(self):
        bars = [
            _intraday_bar(_today_at(9, 30), 100, 102, 98, 100, 1000),
            _intraday_bar(_today_at(9, 35), 100, 104, 100, 102, 1000),
        ]
        # tp1 = (102+98+100)/3 = 100, tp2 = (104+100+102)/3 = 102
        # vwap = (100*1000 + 102*1000) / 2000 = 101
        self.assertAlmostEqual(vwap(bars), 101.0, places=6)
        self.assertIsNone(vwap([]))


class TestProratedVolume(unittest.TestCase):
    def test_prorated_calculation(self):
        # 20d avg = 1M/day. At 11:00 (90 min elapsed of 390),
        # expected = 1M * 90/390 = 230,769. Today vol 500k -> 2.17x
        bars = [
            _intraday_bar(_today_at(9, 30), 100, 102, 99, 101, 200_000),
            _intraday_bar(_today_at(9, 35), 101, 103, 100, 102, 300_000),
        ]
        ids.daily_bars = lambda s, acct: _daily_bars()  # 1M avg
        ids.intraday_bars_today = lambda s: bars
        res, reasons = ids.screen_one("TEST", quote_map={"TEST": 105.0},
                                      now_et=_today_at(11, 0))
        expected = 500_000 / (1_000_000 * 90 / 390)
        self.assertAlmostEqual(res["rel_vol_tp"], expected, places=4)
        self.assertEqual(res["elapsed_min"], 90)

    def test_thin_volume_rejected(self):
        bars = [
            _intraday_bar(_today_at(9, 30), 100, 101, 99, 100, 10_000),
            _intraday_bar(_today_at(11, 0), 100, 101, 99, 100, 10_000),
        ]
        ids.daily_bars = lambda s, acct: _daily_bars()
        ids.intraday_bars_today = lambda s: bars
        res, reasons = ids.screen_one("TEST", quote_map={"TEST": 100.5},
                                      now_et=_today_at(11, 0))
        self.assertLess(res["rel_vol_tp"], 1.5)
        self.assertIn("volume too thin (time-prorated)", reasons)


class TestGates(unittest.TestCase):
    def test_intraday_gates_load(self):
        import gates
        g = gates.load()["intraday"]
        self.assertEqual(g["or_minutes"], 15)
        self.assertEqual(g["rel_vol_min"], 1.5)
        self.assertEqual(g["vwap_lookback_bars"], 6)


if __name__ == "__main__":
    unittest.main(verbosity=2)
