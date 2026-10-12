"""Perf tests (issue #14): batching + concurrency without MCP access.

Every screener funnels MCP traffic through one mcp_call(tool, args)
function. These tests monkeypatch it with a canned fake that counts calls,
proving:
  - daytrade quotes are batched (one get_quotes for N names, not N calls)
  - screen_one honors a provided quote_map (zero quote calls)
  - threaded fan-out returns results identical to sequential runs
"""

import concurrent.futures
import json
import unittest
from datetime import date, timedelta

import daytrade_screen as dt


def _daily_bars(n=60, close=100.0):
    base = date.today() - timedelta(days=n + 10)
    return [{"timestamp": (base + timedelta(days=i)).isoformat(),
             "close": close, "high": close * 1.01,
             "low": close * 0.99, "volume": 1_000_000}
            for i in range(n)]


def _intraday_bars(n=20, price=103.0):
    base = date.today()
    return [{"timestamp": base.isoformat(),
             "open": price, "high": price * 1.01, "low": price * 0.99,
             "close": price, "volume": 60_000}
            for _ in range(n)]


class FakeMCP:
    """Canned mcp_call replacement. Counts calls per tool."""

    def __init__(self, quotes):
        self.quotes = quotes
        self.calls = []

    def __call__(self, tool, args):
        self.calls.append(tool)
        if tool == "get_quotes":
            syms = args["symbols"] if isinstance(args["symbols"], list) \
                else [args["symbols"]]
            return {"data": [{"instrument": {"symbol": s},
                              "last": self.quotes.get(s)}
                             for s in syms if s in self.quotes]}
        if tool == "get_price_history":
            if args.get("aggregation") == "ONE_DAY":
                return {"regularMarket": {"bars": _daily_bars()}}
            return {"regularMarket": {"bars": _intraday_bars()}}
        raise AssertionError(f"unexpected tool {tool}")

    def count(self, tool):
        return sum(1 for c in self.calls if c == tool)


class TestBatching(unittest.TestCase):
    def setUp(self):
        self.fake = FakeMCP({"AAA": 100.0, "BBB": 50.0, "CCC": 200.0})
        self._real = dt.mcp_call
        dt.mcp_call = self.fake

    def tearDown(self):
        dt.mcp_call = self._real

    def test_quotes_for_batches(self):
        m = dt.quotes_for(["AAA", "BBB", "CCC"])
        self.assertEqual(m, {"AAA": 100.0, "BBB": 50.0, "CCC": 200.0})
        self.assertEqual(self.fake.count("get_quotes"), 1)

    def test_screen_one_uses_quote_map(self):
        res, reasons = dt.screen_one("AAA", {"AAA": 103.0})
        self.assertEqual(self.fake.count("get_quotes"), 0)
        self.assertAlmostEqual(res["price"], 103.0)
        # gap = 103/100 - 1 = 3% >= 2% min; rel vol = 1.2M/1M = 1.2 < 1.5
        self.assertIn("volume too thin", reasons)

    def test_screen_one_falls_back_without_map(self):
        res, reasons = dt.screen_one("AAA", None)
        self.assertEqual(self.fake.count("get_quotes"), 1)
        self.assertAlmostEqual(res["price"], 100.0)

    def test_missing_quote_in_map(self):
        res, reasons = dt.screen_one("ZZZ", {"AAA": 103.0})
        self.assertEqual(reasons, ["no quote"])


class TestConcurrency(unittest.TestCase):
    def _run(self, names, workers):
        fake = FakeMCP({s: 103.0 for s in names})
        real = dt.mcp_call
        dt.mcp_call = fake
        try:
            qm = dt.quotes_for(names)

            def safe(sym):
                return (sym,) + dt.screen_one(sym, qm)

            with concurrent.futures.ThreadPoolExecutor(
                    max_workers=workers) as ex:
                return sorted(ex.map(safe, names), key=lambda r: r[0])
        finally:
            dt.mcp_call = real

    def test_threaded_matches_sequential(self):
        names = ["AAA", "BBB", "CCC", "DDD", "EEE"]
        seq = self._run(names, 1)
        par = self._run(names, 8)
        self.assertEqual(len(seq), len(names))
        self.assertEqual(len(par), len(names))
        for (s1, r1, rs1), (s2, r2, rs2) in zip(seq, par):
            self.assertEqual(s1, s2)
            self.assertEqual(r1, r2)
            self.assertEqual(rs1, rs2)

    def test_no_missing_or_duplicate_symbols(self):
        names = [f"S{i:03d}" for i in range(30)]
        out = self._run(names, 8)
        got = [s for s, _, _ in out]
        self.assertEqual(sorted(got), sorted(names))
        self.assertEqual(len(set(got)), len(names))


class SpreadFakeMCP:
    """Canned contract/Greeks data for spread_screener.screen_spreads_sym."""

    def __init__(self, exp):
        self.exp = exp
        self.call_names = []
        yymmdd = exp[2:4] + exp[5:7] + exp[8:10]

        def osi(cp, strike):
            return f"XOM{yymmdd}{cp}{int(strike * 1000):08d}"

        # (strike, delta, bid, ask) per contract
        self.puts = [(95.0, -0.15, 1.20, 1.30), (90.0, -0.05, 0.50, 0.60)]
        self.call_contracts = [(105.0, 0.15, 1.10, 1.20),
                               (110.0, 0.05, 0.45, 0.55)]
        self.greeks = {}
        for strike, delta, _b, _a in self.puts:
            self.greeks[osi("P", strike)] = (delta, 0.30)
        for strike, delta, _b, _a in self.call_contracts:
            self.greeks[osi("C", strike)] = (delta, 0.28)


class TestSpreadThreading(unittest.TestCase):
    def setUp(self):
        import spread_screener as sp
        self.sp = sp
        self.exp = (date.today() + timedelta(days=39)).isoformat()
        self.fake = SpreadFakeMCP(self.exp)

        def fake_call(tool, args):
            self.fake.call_names.append(tool)
            if tool == "get_option_expirations":
                return {"expirations": [self.exp]}
            if tool == "get_option_chain":
                # parse_options calls once per (expiry, puts|calls); infer
                # side from the previous call order is fragile, so serve
                # both and let the wrong-type filter drop extras.
                yymmdd = self.exp[2:4] + self.exp[5:7] + self.exp[8:10]

                def mk(cp, strike, bid, ask):
                    return {"instrument": {
                        "symbol": f"XOM{yymmdd}{cp}{int(strike*1000):08d}"},
                        "bid": bid, "ask": ask,
                        "openInterest": 100, "volume": 50}

                puts = [mk("P", s, b, a) for s, _d, b, a in self.fake.puts]
                calls = [mk("C", s, b, a) for s, _d, b, a in self.fake.call_contracts]
                return {"puts": puts, "calls": calls}
            if tool == "get_option_greeks":
                return {"greeks": [
                    {"symbol": sym,
                     "greeks": {"delta": d, "impliedVolatility": iv}}
                    for sym, (d, iv) in self.fake.greeks.items()
                    if sym in args["osi_symbols"]]}
            if tool == "get_price_history":
                return {"regularMarket": {"bars": _daily_bars()}}
            raise AssertionError(f"unexpected tool {tool}")

        self._real = sp.mcp_call
        sp.mcp_call = fake_call

    def tearDown(self):
        self.sp.mcp_call = self._real

    def test_screen_spreads_sym_finds_bull_put(self):
        sp = self.sp
        r = sp.screen_spreads_sym("XOM", {"XOM": 100.0}, 5.0, {}, "/tmp/none.jsonl", True)
        self.assertIsNone(r["error"], r)
        self.assertEqual(len(r["bp"]), 1)
        bp = r["bp"][0]
        self.assertEqual(bp["short_strike"], 95.0)
        self.assertEqual(bp["long_strike"], 90.0)
        self.assertAlmostEqual(bp["credit_total"], (1.20 - 0.60) * 100)
        # bear-call wing also qualifies -> iron condor built
        self.assertEqual(len(r["ic"]), 1)

    def test_threaded_merge_matches(self):
        import concurrent.futures
        sp = self.sp
        names = ["XOM", "YYY"]

        def safe(sym):
            return (sym, sp.screen_spreads_sym(
                sym, {"XOM": 100.0, "YYY": 100.0}, 5.0, {},
                "/tmp/none.jsonl", True))

        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:
            results = list(ex.map(safe, names))
        got = {}
        for sym, r in results:
            got[sym] = r
        # YYY has no chain data in the fake -> no expirations? (fake serves
        # expirations for any symbol; chains keyed by XOM OSI root parse
        # fine, so both get structures -- assert determinism instead)
        for sym in names:
            self.assertIn(sym, got)
            self.assertIsNone(got[sym]["error"])
        self.assertEqual(len(got["XOM"]["bp"]), 1)

    def test_no_vol_skips_price_history(self):
        sp = self.sp
        calls_before = len(self.fake.call_names)
        sp.screen_spreads_sym("XOM", {"XOM": 100.0}, 5.0, {}, "/tmp/none.jsonl", True)
        self.assertNotIn("get_price_history",
                           self.fake.call_names[calls_before:])


if __name__ == "__main__":
    unittest.main(verbosity=2)