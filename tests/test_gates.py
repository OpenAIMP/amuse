"""Tests for gates.py: subset-YAML parsing, defaults, merging, overrides."""
import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)),
                                  "..", "src"))


import os
import tempfile
import unittest

import gates


class TestParse(unittest.TestCase):
    def test_basic(self):
        d = gates.parse("spreads:\n  dte_min: 21\n  max_loss: 1000\n")
        self.assertEqual(d, {"spreads": {"dte_min": 21, "max_loss": 1000}})

    def test_types(self):
        d = gates.parse("a:\n  i: 3\n  f: 2.5\n  t: true\n  ff: false\n  n: null\n")
        self.assertEqual(d["a"], {"i": 3, "f": 2.5, "t": True, "ff": False,
                                  "n": None})

    def test_comments_and_blanks(self):
        d = gates.parse("# top\nspreads:  # trailing\n\n  dte_min: 21  # eol\n")
        self.assertEqual(d["spreads"]["dte_min"], 21)

    def test_tabs_rejected(self):
        with self.assertRaises(ValueError):
            gates.parse("spreads:\n\tbad: 1\n")

    def test_bad_indent_rejected(self):
        with self.assertRaises(ValueError):
            gates.parse("spreads:\n   bad: 1\n")

    def test_bad_value_rejected(self):
        with self.assertRaises(ValueError):
            gates.parse("spreads:\n  bad: [1, 2]\n")


class TestLoad(unittest.TestCase):
    def test_defaults_match_yaml(self):
        file_cfg = gates.parse(open(gates.DEFAULT_PATH).read())
        for section, keys in file_cfg.items():
            for k, v in keys.items():
                self.assertEqual(gates.DEFAULTS[section][k], v,
                                 f"{section}.{k} drifted from gates.yaml")

    def test_partial_override_merges(self):
        with tempfile.NamedTemporaryFile("w", suffix=".yaml",
                                         delete=False) as f:
            f.write("spreads:\n  max_loss: 500\n")
            path = f.name
        try:
            g = gates.load(path)
            self.assertEqual(g["spreads"]["max_loss"], 500)
            self.assertEqual(g["spreads"]["dte_min"], 21)  # default kept
            self.assertEqual(g["pmcc"]["max_capital"], 10000)
        finally:
            os.unlink(path)

    def test_missing_file_uses_defaults(self):
        g = gates.load("/tmp/definitely-not-here-12345.yaml")
        self.assertEqual(g["daytrade"]["top_n"], 20)

    def test_ledger_section(self):
        g = gates.load()
        self.assertEqual(g["ledger"]["max_loss_pct"], 0.02)
        self.assertEqual(g["ledger"]["heat_cap_pct"], 0.35)
        self.assertEqual(g["ledger"]["fee_per_contract"], 0.65)

    def test_vol_section(self):
        g = gates.load()
        self.assertEqual(g["vol"]["hv_short"], 20)
        self.assertEqual(g["vol"]["hv_long"], 60)
        self.assertEqual(g["vol"]["ivr_sell"], 50)
        self.assertEqual(g["vol"]["ivr_stand_down"], 25)
        self.assertEqual(g["vol"]["min_iv_history"], 30)


if __name__ == "__main__":
    unittest.main(verbosity=2)
