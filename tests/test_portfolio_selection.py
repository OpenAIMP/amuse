import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from portfolio_selection import select_portfolio


def cand(id, under, score, margin=1000, **kw):
    c = {"id": id, "underlying": under, "score": score, "margin": margin,
         "kind": "bull_put", "expiration": "2026-12-18", "greeks": {}}
    c.update(kw)
    return c


def reasons(result):
    return {r["id"]: r["binding_constraint"]["constraint"] for r in result["rejected"]}


class TestPortfolioSelection(unittest.TestCase):
    def test_orders_by_score_and_reports_incremental(self):
        r = select_portfolio([cand("lo", "A", 0.1), cand("hi", "B", 0.3), cand("mid", "C", 0.2)],
                             10000, {"max_positions": 2})
        self.assertEqual([p["id"] for p in r["proposed"]], ["hi", "mid"])
        self.assertEqual(reasons(r), {"lo": "max_positions"})
        self.assertEqual(r["proposed"][0]["incremental"]["margin"], 1000)

    def test_greek_limits(self):
        for g in ("delta", "gamma", "theta", "vega"):
            cs = [cand("a", "A", 2, greeks={g: 60}), cand("b", "B", 1, greeks={g: 60})]
            r = select_portfolio(cs, 10000, {f"max_abs_{g}": 100})
            self.assertEqual(reasons(r), {"b": f"max_abs_{g}"})
        r = select_portfolio([cand("a", "A", 2, greeks={"delta": 60}),
                              cand("b", "B", 1, greeks={"delta": -60})], 10000,
                             {"max_abs_delta": 100})
        self.assertEqual(len(r["proposed"]), 2)

    def test_baseline_counts_toward_greeks(self):
        r = select_portfolio([cand("a", "A", 1, greeks={"vega": 30})], 10000,
                             {"max_abs_vega": 100}, baseline={"vega": 80})
        self.assertEqual(reasons(r), {"a": "max_abs_vega"})

    def test_concentration_limits(self):
        r = select_portfolio([cand("a", "A", 3, expiration="1"), cand("a2", "A", 2, expiration="2"),
                              cand("b", "B", 1, sector="tech"), cand("c", "C", 0.5, sector="tech")],
                             10000, {"max_underlying_pct": 0.15, "max_sector_pct": 0.15})
        self.assertEqual(reasons(r), {"a2": "max_underlying_pct", "c": "max_sector_pct"})

    def test_correlation_limit(self):
        r = select_portfolio([cand("a", "A", 3), cand("b", "B", 2), cand("c", "C", 1)], 10000,
                             {"max_correlated_pct": 0.15},
                             correlations={("A", "B"): 0.9, ("A", "C"): 0.1})
        self.assertEqual(reasons(r), {"b": "max_correlated_pct"})
        self.assertEqual([p["id"] for p in r["proposed"]], ["a", "c"])

    def test_margin_limit(self):
        r = select_portfolio([cand("a", "A", 2, margin=6000), cand("b", "B", 1, margin=5000)],
                             10000, {"max_margin_pct": 0.9})
        self.assertEqual(reasons(r), {"b": "max_margin_pct"})
        self.assertEqual(r["exposure"]["margin"], 6000)

    def test_redundant_candidate_rejected(self):
        r = select_portfolio([cand("a", "A", 2), cand("a2", "A", 1)], 10000)
        self.assertEqual(reasons(r), {"a2": "redundant"})


if __name__ == "__main__":
    unittest.main()
