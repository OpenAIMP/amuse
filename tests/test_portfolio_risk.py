import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)),
                                  "..", "src"))

import unittest

from options_math import black_scholes
from portfolio_risk import analyze_portfolio


class TestPortfolioRiskGreeks(unittest.TestCase):
    def test_analyze_portfolio_aggregates_all_five_greeks(self):
        now = "2026-10-13T12:00:00Z"
        expiry = "2027-01-15"
        ledger = {
            "updated_at": now,
            "positions": [{
                "status": "open", "underlying": "XYZ", "contracts": 2,
                "multiplier": 100,
                "legs": [
                    {"expiry": expiry, "strike": 100, "type": "call",
                     "side": "long"},
                    {"expiry": expiry, "strike": 100, "type": "put",
                     "side": "short"},
                ],
            }],
        }
        market = {
            "schema_version": 1, "source": "test", "asof": now,
            "risk_free_rate": 0.04, "risk_free_rate_asof": now,
            "underlyings": {
                "XYZ": {"spot": 100, "spot_asof": now, "iv": 0.25,
                        "iv_asof": now},
            },
        }
        result = analyze_portfolio(ledger, market, now=now)
        days = (unittest.mock if False else None)
        del days
        from datetime import date
        t = (date.fromisoformat(expiry) - date.fromisoformat(now[:10])).days / 365
        call = black_scholes(100, 100, t, 0.04, 0.25, "call")
        put = black_scholes(100, 100, t, 0.04, 0.25, "put")
        self.assertTrue(result["complete"])
        self.assertEqual(set(result["greeks"]), {
            "delta", "gamma", "theta", "vega", "rho"})
        for key in result["greeks"]:
            self.assertAlmostEqual(
                result["greeks"][key], round((call[key] - put[key]) * 200, 6))


if __name__ == "__main__":
    unittest.main()
