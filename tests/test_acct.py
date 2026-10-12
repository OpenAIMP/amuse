"""Tests for issue #23: PUBLIC_ACCOUNT_ID is required, no hardcoded fallback.

Empty or unset PUBLIC_ACCOUNT_ID must fail fast at import with SystemExit
instead of silently producing an unusable account id (the #22 failure mode).
An explicit value must be respected.
"""
import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)),
                                  "..", "src"))

import os
import subprocess
import sys
import unittest


MODULES = ["spread_screener", "daytrade_screen", "pmcc_quality",
           "stock_screener"]
SRC_DIR = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)),
                        "..", "src")


def _import_acct(module_name, env_value):
    """Import module in a subprocess with controlled env; return (rc, ACCT)."""
    env = {k: v for k, v in os.environ.items()
           if k != "PUBLIC_ACCOUNT_ID"}
    if env_value is not None:
        env["PUBLIC_ACCOUNT_ID"] = env_value
    code = (f"import sys; sys.path.insert(0, {SRC_DIR!r}); "
            f"import {module_name}; print({module_name}.ACCT)")
    r = subprocess.run([sys.executable, "-c", code], capture_output=True,
                       text=True, env=env, timeout=60)
    return r.returncode, r.stdout.strip(), r.stderr.strip()


class TestAcctRequired(unittest.TestCase):
    def test_empty_raises(self):
        for m in MODULES:
            with self.subTest(module=m):
                rc, _, err = _import_acct(m, "")
                self.assertNotEqual(rc, 0, f"{m} imported with empty account id")
                self.assertIn("PUBLIC_ACCOUNT_ID", err)

    def test_unset_raises(self):
        for m in MODULES:
            with self.subTest(module=m):
                rc, _, err = _import_acct(m, None)
                self.assertNotEqual(rc, 0, f"{m} imported with unset account id")
                self.assertIn("PUBLIC_ACCOUNT_ID", err)

    def test_explicit_value_respected(self):
        for m in MODULES:
            with self.subTest(module=m):
                rc, acct, _ = _import_acct(m, "TESTACCT1")
                self.assertEqual(rc, 0)
                self.assertEqual(acct, "TESTACCT1")


if __name__ == "__main__":
    unittest.main()
