"""Unit tests for market_data.py (issue #36).

Shared bar/quote fetching consolidated from the screeners' copy-pasted
bars_for / daily_bars_for / intraday_bars_for / quotes_for.
"""
import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)),
                                  "..", "src"))

import unittest
from datetime import date

import mcp_client
import market_data as md


def _bars_payload(n=5):
    base = date(2026, 1, 5)
    return {"regularMarket": {"bars": [
        {"timestamp": (base.replace(day=5 + i)).isoformat() if False else
         f"2026-01-{5 + i:02d}T00:00:00",
         "open": 100.0 + i, "high": 101.0 + i, "low": 99.0 + i,
         "close": 100.5 + i, "volume": 1_000_000}
        for i in range(n)] + [
        # one bad row: must be skipped, not crash
        {"timestamp": "2026-01-20T00:00:00", "open": 0, "high": -1,
         "low": 0, "close": 0, "volume": 0},
    ], "expectedBars": 78}}


def _quotes_payload(symbols):
    return {"data": [{"instrument": {"symbol": s}, "last": 100.0 + i}
                     for i, s in enumerate(symbols)]}


class _Fake:
    def __init__(self):
        self.tools = []

    def __call__(self, tool, args):
        self.tools.append(tool)
        if tool == "get_price_history":
            return _bars_payload()
        if tool == "get_quotes":
            return _quotes_payload(args["symbols"])
        raise AssertionError(tool)


class TestMarketData(unittest.TestCase):
    def setUp(self):
        self.fake = _Fake()
        self._real = mcp_client.mcp_call
        mcp_client.mcp_call = self.fake

    def tearDown(self):
        mcp_client.mcp_call = self._real

    def test_daily_bars_canonical_shape(self):
        bars = md.daily_bars("AAA", "TEST")
        self.assertEqual(len(bars), 5)  # bad row skipped
        b = bars[0]
        self.assertEqual(b["date"], date(2026, 1, 5))
        self.assertAlmostEqual(b["close"], 100.5)
        self.assertAlmostEqual(b["volume"], 1_000_000)
        self.assertEqual(self.fake.tools, ["get_price_history"])

    def test_intraday_bars_returns_expected(self):
        bars, expected = md.intraday_bars("AAA", "TEST")
        self.assertEqual(len(bars), 5)
        self.assertEqual(expected, 78)
        self.assertIn("ts", bars[0])

    def test_quotes_batch(self):
        m = md.quotes(["AAA", "BBB"], "TEST")
        self.assertEqual(m, {"AAA": 100.0, "BBB": 101.0})
        self.assertEqual(self.fake.tools, ["get_quotes"])

    def test_quote_single(self):
        self.assertAlmostEqual(md.quote("AAA", "TEST"), 100.0)

    def test_mcp_error_propagates(self):
        def boom(tool, args):
            raise mcp_client.McpError("down")
        mcp_client.mcp_call = boom
        with self.assertRaises(mcp_client.McpError):
            md.daily_bars("AAA", "TEST")


if __name__ == "__main__":
    unittest.main()
