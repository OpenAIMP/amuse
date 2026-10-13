"""Tests for issue #74: full Greeks retention and portfolio aggregation."""
import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)),
                                  "..", "src"))

import unittest

import mcp_client
import options_chain as oc


class TestGreeksFull(unittest.TestCase):
    def _fake(self, tool, args):
        assert tool == "get_option_greeks"
        return {"greeks": [
            {"symbol": "P1", "greeks": {
                "delta": -0.20, "impliedVolatility": 0.28,
                "gamma": 0.015, "theta": -0.04,
                "vega": 0.12, "rho": -0.01}},
            {"symbol": "C1", "greeks": {
                "delta": 0.35, "impliedVolatility": 0.31,
                "gamma": 0.022, "theta": -0.06,
                "vega": 0.18, "rho": 0.02}},
            {"symbol": "PARTIAL", "greeks": {
                "delta": 0.10, "impliedVolatility": 0.25,
                "gamma": 0.01}},
            {"symbol": "BAD", "greeks": {
                "delta": 5.0, "impliedVolatility": 0.30}},
        ]}

    def test_full_greeks_retained(self):
        real = mcp_client.mcp_call
        mcp_client.mcp_call = self._fake
        try:
            out, errors = oc.greeks_full(["P1", "C1"], "TEST")
        finally:
            mcp_client.mcp_call = real
        self.assertEqual(errors, [])
        self.assertEqual(set(out), {"P1", "C1"})
        self.assertAlmostEqual(out["P1"]["gamma"], 0.015)
        self.assertAlmostEqual(out["P1"]["theta"], -0.04)
        self.assertAlmostEqual(out["P1"]["vega"], 0.12)
        self.assertAlmostEqual(out["P1"]["rho"], -0.01)
        self.assertTrue(all(out[s]["available"][k] for s in ("P1", "C1")
                            for k in ("gamma", "theta", "vega", "rho")))

    def test_unrequested_symbols_are_filtered(self):
        real = mcp_client.mcp_call
        mcp_client.mcp_call = self._fake
        try:
            out, errors = oc.greeks_full(["P1"], "TEST")
        finally:
            mcp_client.mcp_call = real
        self.assertEqual(errors, [])
        self.assertEqual(set(out), {"P1"})

    def test_invalid_delta_is_reported(self):
        real = mcp_client.mcp_call
        mcp_client.mcp_call = self._fake
        try:
            out, errors = oc.greeks_full(["BAD"], "TEST")
        finally:
            mcp_client.mcp_call = real
        self.assertEqual(out, {})
        self.assertEqual(len(errors), 1)
        self.assertIn("BAD", errors[0])

    def test_partial_greeks_are_none_not_rejected(self):
        real = mcp_client.mcp_call
        mcp_client.mcp_call = self._fake
        try:
            out, errors = oc.greeks_full(["PARTIAL"], "TEST")
        finally:
            mcp_client.mcp_call = real
        self.assertEqual(errors, [])
        g = out["PARTIAL"]
        self.assertAlmostEqual(g["gamma"], 0.01)
        self.assertIsNone(g["theta"])
        self.assertIsNone(g["vega"])
        self.assertIsNone(g["rho"])
        self.assertEqual(g["available"], {
            "gamma": True, "theta": False, "vega": False, "rho": False})

    def test_legacy_greeks_tuple_unchanged(self):
        real = mcp_client.mcp_call
        mcp_client.mcp_call = self._fake
        try:
            out, errors = oc.greeks(["P1"], "TEST", signed=True)
        finally:
            mcp_client.mcp_call = real
        self.assertEqual(errors, [])
        self.assertEqual(out["P1"], (-0.20, 0.28))


class TestAggregateGreeks(unittest.TestCase):
    def test_signed_portfolio_aggregation(self):
        positions = [
            {"quantity": 2, "delta": 0.30, "gamma": 0.01,
             "theta": -0.05, "vega": 0.10, "rho": 0.01},
            {"quantity": -1, "delta": -0.20, "gamma": 0.02,
             "theta": -0.03, "vega": 0.15, "rho": -0.01},
        ]
        agg = oc.aggregate_greeks(positions)
        self.assertAlmostEqual(agg["delta"], 0.80)
        self.assertAlmostEqual(agg["gamma"], 0.0)
        self.assertAlmostEqual(agg["theta"], -0.07)
        self.assertAlmostEqual(agg["vega"], 0.05)
        self.assertAlmostEqual(agg["rho"], 0.03)
        self.assertTrue(all(agg["available"].values()))

    def test_missing_metrics_do_not_zero_valid_totals(self):
        positions = [
            {"quantity": 1, "delta": 0.25, "gamma": 0.01},
            {"quantity": 1, "delta": 0.15},
        ]
        agg = oc.aggregate_greeks(positions)
        self.assertAlmostEqual(agg["delta"], 0.40)
        self.assertAlmostEqual(agg["gamma"], 0.01)
        self.assertIsNone(agg["theta"])
        self.assertIsNone(agg["vega"])
        self.assertIsNone(agg["rho"])
        self.assertTrue(agg["available"]["gamma"])
        self.assertFalse(agg["available"]["theta"])

    def test_empty_positions(self):
        agg = oc.aggregate_greeks([])
        self.assertIsNone(agg["delta"])
        self.assertFalse(agg["available"]["delta"])
        self.assertEqual(agg["positions_with_greeks"], 0)


if __name__ == "__main__":
    unittest.main()
