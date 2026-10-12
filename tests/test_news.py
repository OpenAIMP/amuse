"""Tests for fetch_news.py: Google News RSS parsing (issue #21)."""
import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)),
                                  "..", "src"))

import unittest

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


if __name__ == "__main__":
    unittest.main(verbosity=2)
