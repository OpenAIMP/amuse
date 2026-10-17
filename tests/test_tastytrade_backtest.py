"""
Tests for src/tastytrade_backtest.py (#111).

Tests cover payload builders and result summarization (no network calls).
Network-dependent functions (auth, API calls) are not tested here —
they require Tastytrade credentials.
"""

import io
import json
import sys
import os
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import tastytrade_backtest as tt


class TestBuildBacktest(unittest.TestCase):
    def test_bull_put_payload_structure(self):
        payload = tt.build_backtest(
            symbol="SPY",
            strategy="bull_put",
            start_date="2022-01-01",
            end_date="2026-10-01",
        )
        self.assertEqual(payload["symbol"], "SPY")
        self.assertEqual(payload["startDate"], "2022-01-01")
        self.assertEqual(payload["endDate"], "2026-10-01")
        self.assertEqual(len(payload["legs"]), 2)
        # Short put leg
        self.assertEqual(payload["legs"][0]["direction"], "short")
        self.assertEqual(payload["legs"][0]["side"], "put")
        # Long put leg
        self.assertEqual(payload["legs"][1]["direction"], "long")
        self.assertEqual(payload["legs"][1]["side"], "put")

    def test_iron_condor_has_four_legs(self):
        payload = tt.build_backtest(
            symbol="QQQ", strategy="iron_condor",
            start_date="2022-01-01", end_date="2026-01-01",
        )
        self.assertEqual(len(payload["legs"]), 4)
        sides = sorted(l["side"] for l in payload["legs"])
        self.assertEqual(sides, ["call", "call", "put", "put"])

    def test_exit_conditions(self):
        payload = tt.build_backtest(
            symbol="SPY", strategy="bull_put",
            start_date="2022-01-01", end_date="2026-01-01",
            dte_target=45, profit_target=0.50, exit_dte=21,
        )
        exits = payload["exitConditions"]
        # API uses takeProfitPercentage (50 = 50%)
        self.assertEqual(exits["takeProfitPercentage"], 50)
        # DTE is per-leg per API spec
        self.assertEqual(payload["legs"][0]["daysUntilExpiration"], 45)
        self.assertEqual(payload["entryConditions"]["frequency"], "every day")

    def test_stop_loss_optional(self):
        payload = tt.build_backtest(
            symbol="SPY", strategy="bull_put",
            start_date="2022-01-01", end_date="2026-01-01",
            stop_loss=2.0,
        )
        # API uses stopLossPercentage (200 = 2x credit)
        self.assertEqual(payload["exitConditions"]["stopLossPercentage"], 200)

        payload_no_sl = tt.build_backtest(
            symbol="SPY", strategy="bull_put",
            start_date="2022-01-01", end_date="2026-01-01",
        )
        self.assertNotIn("stopLoss", payload_no_sl["exitConditions"])

    def test_unknown_strategy_raises(self):
        with self.assertRaises(ValueError):
            tt.build_backtest(
                symbol="SPY", strategy="not_a_strategy",
                start_date="2022-01-01", end_date="2026-01-01",
            )


class TestSummarizeResults(unittest.TestCase):
    def _make_result(self, pnls):
        return {
            "statistics": {"profitFactor": 1.5, "maxDrawdown": -200},
            "trials": [{"pnl": p} for p in pnls],
        }

    def test_basic_summary(self):
        result = self._make_result([100, 150, -50, 200, -75])
        summary = tt.summarize_results(result)
        self.assertEqual(summary["trade_count"], 5)
        self.assertEqual(summary["win_count"], 3)
        self.assertEqual(summary["loss_count"], 2)
        self.assertAlmostEqual(summary["win_rate"], 0.6)
        self.assertEqual(summary["total_pnl"], 325)

    def test_avg_win_loss(self):
        result = self._make_result([100, 200, -50])
        summary = tt.summarize_results(result)
        self.assertAlmostEqual(summary["avg_win"], 150.0)
        self.assertAlmostEqual(summary["avg_loss"], -50.0)

    def test_empty_trials(self):
        summary = tt.summarize_results({"statistics": {}, "trials": []})
        self.assertEqual(summary["trade_count"], 0)
        self.assertEqual(summary["win_rate"], 0)
        self.assertEqual(summary["total_pnl"], 0)

    def test_server_stats_merged(self):
        result = self._make_result([100])
        summary = tt.summarize_results(result)
        self.assertEqual(summary["profitFactor"], 1.5)
        self.assertEqual(summary["maxDrawdown"], -200)


class TestStrategyLegs(unittest.TestCase):
    def test_all_strategies_have_legs(self):
        for name, legs in tt.STRATEGY_LEGS.items():
            # single_put is a diagnostic single-leg strategy
            min_legs = 1 if name == "single_put" else 2
            self.assertTrue(len(legs) >= min_legs, f"{name} has no legs")
            for leg in legs:
                self.assertIn("type", leg)
                self.assertIn("side", leg)
                self.assertIn("direction", leg)


class TestOAuthSession(unittest.TestCase):
    SECRET = "test-client-secret-abc123"
    REFRESH = "test-refresh-token-xyz789"

    def _mock_token_response(self, access="tok-1", expires_in=900,
                             new_refresh=None):
        payload = {"access_token": access, "token_type": "Bearer",
                   "expires_in": expires_in}
        if new_refresh:
            payload["refresh_token"] = new_refresh
        resp = mock.MagicMock()
        resp.read.return_value = json.dumps(payload).encode()
        resp.__enter__ = mock.MagicMock(return_value=resp)
        resp.__exit__ = mock.MagicMock(return_value=False)
        return resp

    def _session(self, **kw):
        kw.setdefault("client_secret", self.SECRET)
        kw.setdefault("refresh_token", self.REFRESH)
        return tt.OAuthSession(**kw)

    def test_missing_credentials_raise(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(ValueError) as ctx:
                tt.OAuthSession()
            self.assertIn("TASTYTRADE_CLIENT_SECRET", str(ctx.exception))

    def test_env_fallback(self):
        env = {"TASTYTRADE_CLIENT_SECRET": "env-secret",
               "TASTYTRADE_REFRESH_TOKEN": "env-refresh"}
        with mock.patch.dict(os.environ, env, clear=True):
            s = tt.OAuthSession()
            self.assertEqual(s._client_secret, "env-secret")
            self.assertEqual(s._refresh_token, "env-refresh")

    def test_refresh_posts_form_encoded(self):
        s = self._session()
        with mock.patch("urllib.request.urlopen",
                        return_value=self._mock_token_response()) as m:
            token = s.get_access_token()
        self.assertEqual(token, "tok-1")
        req = m.call_args[0][0]
        self.assertIn("/oauth/token", req.full_url)
        self.assertEqual(
            req.headers.get("Content-type"),
            "application/x-www-form-urlencoded",
        )
        body = req.data.decode()
        self.assertIn("grant_type=refresh_token", body)
        # Secrets go in the body, never in the URL
        self.assertNotIn(self.SECRET, req.full_url)
        self.assertNotIn(self.REFRESH, req.full_url)

    def test_proactive_refresh_before_expiry(self):
        s = self._session()
        calls = {"n": 0}

        def fake_urlopen(req, timeout=None):
            calls["n"] += 1
            return self._mock_token_response(
                access=f"tok-{calls['n']}", expires_in=900)

        with mock.patch("urllib.request.urlopen", side_effect=fake_urlopen):
            t1 = s.get_access_token()
            t2 = s.get_access_token()  # within validity, no new call
        self.assertEqual(t1, t2)
        self.assertEqual(calls["n"], 1)

        # Force expiry -> next call refreshes
        s._expires_at = time.time() - 1
        with mock.patch("urllib.request.urlopen", side_effect=fake_urlopen):
            t3 = s.get_access_token()
        self.assertNotEqual(t3, t1)
        self.assertEqual(calls["n"], 2)

    def test_refresh_inside_margin_triggers_early(self):
        s = self._session()
        with mock.patch("urllib.request.urlopen",
                        return_value=self._mock_token_response(
                            access="tok-1", expires_in=120)):
            s.get_access_token()
        # 120s validity, 59s left -> inside 60s margin -> refresh
        s._expires_at = time.time() + 59
        with mock.patch("urllib.request.urlopen",
                        return_value=self._mock_token_response(
                            access="tok-2")) as m:
            token = s.get_access_token()
        self.assertEqual(token, "tok-2")
        self.assertTrue(m.called)

    def test_refresh_token_rotation(self):
        s = self._session()
        with mock.patch("urllib.request.urlopen",
                        return_value=self._mock_token_response(
                            new_refresh="rotated-refresh-999")):
            s.get_access_token()
        self.assertEqual(s._refresh_token, "rotated-refresh-999")

    def test_malformed_response_raises(self):
        s = self._session()
        resp = mock.MagicMock()
        resp.read.return_value = b'{"unexpected": true}'
        resp.__enter__ = mock.MagicMock(return_value=resp)
        resp.__exit__ = mock.MagicMock(return_value=False)
        with mock.patch("urllib.request.urlopen", return_value=resp):
            with self.assertRaises(RuntimeError):
                s.get_access_token()


class TestNoSecretLeak(unittest.TestCase):
    SECRET = "super-secret-client-abc"
    REFRESH = "super-secret-refresh-xyz"

    def test_repr_hides_secrets(self):
        s = tt.OAuthSession(client_secret=self.SECRET,
                            refresh_token=self.REFRESH)
        r = repr(s)
        self.assertNotIn(self.SECRET, r)
        self.assertNotIn(self.REFRESH, r)

    def test_http_error_hides_secrets(self):
        import urllib.error
        s = tt.OAuthSession(client_secret=self.SECRET,
                            refresh_token=self.REFRESH)
        err = urllib.error.HTTPError(
            url="https://api.tastyworks.com/oauth/token",
            code=401, msg="Unauthorized", hdrs={},
            fp=io.BytesIO(b'{"error": "invalid_client"}'),
        )
        with mock.patch("urllib.request.urlopen", side_effect=err):
            with self.assertRaises(RuntimeError) as ctx:
                s.get_access_token()
        msg = str(ctx.exception)
        self.assertNotIn(self.SECRET, msg)
        self.assertNotIn(self.REFRESH, msg)
        self.assertIn("401", msg)  # diagnostic info preserved

    def test_missing_credentials_error_hides_nothing_sensitive(self):
        # No secrets exist yet; the error must name the env vars, not values.
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(ValueError) as ctx:
                tt.OAuthSession()
        msg = str(ctx.exception)
        self.assertIn("TASTYTRADE_CLIENT_SECRET", msg)
        self.assertIn("TASTYTRADE_REFRESH_TOKEN", msg)


if __name__ == "__main__":
    unittest.main()
