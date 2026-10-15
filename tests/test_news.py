"""Tests for fetch_news.py: Google News RSS parsing (issue #21)."""
import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)),
                                  "..", "src"))

import unittest
import json
import tempfile
from unittest import mock
from urllib.error import HTTPError

import fetch_news as fn

SAMPLE_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
<title>NVDA stock - Google News</title>
<item>
<title>Nvidia Stock Surges on AI Demand - Barron's</title>
<link>https://news.google.com/rss/articles/abc123</link>
<pubDate>Mon, 12 Oct 2026 12:00:00 GMT</pubDate>
<source url="https://barrons.com">Barron's</source>
</item>
<item>
<title>Chip stocks mixed premarket</title>
<link>https://news.google.com/rss/articles/def456</link>
<pubDate>Mon, 12 Oct 2026 08:00:00 GMT</pubDate>
<source url="https://cnbc.com">CNBC</source>
</item>
</channel></rss>"""


class TestParseRss(unittest.TestCase):
    def test_parses_items(self):
        heads = fn.parse_rss(SAMPLE_RSS)
        self.assertEqual(len(heads), 2)
        self.assertEqual(heads[0]["source"], "Barron's")
        # " - Source" suffix stripped from title
        self.assertEqual(heads[0]["title"], "Nvidia Stock Surges on AI Demand")
        self.assertTrue(heads[0]["link"].startswith("https://"))
        self.assertIn("2026", heads[0]["published"])

    def test_title_without_source_suffix_kept(self):
        heads = fn.parse_rss(SAMPLE_RSS)
        self.assertEqual(heads[1]["title"], "Chip stocks mixed premarket")

    def test_bad_xml_returns_empty(self):
        self.assertEqual(fn.parse_rss("not xml at all"), [])
        self.assertEqual(fn.parse_rss(""), [])

    def test_items_missing_link_skipped(self):
        rss = ('<rss><channel><item><title>No link here</title>'
               '</item></channel></rss>')
        self.assertEqual(fn.parse_rss(rss), [])

    def test_dedupe(self):
        h = {"title": "Same Title", "link": "x", "published": "", "source": ""}
        h2 = {"title": "same title", "link": "y", "published": "", "source": ""}
        h3 = {"title": "Different", "link": "z", "published": "", "source": ""}
        self.assertEqual(len(fn.dedupe([h, h2, h3])), 2)


class TestNewsFetching(unittest.TestCase):
    def test_symbols_from_reports_collects_only_screened_candidates(self):
        with tempfile.TemporaryDirectory() as tmp:
            stock = _os.path.join(tmp, "stock.json")
            spreads = _os.path.join(tmp, "spreads.json")
            with open(stock, "w", encoding="utf-8") as f:
                json.dump({"passing": [{"symbol": "NVDA"}, {"symbol": " msft "}]}, f)
            with open(spreads, "w", encoding="utf-8") as f:
                json.dump({"results": {"bull_puts": {"NVDA": {}, "AMD": {}}}}, f)

            self.assertEqual(fn.symbols_from_reports([stock, spreads, "missing.json"]),
                             ["NVDA", "MSFT", "AMD"])

    def test_fetch_retries_temporary_service_unavailable(self):
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = SAMPLE_RSS.encode()
        temporary = HTTPError("https://news.google.com", 503,
                              "Service Unavailable", {}, None)
        with mock.patch.object(fn.urllib.request, "urlopen",
                               side_effect=[temporary, response]), \
                mock.patch.object(fn.time, "sleep") as sleep:
            headlines = fn.fetch("NVDA stock", retries=1)

        self.assertEqual(len(headlines), 2)
        sleep.assert_called_once_with(1)

    def test_fetch_returns_empty_after_retryable_failures(self):
        temporary = HTTPError("https://news.google.com", 503,
                              "Service Unavailable", {}, None)
        with mock.patch.object(fn.urllib.request, "urlopen",
                               side_effect=temporary), \
                mock.patch.object(fn.time, "sleep"):
            self.assertEqual(fn.fetch("NVDA stock", retries=1), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
