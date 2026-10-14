"""Tests for cross_stock.py (pairs / rotation / dispersion screening)."""
import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "src"))

import random
import unittest
from datetime import date

import cross_stock as cs

TODAY = date(2026, 1, 2)
EXP = "2026-02-20"


def series(seed, n=60, drift=0.0, base=None):
    rnd = random.Random(seed)
    base = base or [rnd.gauss(0, 0.01) for _ in range(n)]
    return base


def prices(rets, start=100.0):
    p = [start]
    for r in rets:
        p.append(p[-1] * (1 + r))
    return p


def mkdata(corr_noise=0.002, n=60):
    rnd = random.Random(1)
    common = [rnd.gauss(0, 0.01) for _ in range(n)]
    ra = [c + rnd.gauss(0, corr_noise) for c in common]
    rb = [c + rnd.gauss(0, corr_noise) for c in common]
    return {"A": {"price": 100.0, "prices": prices(ra), "beta": 1.0},
            "B": {"price": 50.0, "prices": prices(rb, 50.0), "beta": 1.0}}


def stock_pair(data, qa=100, ratio=1.0):
    qb = cs.size_hedge_shares(100.0, 50.0, qa, ratio)
    return [dict(underlying="A", kind="stock", side=1, qty=qa),
            dict(underlying="B", kind="stock", side=-1, qty=qb)]


class T(unittest.TestCase):
    def test_hedge_ratio_and_sizing(self):
        ra = [0.02, -0.01, 0.03, 0.0, 0.01]
        rb = [0.01, -0.005, 0.015, 0.0, 0.005]
        self.assertAlmostEqual(cs.hedge_ratio(ra, rb), 2.0)
        self.assertAlmostEqual(cs.correlation(ra, rb), 1.0)
        # $10,000 of A at 100, ratio 2 -> $20,000 of B at 50 = 400 shares
        self.assertEqual(cs.size_hedge_shares(100, 50, 100, 2.0), 400)
        self.assertIsNone(cs.hedge_ratio([1, 2, 3], [1, 1, 1]))

    def test_pair_accepts_and_delta_neutral(self):
        d = mkdata()
        r = cs.evaluate_structure("pair", d, stock_pair(d), today=TODAY)
        self.assertTrue(r["accepted"], r["reasons"])
        self.assertAlmostEqual(r["metrics"]["net_dollar_delta"], 0.0)
        self.assertGreater(r["metrics"]["correlation"], 0.9)
        self.assertAlmostEqual(r["metrics"]["concentration_pct"], 0.5)
        self.assertIn("portfolio_variance", r["metrics"])
        self.assertEqual(len(r["legs"]), 2)

    def test_not_delta_neutral_rejected(self):
        d = mkdata()
        legs = stock_pair(d)
        legs[1]["qty"] = 100  # $5k short vs $10k long
        r = cs.evaluate_structure("pair", d, legs, today=TODAY)
        self.assertIn("net_delta:not_neutral", r["reasons"])

    def test_correlation_gate(self):
        d = mkdata()
        rnd = random.Random(9)
        d["B"]["prices"] = prices([rnd.gauss(0, 0.01) for _ in range(60)], 50.0)
        r = cs.evaluate_structure("pair", d, stock_pair(d), today=TODAY)
        self.assertIn("correlation:below_min", r["reasons"])
        g = dict(cs.cfg(), min_correlation=0.0)
        r = cs.evaluate_structure("pair", d, stock_pair(d), g, TODAY)
        self.assertNotIn("correlation:below_min", r["reasons"])

    def test_invalid_pairs(self):
        d = mkdata()
        same = [dict(underlying="A", kind="stock", side=1, qty=10),
                dict(underlying="A", kind="stock", side=-1, qty=10)]
        r = cs.evaluate_structure("pair", d, same, today=TODAY)
        self.assertTrue(any(x.startswith("invalid_pair") for x in r["reasons"]))
        r = cs.evaluate_structure("pair", d, stock_pair(d)[:1], today=TODAY)
        self.assertTrue(any(x.startswith("invalid_pair") for x in r["reasons"]))
        r = cs.evaluate_structure("bogus", d, stock_pair(d), today=TODAY)
        self.assertEqual(r["reasons"], ["invalid_structure"])
        legs = stock_pair(d)
        legs[1]["qty"] = 0
        r = cs.evaluate_structure("pair", d, legs, today=TODAY)
        self.assertIn("invalid_leg", r["reasons"])
        legs = stock_pair(d)
        legs[1]["underlying"] = "ZZZ"
        r = cs.evaluate_structure("pair", d, legs, today=TODAY)
        self.assertIn("missing_data:underlying:ZZZ", r["reasons"])

    def test_missing_data(self):
        d = mkdata()
        d["B"]["prices"] = d["B"]["prices"][:10]
        r = cs.evaluate_structure("pair", d, stock_pair(d), today=TODAY)
        self.assertIn("missing_data:returns:B", r["reasons"])
        d = mkdata()
        d["A"]["price"] = None
        r = cs.evaluate_structure("pair", d, stock_pair(d), today=TODAY)
        self.assertIn("missing_data:price:A", r["reasons"])
        d = mkdata()
        del d["A"]["beta"]
        r = cs.evaluate_structure("pair", d, stock_pair(d), today=TODAY)
        self.assertIn("missing_data:beta", r["reasons"])

    def test_concentration_and_beta_gates(self):
        d = mkdata()
        d["A"]["beta"] = 2.0
        d["B"]["beta"] = 0.2
        r = cs.evaluate_structure("pair", d, stock_pair(d), today=TODAY)
        self.assertIn("beta:exposure_exceeds_max", r["reasons"])
        g = dict(cs.cfg(), max_concentration_pct=0.4)
        r = cs.evaluate_structure("pair", mkdata(), stock_pair(d), g, TODAY)
        self.assertIn("concentration:exceeds_max", r["reasons"])

    def sector_rotation_legs(self, oi=100, bid=1.0, ask=1.1):
        q = dict(bid=bid, ask=ask, open_interest=oi)
        a = cs.vertical_spread_legs("A", "call", 1, 100, 105, EXP, 1, 0.5, 0.3, q, q)
        b = cs.vertical_spread_legs("B", "put", -1, 50, 47, EXP, 2, -0.5, -0.3, q, q)
        return a + b

    def test_sector_rotation_option_verticals(self):
        d = mkdata()
        legs = self.sector_rotation_legs()
        r = cs.evaluate_structure("sector_rotation", d, legs, today=TODAY)
        # A: long 0.5c -short 0.3c = +0.2*100*100=+2000; B: short vertical of puts:
        # side -1 -> short 50p(-0.5) = +0.5*2*100*50... verify numbers are reported
        self.assertEqual(len(r["legs"]), 4)
        self.assertTrue(all(l["expiration"] == EXP for l in r["legs"]))
        self.assertAlmostEqual(r["metrics"]["exposure_by_underlying"]["A"], 2000.0)

    def test_option_liquidity_and_expired(self):
        d = mkdata()
        r = cs.evaluate_structure("sector_rotation", d,
                                  self.sector_rotation_legs(oi=1), today=TODAY)
        self.assertIn("liquidity:open_interest", r["reasons"])
        r = cs.evaluate_structure("sector_rotation", d,
                                  self.sector_rotation_legs(bid=0.1, ask=1.0), today=TODAY)
        self.assertIn("liquidity:wide_spread", r["reasons"])
        r = cs.evaluate_structure("sector_rotation", d, self.sector_rotation_legs(),
                                  today=date(2026, 3, 1))
        self.assertIn("invalid_leg:expired", r["reasons"])
        legs = self.sector_rotation_legs()
        del legs[0]["bid"]
        r = cs.evaluate_structure("sector_rotation", d, legs, today=TODAY)
        self.assertIn("missing_data:option_quote", r["reasons"])
        legs = self.sector_rotation_legs()
        legs[0]["strike"] = legs[1]["strike"]
        r = cs.evaluate_structure("sector_rotation", d, legs, today=TODAY)
        self.assertIn("invalid_leg:duplicate_strike", r["reasons"])

    def test_dispersion(self):
        rnd = random.Random(3)
        common = [rnd.gauss(0, 0.01) for _ in range(60)]
        mk = lambda: prices([c + rnd.gauss(0, 0.003) for c in common])
        d = {"IDX": {"price": 100.0, "prices": prices(common), "beta": 1.0, "role": "index"},
             "C1": {"price": 100.0, "prices": mk(), "beta": 1.0},
             "C2": {"price": 100.0, "prices": mk(), "beta": 1.0}}
        legs = [dict(underlying="IDX", kind="stock", side=-1, qty=200),
                dict(underlying="C1", kind="stock", side=1, qty=100),
                dict(underlying="C2", kind="stock", side=1, qty=100)]
        g = dict(cs.cfg(), max_concentration_pct=0.6)
        r = cs.evaluate_structure("dispersion", d, legs, g, TODAY)
        self.assertTrue(r["accepted"], r["reasons"])
        self.assertAlmostEqual(r["metrics"]["net_dollar_delta"], 0.0)
        self.assertEqual(set(r["metrics"]["hedge_ratio"]), {"C1", "C2"})
        del d["IDX"]["role"]
        r = cs.evaluate_structure("dispersion", d, legs, g, TODAY)
        self.assertTrue(any("dispersion_requires_index" in x for x in r["reasons"]))

    def test_screen_and_format(self):
        d = mkdata()
        acc, rej = cs.screen_structures(
            [dict(structure="pair", underlyings=d, legs=stock_pair(d)),
             dict(structure="pair", underlyings=d, legs=stock_pair(d)[:1])], None, TODAY)
        self.assertEqual((len(acc), len(rej)), (1, 1))
        self.assertIn("ACCEPT", cs.format_record(acc[0]))
        self.assertIn("reasons", cs.format_record(rej[0]))


if __name__ == "__main__":
    unittest.main()
