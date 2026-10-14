"""Perf tests (issue #14): batching + concurrency without MCP access.

Every screener funnels MCP traffic through one mcp_call(tool, args)
function. These tests monkeypatch it with a canned fake that counts calls,
proving:
  - premarket quotes are batched (one get_quotes for N names, not N calls)
  - screen_one honors a provided quote_map (zero quote calls)
  - threaded fan-out returns results identical to sequential runs
"""
import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)),
                                  "..", "src"))
# Screener modules require PUBLIC_ACCOUNT_ID at import time (#23); unit
# tests never hit the API, so a dummy value suffices.
_os.environ.setdefault("PUBLIC_ACCOUNT_ID", "TEST")


import concurrent.futures
import json
import unittest
from datetime import date, timedelta

import premarket_screen as dt
import mcp_client
from market_data import quotes as batch_quotes


def _daily_bars(n=60, close=100.0, drift=0.0):
    import math as _m
    base = date.today() - timedelta(days=n + 10)
    out = []
    for i in range(n):
        # gentle oscillation around an uptrend: mixed up/down days keep
        # RSI mid-range instead of pegging at 0/100
        c = close * (1 + drift) ** i + 4.0 * _m.sin(i / 3.0)
        out.append({"timestamp": (base + timedelta(days=i)).isoformat(),
                    "close": c, "high": c * 1.01, "low": c * 0.99,
                    "volume": 1_000_000})
    return out


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
        self._real = mcp_client.mcp_call
        mcp_client.mcp_call = self.fake

    def tearDown(self):
        mcp_client.mcp_call = self._real

    def test_quotes_for_batches(self):
        m = batch_quotes(["AAA", "BBB", "CCC"], "TEST")
        self.assertEqual(m, {"AAA": 100.0, "BBB": 50.0, "CCC": 200.0})
        self.assertEqual(self.fake.count("get_quotes"), 1)

    def test_screen_one_uses_quote_map(self):
        res, reasons = dt.screen_one("AAA", {"AAA": 103.0})
        self.assertEqual(self.fake.count("get_quotes"), 0)
        self.assertAlmostEqual(res["price"], 103.0)
        # gap = 103/100 - 1 = 3% >= 2% min; rel vol = 1.2M/1M = 1.2 < 1.5
        self.assertIn("regular-session volume below time-normalized minimum", reasons)

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
        real = mcp_client.mcp_call
        mcp_client.mcp_call = fake
        try:
            qm = batch_quotes(names, "TEST")

            def safe(sym):
                return (sym,) + dt.screen_one(sym, qm)

            with concurrent.futures.ThreadPoolExecutor(
                    max_workers=workers) as ex:
                return sorted(ex.map(safe, names), key=lambda r: r[0])
        finally:
            mcp_client.mcp_call = real

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

        self._real = mcp_client.mcp_call
        mcp_client.mcp_call = fake_call

    def tearDown(self):
        mcp_client.mcp_call = self._real

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


class TestStockRegression(unittest.TestCase):
    """Issue #15: rsi local shadowed rsi() -> UnboundLocalError on every name.

    screen_stock with a mocked mcp_call must never return an
    "evaluation error" reason.
    """

    def test_screen_stock_no_evaluation_error(self):
        import stock_screener as st
        real = mcp_client.mcp_call

        def fake(tool, args):
            if args.get("aggregation") == "ONE_DAY":
                return {"regularMarket": {"bars": _daily_bars(210, drift=0.001)}}
            return {"regularMarket": {
                "bars": _intraday_bars(), "expectedBars": 78}}

        mcp_client.mcp_call = fake
        try:
            sym, ok, metrics, reasons = st.screen_stock("AAA")
        finally:
            mcp_client.mcp_call = real
        for r in reasons:
            self.assertFalse(r.startswith("evaluation error"),
                             f"regression: {r}")
        # mock data is constructed to pass the gates
        self.assertTrue(ok, reasons)
        self.assertIn("rsi14", metrics)
        self.assertIn("score", metrics)


class TestIndicators(unittest.TestCase):
    """Issue #17: pure-function tests for ema/mACD/cross (no MCP)."""

    def test_ema_flat(self):
        import stock_screener as st
        self.assertAlmostEqual(st.ema([100.0] * 60, 50), 100.0)

    def test_ema_follows_trend(self):
        import stock_screener as st
        vals = [100.0 + i for i in range(60)]
        e = st.ema(vals, 50)
        self.assertLess(e, vals[-1])
        self.assertGreater(e, vals[0])

    def test_ema_insufficient(self):
        import stock_screener as st
        self.assertIsNone(st.ema([1.0] * 10, 50))

    def test_macd_flat(self):
        import stock_screener as st
        line, _sig, hist = st.macd([100.0] * 60)
        self.assertAlmostEqual(line, 0.0)
        self.assertAlmostEqual(hist, 0.0)

    def test_macd_uptrend_positive_hist(self):
        import stock_screener as st
        vals = [100.0 + i * 0.5 for i in range(60)]
        _line, _sig, hist = st.macd(vals)
        self.assertGreater(hist, 0)

    def test_macd_insufficient(self):
        import stock_screener as st
        self.assertEqual(st.macd([100.0] * 20), (None, None, None))

    def test_golden_cross(self):
        import stock_screener as st
        closes = [120.0] * 200 + [100.0] * 30 + [130.0] * 40
        self.assertEqual(st.sma_cross(closes, 50, 200, 20), "golden")

    def test_death_cross(self):
        import stock_screener as st
        closes = [100.0] * 200 + [120.0] * 30 + [90.0] * 40
        self.assertEqual(st.sma_cross(closes, 50, 200, 20), "death")

    def test_no_cross(self):
        import stock_screener as st
        closes = [100.0] * 245
        self.assertIsNone(st.sma_cross(closes, 50, 200, 20))


class TestRenderSmoke(unittest.TestCase):
    """Issue #17 follow-up: render_report.py must at least import and render.

    A SyntaxError in the renderer once broke two scheduled jobs while the
    whole unit suite stayed green (nothing imported the renderer)."""

    def _record(self, **kw):
        rec = {
            "symbol": "TST", "price": 100.0, "rsi14": 55.0, "score": 26.3,
            "vs_sma50_pct": 3.2, "off_52w_high_pct": 8.5,
            "atr_pct": 2.1, "vol_ratio": 1.2,
            "indicators": {
                "bollinger": {"pct_b": 0.6, "bandwidth_pct": 8.0,
                              "squeeze": False},
                "vwap": {"anchored_dist_pct": 2.0},
                "structure": {"trend": "UP"},
                "trend": {"cross": "golden"},
                "macd": {"hist": 0.5},
            },
        }
        rec.update(kw)
        return rec

    def test_imports(self):
        import render_report  # noqa: F401 — must not SyntaxError

    def test_stock_section_renders(self):
        import render_report as rr
        html = rr.stock_section({"passing": [self._record()]})
        self.assertIn("TST", html)
        self.assertIn("GC", html)          # golden-cross badge
        self.assertIn("+0.50", html)       # macd hist cell
        self.assertIn("/40", html)
        self.assertIn("3.2%", html)        # vs SMA50
        self.assertIn("8.5%", html)        # off 52w high
        self.assertIn("2.1<", html)         # ATR%
        self.assertIn("1.20", html)        # vol ratio

    def test_stock_section_empty(self):
        import render_report as rr
        html = rr.stock_section({"passing": []})
        self.assertIn("No qualifiers", html)

    def test_stock_section_missing_indicators(self):
        import render_report as rr
        rec = self._record()
        del rec["indicators"]["trend"]
        del rec["indicators"]["macd"]
        html = rr.stock_section({"passing": [rec]})
        self.assertIn("TST", html)  # must not crash on absent fields


    def test_squeeze_fires_at_125d_minimum(self):
        import random
        import stock_screener as st
        random.seed(7)
        closes = [100 + random.uniform(-8, 8) for _ in range(200)]
        closes += [105 + random.uniform(-1, 1) * 0.1 * (1 - i / 30)
                   for i in range(30)]
        bb = st.bollinger(closes)
        self.assertTrue(bb["squeeze"])

    def test_squeeze_false_when_not_minimum(self):
        import random
        import stock_screener as st
        random.seed(7)
        closes = [100 + i * 0.1 + random.uniform(-2, 2) for i in range(230)]
        self.assertFalse(st.bollinger(closes)["squeeze"])


class TestTapeReadouts(unittest.TestCase):
    """Issue #18: gap / momentum / value / bias helpers."""

    def test_gap_up_down_flat(self):
        import stock_screener as st
        mk = lambda o, pc: [{"close": pc, "high": pc, "low": pc, "volume": 1,
                          "open": None},
                         {"close": 100, "high": 100, "low": 100,
                          "volume": 1, "open": o}]
        self.assertEqual(st.gap_label(st.gap_pct(mk(103, 100))), "gap up")
        self.assertEqual(st.gap_label(st.gap_pct(mk(97, 100))), "gap down")
        self.assertEqual(st.gap_label(st.gap_pct(mk(100.5, 100))), "no gap")

    def test_gap_unknown_without_open(self):
        import stock_screener as st
        bars = [{"close": 100, "high": 100, "low": 100, "volume": 1,
             "open": None},
            {"close": 101, "high": 101, "low": 101, "volume": 1,
             "open": None}]
        self.assertIsNone(st.gap_pct(bars))
        self.assertIsNone(st.gap_label(None))

    def test_rsi_state(self):
        import stock_screener as st
        self.assertEqual(st.rsi_state(25), "oversold")
        self.assertEqual(st.rsi_state(75), "overbought")
        self.assertEqual(st.rsi_state(55), "neutral")
        self.assertIsNone(st.rsi_state(None))

    def test_value_position_and_label(self):
        import stock_screener as st
        self.assertAlmostEqual(st.value_position(110, 100, 200), 10.0)
        self.assertEqual(st.value_label(10.0), "undervalued")
        self.assertEqual(st.value_label(90.0), "overvalued")
        self.assertEqual(st.value_label(50.0), "mid-range")
        self.assertIsNone(st.value_position(110, 200, 200))  # hi <= lo

    def test_bias_votes_and_label(self):
        import stock_screener as st
        v, n = st.bias_votes(110, 100, 90, 1.5, 60, "UP")
        self.assertEqual((v, n), (6, 6))
        self.assertEqual(st.bias_label(6), "bullish")
        self.assertEqual(st.bias_label(4), "bullish")
        self.assertEqual(st.bias_label(3), "neutral")
        self.assertEqual(st.bias_label(2), "bearish")
        self.assertEqual(st.bias_label(0), "bearish")

    def test_evaluate_carries_tape(self):
        import stock_screener as st
        # Mock session_vwap to avoid MCP call in CI
        real_svwap = st.session_vwap
        st.session_vwap = lambda sym: None
        try:
            bars = [{"close": 100 + i * 0.1, "high": 101 + i * 0.1,
                     "low": 99 + i * 0.1, "volume": 1_000_000,
                     "open": 100 + i * 0.1} for i in range(210)]
            ok, m, _ = st.evaluate("T", bars)
        finally:
            st.session_vwap = real_svwap
        tape = m["indicators"]["tape"]
        for k in ("gap_pct", "gap", "momentum", "value_pct", "value",
                  "bias_votes", "bias"):
            self.assertIn(k, tape)


if __name__ == "__main__":
    unittest.main(verbosity=2)