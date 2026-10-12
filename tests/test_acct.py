"""Regression test for issue #22: empty PUBLIC_ACCOUNT_ID must fall back.

All screeners resolve the account id at import time. The old pattern
`os.environ.get(\"PUBLIC_ACCOUNT_ID\", \"5OI32712\")` only fell back when the
variable was unset; GitHub Actions sets it to empty string (undefined
`vars.PUBLIC_ACCOUNT_ID`), which passed through as ACCT=\"\" and made
get_quotes fail for every symbol while get_price_history kept working.
The fix uses the or-pattern so both unset and empty fall back.
"""
import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)),
                                  "..", "src"))

import importlib
import os
import unittest
from unittest import mock


FALLBACK = "5OI32712"
MODULES = ["spread_screener", "daytrade_screen", "pmcc_quality",
           "stock_screener"]


def _reload_acct(module_name):
    mod = importlib.import_module(module_name)
    importlib.reload(mod)
    return mod.ACCT


class TestAcctFallback(unittest.TestCase):
    def test_empty_string_falls_back(self):
        for m in MODULES:
            with self.subTest(module=m):
                with mock.patch.dict(os.environ, {"PUBLIC_ACCOUNT_ID": ""}):
                    self.assertEqual(_reload_acct(m), FALLBACK)

    def test_unset_falls_back(self):
        for m in MODULES:
            with self.subTest(module=m):
                env = {k: v for k, v in os.environ.items()
                       if k != "PUBLIC_ACCOUNT_ID"}
                with mock.patch.dict(os.environ, env, clear=True):
                    self.assertEqual(_reload_acct(m), FALLBACK)

    def test_explicit_value_respected(self):
        for m in MODULES:
            with self.subTest(module=m):
                with mock.patch.dict(os.environ,
                                     {"PUBLIC_ACCOUNT_ID": "ABC123"}):
                    self.assertEqual(_reload_acct(m), "ABC123")


if __name__ == "__main__":
    unittest.main()
