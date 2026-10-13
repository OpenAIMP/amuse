"""Unit tests for mcp_client.py (issue #36).

The shared MCP subprocess client every screener funnels through.
"""
import json
import os as _os
import subprocess as _sp
import sys as _sys
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)),
                                  "..", "src"))

import unittest
from unittest import mock

import mcp_client


def _envelope(payload, is_error=False):
    return json.dumps({"content": [{"text": json.dumps(payload)}],
                       "isError": is_error})


class TestMcpCall(unittest.TestCase):
    def _run(self, stdout, returncode=0):
        proc = mock.Mock()
        proc.returncode = returncode
        proc.stdout = stdout
        proc.stderr = ""
        with mock.patch.object(_sp, "run", return_value=proc) as run:
            return mcp_client.mcp_call("get_quotes", {"symbols": ["AAA"]}), run

    def test_success_returns_parsed_payload(self):
        out, run = self._run(_envelope({"price": 100.0}))
        self.assertEqual(out, {"price": 100.0})
        args = run.call_args[0][0]
        self.assertEqual(args[1], "call")
        self.assertEqual(args[2], "get_quotes")

    def test_timeout_becomes_mcp_error(self):
        with mock.patch.object(_sp, "run",
                               side_effect=_sp.TimeoutExpired("x", 1)):
            with self.assertRaises(mcp_client.McpError):
                mcp_client.mcp_call("get_quotes", {})

    def test_nonzero_exit_becomes_mcp_error(self):
        with mock.patch.object(_sp, "run") as run:
            run.return_value.returncode = 1
            run.return_value.stderr = "boom"
            run.return_value.stdout = ""
            with self.assertRaises(mcp_client.McpError):
                mcp_client.mcp_call("get_quotes", {})

    def test_non_json_becomes_mcp_error(self):
        with self.assertRaises(mcp_client.McpError):
            self._run("not json")

    def test_api_error_flag_becomes_mcp_error(self):
        with self.assertRaises(mcp_client.McpError):
            self._run(_envelope({"x": 1}, is_error=True))

    def test_unparseable_content_becomes_mcp_error(self):
        bad = json.dumps({"content": [{"text": "not json either"}]})
        with self.assertRaises(mcp_client.McpError):
            self._run(bad)

    def test_mcp_error_is_runtime_error(self):
        self.assertTrue(issubclass(mcp_client.McpError, RuntimeError))


if __name__ == "__main__":
    unittest.main()
