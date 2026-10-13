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
            out, diag, rejected = oc.parse_chain("XOM", "2026-01-16", "TEST",
                                                  min_liquidity=10,
                                                  max_spread_pct=0.25, want="puts")
        finally:
            mcp_client.mcp_call = real
        # 95 put passes; 90 put has zero bid -> bad_quote
        self.assertEqual(sorted(out), ["XOM260116P00095000"])
        self.assertEqual(diag["bad_quote"], 1)
        # issue #38: rejected contracts are captured, not just counted
        self.assertEqual(len(rejected), 1)
        self.assertEqual(rejected[0]["gate"], "bad_quote")
        self.assertEqual(rejected[0]["strike"], 90.0)
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

    def test_full_greeks_preserve_valid_delta_iv_on_optional_failures(self):
        def fake(tool, args):
            return {"greeks": [
                {"symbol": "FULL", "greeks": {
                    "delta": -0.25, "impliedVolatility": 0.4, "gamma": 0.03,
                    "theta": -0.02, "vega": 0.08, "rho": -0.01}},
                {"symbol": "MISSING", "greeks": {
                    "delta": 0.2, "impliedVolatility": 0.3}},
                {"symbol": "INVALID", "greeks": {
                    "delta": 0.1, "impliedVolatility": 0.2, "gamma": "nan",
                    "theta": "bad", "vega": True, "rho": 0.01}},
            ]}

        real = mcp_client.mcp_call
        mcp_client.mcp_call = fake
        try:
            out, errors = oc.greeks(["FULL", "MISSING", "INVALID"], "TEST",
                                    include_all=True)
        finally:
            mcp_client.mcp_call = real
        self.assertEqual(out["FULL"], {
            "delta": -0.25, "iv": 0.4, "gamma": 0.03, "theta": -0.02,
            "vega": 0.08, "rho": -0.01})
        self.assertEqual(out["MISSING"], {
            "delta": 0.2, "iv": 0.3, "gamma": None, "theta": None,
            "vega": None, "rho": None})
        self.assertEqual(out["INVALID"], {
            "delta": 0.1, "iv": 0.2, "gamma": None, "theta": None,
            "vega": None, "rho": 0.01})
        self.assertTrue(any("gamma" in error for error in errors))
        self.assertTrue(any("theta" in error for error in errors))
        self.assertTrue(any("vega" in error for error in errors))

    def test_legacy_delta_iv_tuple_is_unchanged(self):
        real = mcp_client.mcp_call
        mcp_client.mcp_call = self._fake_greeks
        try:
            out, _ = oc.greeks(["P1"], "TEST")
        finally:
            mcp_client.mcp_call = real
        delta, iv = out["P1"]
        self.assertEqual((delta, iv), (-0.15, 0.30))

    def test_batches_deduplicated_symbols_and_validates_size(self):
        batches = []

        def fake(tool, args):
            batches.append(args["osi_symbols"])
            return {"greeks": [
                {"symbol": symbol, "greeks": {
                    "delta": 0.1, "impliedVolatility": 0.2}}
                for symbol in args["osi_symbols"]]}

        symbols = ["S0", "S1", "S2", "S3", "S4", "S0"]
        real = mcp_client.mcp_call
        mcp_client.mcp_call = fake
        try:
            out, errors = oc.greeks(symbols, "TEST", batch_size=2)
        finally:
            mcp_client.mcp_call = real
        self.assertEqual([len(batch) for batch in batches], [2, 2, 1])
        self.assertEqual(set(out), set(symbols))
        self.assertEqual(errors, [])
        with self.assertRaises(ValueError):
            oc.greeks([], "TEST", batch_size=0)


class TestAggregateGreeks(unittest.TestCase):
    def test_signed_portfolio_aggregation_and_partial_unavailability(self):
        out = oc.aggregate_greeks([
            {"greeks": {"delta": 0.5, "gamma": 0.02, "theta": -0.01,
                        "vega": 0.03, "rho": 0.04}, "quantity": 2},
            {"greeks": {"delta": -0.2, "gamma": 0.01, "theta": -0.02,
                        "vega": 0.02, "rho": None}, "quantity": -1},
        ], multiplier=100)
        self.assertEqual(out["delta"], 120.0)
        self.assertEqual(out["gamma"], 3.0)
        self.assertEqual(out["theta"], 0.0)
        self.assertAlmostEqual(out["vega"], 4.0)
        self.assertIsNone(out["rho"])

    def test_invalid_greek_does_not_invalidate_other_metrics(self):
        out = oc.aggregate_greeks([
            {"greeks": {"delta": 0.1, "gamma": float("inf"),
                        "theta": -0.1, "vega": "bad", "rho": 0.2}}
        ])
        self.assertEqual(out["delta"], 0.1)
        self.assertIsNone(out["gamma"])
        self.assertEqual(out["theta"], -0.1)
        self.assertIsNone(out["vega"])
        self.assertEqual(out["rho"], 0.2)


if __name__ == "__main__":
    unittest.main()
