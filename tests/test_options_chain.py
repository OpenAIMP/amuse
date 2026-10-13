"""Unit tests for options_chain.py (issue #36).

Consolidated option-chain plumbing from spread_screener.py and
pmcc_quality.py. MCP calls are faked at the mcp_client funnel.
"""
import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)),
                                  "..", "src"))

import unittest
from datetime import date, timedelta

import mcp_client
import options_chain as oc


class TestParseOsi(unittest.TestCase):
    def test_call(self):
        exp, is_call, strike = oc.parse_osi("AAPL260116C00150000")
        self.assertEqual(exp, "2026-01-16")
        self.assertTrue(is_call)
        self.assertAlmostEqual(strike, 150.0)

    def test_put(self):
        exp, is_call, strike = oc.parse_osi("XOM260116P00095000")
        self.assertEqual(exp, "2026-01-16")
        self.assertFalse(is_call)
        self.assertAlmostEqual(strike, 95.0)

    def test_bad_symbol_raises(self):
        with self.assertRaises(ValueError):
            oc.parse_osi("GARBAGE")

    def test_optional_int(self):
        self.assertEqual(oc.optional_int("42"), 42)
        self.assertIsNone(oc.optional_int(None))
        self.assertIsNone(oc.optional_int("nope"))


class TestDte(unittest.TestCase):
    def test_iso_string(self):
        future = (date.today() + timedelta(days=30)).isoformat()
        self.assertEqual(oc.dte(future), 30)

    def test_date_object(self):
        self.assertEqual(oc.dte(date.today() + timedelta(days=7)), 7)

    def test_eligible_expirations(self):
        exps = [(date.today() + timedelta(days=d)).isoformat()
                for d in (10, 30, 90, 200)]
        self.assertEqual(oc.eligible_expirations(exps, 21, 60),
                         [exps[1]])  # only +30d sits in 21..60


class TestParseChain(unittest.TestCase):
    def _fake_chain(self, tool, args):
        assert tool == "get_option_chain"
        return {"puts": [
            {"instrument": {"symbol": "XOM260116P00095000"},
             "bid": 1.20, "ask": 1.30, "openInterest": 100, "volume": 50},
            {"instrument": {"symbol": "XOM260116P00090000"},
             "bid": 0.0, "ask": 0.10, "openInterest": 5, "volume": 0},
        ], "calls": []}

    def test_puts_parsed_and_filtered(self):
        real = mcp_client.mcp_call
        mcp_client.mcp_call = self._fake_chain
        try:
            out, diag = oc.parse_chain("XOM", "2026-01-16", "TEST",
                                       min_liquidity=10,
                                       max_spread_pct=0.25, want="puts")
        finally:
            mcp_client.mcp_call = real
        # 95 put passes; 90 put has zero bid -> bad_quote
        self.assertEqual(sorted(out), ["XOM260116P00095000"])
        self.assertEqual(diag["bad_quote"], 1)
        c = out["XOM260116P00095000"]
        self.assertAlmostEqual(c["strike"], 95.0)
        self.assertAlmostEqual(c["mid"], 1.25)


class TestGreeks(unittest.TestCase):
    def _fake_greeks(self, tool, args):
        assert tool == "get_option_greeks"
        return {"greeks": [
            {"symbol": s,
             "greeks": {"delta": d, "impliedVolatility": 0.30}}
            for s, d in [("P1", -0.15), ("C1", 0.15), ("BAD", 5.0)]]}

    def test_signed_accepts_negative_delta(self):
        real = mcp_client.mcp_call
        mcp_client.mcp_call = self._fake_greeks
        try:
            out, errors = oc.greeks(["P1", "C1", "BAD"], "TEST", signed=True)
        finally:
            mcp_client.mcp_call = real
        self.assertEqual(set(out), {"P1", "C1"})
        self.assertTrue(any("BAD" in e for e in errors))

    def test_unsigned_rejects_negative_delta(self):
        real = mcp_client.mcp_call
        mcp_client.mcp_call = self._fake_greeks
        try:
            out, _ = oc.greeks(["P1", "C1"], "TEST", signed=False)
        finally:
            mcp_client.mcp_call = real
        self.assertEqual(set(out), {"C1"})


if __name__ == "__main__":
    unittest.main()
