"""
Tests for src/iv_premium_screener.py.

Tests IV solver and DTE window logic (no network calls).
"""

import os
import sys
import unittest

os.environ.setdefault("PUBLIC_ACCOUNT_ID", "test-dummy")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import iv_premium_screener as ivp


class TestImpliedVolatility(unittest.TestCase):
    def test_atm_put_reasonable_iv(self):
        iv = ivp.implied_volatility(
            "put", S=100, K=100, T=30/365, r=0.045, market_price=2.50)
        self.assertIsNotNone(iv)
        self.assertGreater(iv, 0.10)
        self.assertLess(iv, 0.50)

    def test_higher_price_higher_iv(self):
        iv1 = ivp.implied_volatility(
            "put", S=100, K=100, T=30/365, r=0.045, market_price=2.0)
        iv2 = ivp.implied_volatility(
            "put", S=100, K=100, T=30/365, r=0.045, market_price=4.0)
        self.assertLess(iv1, iv2)

    def test_call_iv(self):
        iv = ivp.implied_volatility(
            "call", S=100, K=100, T=30/365, r=0.045, market_price=2.50)
        self.assertIsNotNone(iv)
        self.assertGreater(iv, 0)

    def test_invalid_inputs_return_none(self):
        self.assertIsNone(ivp.implied_volatility(
            "put", S=0, K=100, T=0.1, r=0.045, market_price=2.0))
        self.assertIsNone(ivp.implied_volatility(
            "put", S=100, K=100, T=0, r=0.045, market_price=2.0))
        self.assertIsNone(ivp.implied_volatility(
            "put", S=100, K=100, T=0.1, r=0.045, market_price=0))

    def test_roundtrip(self):
        # Price at known IV, then solve back
        from options_math import black_scholes
        true_iv = 0.30
        px = black_scholes(100, 95, 45/365, 0.045, true_iv,
                           option_type="put")["price"]
        solved = ivp.implied_volatility(
            "put", S=100, K=95, T=45/365, r=0.045, market_price=px)
        self.assertAlmostEqual(solved, true_iv, places=3)


class TestDteWindows(unittest.TestCase):
    def test_windows_defined(self):
        self.assertIn("1M", ivp.DTE_WINDOWS)
        self.assertIn("2M", ivp.DTE_WINDOWS)
        self.assertIn("3M", ivp.DTE_WINDOWS)

    def test_windows_cover_1_3_months(self):
        w1 = ivp.DTE_WINDOWS["1M"]
        w3 = ivp.DTE_WINDOWS["3M"]
        self.assertLess(w1[0], 45)   # 1M starts before 45 DTE
        self.assertGreater(w3[1], 75)  # 3M extends past 75 DTE


if __name__ == "__main__":
    unittest.main()
