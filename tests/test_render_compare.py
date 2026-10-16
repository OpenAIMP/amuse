"""
Tests for src/render_compare.py (#114).

Tests HTML rendering with synthetic data (no network calls).
Per AGENTS.md: renderer changes must be verified by EXECUTING the renderer.
"""

import os
import sys
import unittest

os.environ.setdefault("PUBLIC_ACCOUNT_ID", "test-dummy")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import render_compare


def _metrics(**overrides):
    base = {
        "symbol": "TEST", "price": 100.0,
        "ret_1d_pct": 1.0, "ret_30d_pct": 5.0, "ytd_ret_pct": 20.0,
        "score": 25.0, "verdict": "Go for it", "trend": "UP",
        "rsi14": 55.0, "earnings_date": None,
    }
    base.update(overrides)
    return base


def _results():
    return {
        "bullish": [
            ("AAA", 30.0, _metrics(symbol="AAA", price=100.0)),
            ("BBB", 25.0, _metrics(symbol="BBB", price=200.0, trend="RNG")),
        ],
        "bearish": [
            ("CCC", 28.0, _metrics(symbol="CCC", price=50.0, trend="DN")),
        ],
        "neutral": [],
        "directional": [
            ("AAA", 30.0, _metrics(symbol="AAA", price=100.0)),
        ],
    }


class TestRenderPage(unittest.TestCase):
    def test_renders_valid_html(self):
        html = render_compare.render_page("test_uni", _results(), {})
        self.assertIn("<!DOCTYPE html>", html)
        self.assertIn("</html>", html)
        self.assertIn("test_uni", html)

    def test_has_view_tabs(self):
        html = render_compare.render_page("test_uni", _results(), {})
        for view in ("bullish", "bearish", "neutral", "directional"):
            self.assertIn(f'data-view="{view}"', html)

    def test_has_decision_logic_section(self):
        html = render_compare.render_page("test_uni", _results(), {})
        self.assertIn("How each view scores", html)
        self.assertIn("Bullish", html)
        self.assertIn("pullback entries", html)
        self.assertIn("overbought", html)
        self.assertIn("Bearish", html)
        self.assertIn("oversold", html)
        self.assertIn("Neutral", html)
        self.assertIn("range-bound", html)
        self.assertIn("Directional", html)
        self.assertIn("stronger of the bullish and bearish", html)

    def test_has_leaderboard_tables(self):
        html = render_compare.render_page("test_uni", _results(), {})
        self.assertIn("AAA", html)
        self.assertIn("BBB", html)
        self.assertIn("$100.00", html)

    def test_has_backlink(self):
        html = render_compare.render_page("test_uni", _results(), {})
        self.assertIn('href="index.html"', html)

    def test_has_disclaimer(self):
        html = render_compare.render_page("test_uni", _results(), {})
        self.assertIn("Not investment advice", html)

    def test_errors_shown(self):
        html = render_compare.render_page(
            "test_uni", _results(), {"BAD": "data error"})
        self.assertIn("BAD", html)
        self.assertIn("Skipped 1", html)

    def test_trend_badges(self):
        html = render_compare.render_page("test_uni", _results(), {})
        # UP trend should get green badge
        self.assertIn("var(--green)", html)

    def test_tab_switching_js(self):
        html = render_compare.render_page("test_uni", _results(), {})
        self.assertIn("view-tab", html)
        self.assertIn("addEventListener", html)


class TestRenderHubLink(unittest.TestCase):
    def test_hub_links_to_compare(self):
        # Verify render_hub.py includes the compare.html link
        hub_path = os.path.join(
            os.path.dirname(__file__), "..", "src", "render_hub.py")
        with open(hub_path) as f:
            content = f.read()
        self.assertIn("compare.html", content)
        self.assertIn("Setup leaderboard", content)


if __name__ == "__main__":
    unittest.main()
