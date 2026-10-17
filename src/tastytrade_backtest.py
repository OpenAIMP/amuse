"""
Tastytrade backtesting integration (#111).

Submits options backtests to Tastytrade's backtesting API and retrieves
results for strategy validation. Uses only stdlib (urllib, json) to match
the repo's no-dependency convention.

API host: https://backtester.vast.tastyworks.com
Docs: https://developer.tastytrade.com/docs/guides/backtesting/

Auth: OAuth2 only. The legacy POST /sessions username/password flow was
decommissioned by Tastytrade on 2026-02-11 and no longer exists.
Create an OAuth application at my.tastytrade.com -> Manage -> My Profile
-> API -> OAuth Applications, then "Create Grant" for a personal
refresh token. Set TASTYTRADE_CLIENT_SECRET and TASTYTRADE_REFRESH_TOKEN
environment variables.

Usage:
    python3 src/tastytrade_backtest.py --symbol SPY --strategy bull_put \
        --start 2022-01-01 --end 2026-10-01

    python3 src/tastytrade_backtest.py --check-dates --symbol SPY
"""

import json
import os
import sys
import time
import urllib.parse
import urllib.request
import urllib.error
from datetime import datetime

# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

AUTH_HOST = "https://api.tastyworks.com"
BACKTEST_HOST = "https://backtester.vast.tastyworks.com"

# Refresh the access token this many seconds before it expires.
# Renewal is proactive, never a retry after 401: a POST that may have
# placed an order must not be replayed.
REFRESH_MARGIN_SECS = 60

# ---------------------------------------------------------------------------
# Authentication (OAuth2)
# ---------------------------------------------------------------------------


class OAuthSession:
    """
    OAuth2 session using the personal refresh-token grant.

    POSTs form-encoded grant_type=refresh_token to /oauth/token and
    keeps a short-lived access token (~15 min), refreshing proactively
    before expiry. Secrets never appear in exceptions, logs, or repr.
    """

    def __init__(self, client_secret=None, refresh_token=None,
                 base_url=AUTH_HOST):
        self._client_secret = (
            client_secret or os.environ.get("TASTYTRADE_CLIENT_SECRET")
        )
        self._refresh_token = (
            refresh_token or os.environ.get("TASTYTRADE_REFRESH_TOKEN")
        )
        if not self._client_secret or not self._refresh_token:
            raise ValueError(
                "Tastytrade OAuth credentials required. Set "
                "TASTYTRADE_CLIENT_SECRET and TASTYTRADE_REFRESH_TOKEN "
                "environment variables. Create them at my.tastytrade.com "
                "-> Manage -> My Profile -> API -> OAuth Applications."
            )
        self.base_url = base_url
        self._access_token = None
        self._expires_at = 0

    def __repr__(self):
        return (
            f"OAuthSession(base_url={self.base_url!r}, "
            f"authenticated={self._access_token is not None})"
        )

    def get_access_token(self):
        """Return a valid access token, refreshing proactively if needed."""
        if (self._access_token is None
                or time.time() >= self._expires_at - REFRESH_MARGIN_SECS):
            self._refresh()
        return self._access_token

    def _refresh(self):
        """Exchange the refresh token for a new access token."""
        body = urllib.parse.urlencode({
            "grant_type": "refresh_token",
            "refresh_token": self._refresh_token,
            "client_secret": self._client_secret,
        }).encode()
        req = urllib.request.Request(
            f"{self.base_url}/oauth/token",
            data=body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read())
        except urllib.error.HTTPError as e:
            # Never include secrets in the error. Read a short body
            # for diagnostics, scrubbing nothing because the body
            # comes from the server, not from us.
            err_body = e.read().decode()[:300]
            raise RuntimeError(
                f"OAuth token refresh failed: HTTP {e.code}: {err_body}"
            ) from e
        try:
            self._access_token = data["access_token"]
            expires_in = int(data.get("expires_in", 900))
        except (KeyError, ValueError, TypeError) as e:
            raise RuntimeError(
                "OAuth token response missing access_token/expires_in"
            ) from e
        # The server may rotate the refresh token; keep the latest.
        if data.get("refresh_token"):
            self._refresh_token = data["refresh_token"]
        self._expires_at = time.time() + expires_in


def get_access_token(client_secret=None, refresh_token=None):
    """Convenience: build an OAuthSession and return an access token."""
    return OAuthSession(
        client_secret=client_secret,
        refresh_token=refresh_token,
    ).get_access_token()


def _headers(token):
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


def _api_get(path, token, host=BACKTEST_HOST):
    req = urllib.request.Request(
        f"{host}{path}", headers=_headers(token)
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode()[:500]
        raise RuntimeError(f"GET {path} failed: HTTP {e.code}: {body}") from e


def _api_post(path, payload, token, host=BACKTEST_HOST):
    body = json.dumps(payload).encode()
    req = urllib.request.Request(
        f"{host}{path}", data=body, headers=_headers(token)
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        err_body = e.read().decode()[:500]
        raise RuntimeError(
            f"POST {path} failed: HTTP {e.code}: {err_body}"
        ) from e


# ---------------------------------------------------------------------------
# Backtesting operations
# ---------------------------------------------------------------------------


def get_available_dates(token, symbol=None):
    """Check which symbols and date ranges are available for backtesting."""
    path = "/available-dates"
    if symbol:
        path += f"?symbol={symbol}"
    return _api_get(path, token)


def list_backtests(token):
    """List the user's backtest IDs."""
    return _api_get("/backtests", token)


def get_backtest(token, backtest_id):
    """Get a backtest's status and results."""
    return _api_get(f"/backtests/{backtest_id}", token)


def get_backtest_logs(token, backtest_id):
    """Get detailed logs for a backtest."""
    return _api_get(f"/backtests/{backtest_id}/logs", token)


def cancel_backtest(token, backtest_id):
    """Cancel a running backtest."""
    return _api_post(f"/backtests/{backtest_id}/cancel", {}, token)


def simulate_trade(token, underlying, legs, start_time, end_time):
    """
    One-shot historical price lookup for specific OCC option symbols.

    legs: list of OCC-format symbols, e.g. ["SPY  260116P00580000"]
    """
    payload = {
        "underlying": underlying,
        "legs": legs,
        "startTime": start_time,
        "endTime": end_time,
    }
    return _api_post("/simulate-trade", payload, token)


# ---------------------------------------------------------------------------
# Strategy builders
# ---------------------------------------------------------------------------

# Maps our strategy names to Tastytrade backtest leg configurations.
# Each leg: {type, side, direction, strikeSelection, quantity}
#
# strikeSelection options (per API docs):
#   delta, delta_abs, strike, strike_offset, percent_otm, etc.

def _make_leg(side, direction, delta, dte):
    """Build a single option leg per Tastytrade backtest API spec.
    
    Per https://developer.tastytrade.com/docs/guides/backtesting:
    - strikeSelection "delta" takes a "delta" field (e.g. 16 for 16-delta)
    - daysUntilExpiration is a per-leg field (not in entryConditions)
    """
    return {
        "type": "equity-option",
        "side": side,
        "direction": direction,
        "quantity": 1,
        "strikeSelection": "delta",
        "delta": delta,
        "daysUntilExpiration": dte,
    }


def _strategy_legs(strategy, dte):
    """Build legs for a strategy with per-leg DTE."""
    if strategy == "bull_put":
        return [
            _make_leg("put", "short", 16, dte),
            _make_leg("put", "long", 10, dte),
        ]
    elif strategy == "bear_call":
        return [
            _make_leg("call", "short", 16, dte),
            _make_leg("call", "long", 10, dte),
        ]
    elif strategy == "iron_condor":
        return [
            _make_leg("put", "short", 16, dte),
            _make_leg("put", "long", 10, dte),
            _make_leg("call", "short", 16, dte),
            _make_leg("call", "long", 10, dte),
        ]
    else:
        raise ValueError(f"Unknown strategy '{strategy}'")


# Legacy constant for backwards compat (tests may reference)
STRATEGY_LEGS = {
    "bull_put": [
        {"type": "equity-option", "side": "put", "direction": "short",
         "strikeSelection": "delta", "delta": 16, "quantity": 1},
        {"type": "equity-option", "side": "put", "direction": "long",
         "strikeSelection": "delta", "delta": 10, "quantity": 1},
    ],
    "bear_call": [
        {"type": "equity-option", "side": "call", "direction": "short",
         "strikeSelection": "delta", "delta": 16, "quantity": 1},
        {"type": "equity-option", "side": "call", "direction": "long",
         "strikeSelection": "delta", "delta": 10, "quantity": 1},
    ],
    "iron_condor": [
        {"type": "equity-option", "side": "put", "direction": "short",
         "strikeSelection": "delta", "delta": 16, "quantity": 1},
        {"type": "equity-option", "side": "put", "direction": "long",
         "strikeSelection": "delta", "delta": 10, "quantity": 1},
        {"type": "equity-option", "side": "call", "direction": "short",
         "strikeSelection": "delta", "delta": 16, "quantity": 1},
        {"type": "equity-option", "side": "call", "direction": "long",
         "strikeSelection": "delta", "delta": 10, "quantity": 1},
    ],
}


def build_backtest(symbol, strategy, start_date, end_date,
                   dte_target=45, profit_target=0.50,
                   stop_loss=None, exit_dte=21):
    """
    Build a backtest request payload for one of our strategies.

    Per https://developer.tastytrade.com/docs/guides/backtesting:
    - Each leg has "delta" (e.g. 16) and "daysUntilExpiration" (per-leg)
    - entryConditions uses "frequency": "every day"
    - exitConditions uses "takeProfitPercentage" (e.g. 50 for 50%)

    Entry: <dte_target> DTE, delta-based strike selection.
    Exits: profit_target (fraction of credit), optional stop_loss.

    Returns the payload dict ready for POST /backtests.
    """
    legs = _strategy_legs(strategy, dte_target)

    entry_conditions = {
        "frequency": "every day",
    }

    # API expects takeProfitPercentage as a percentage (50 = 50%)
    exit_conditions = {
        "takeProfitPercentage": int(profit_target * 100),
    }
    if stop_loss is not None:
        # stopLoss as percentage of credit (e.g. 200 = 2x credit)
        exit_conditions["stopLossPercentage"] = int(stop_loss * 100)

    return {
        "symbol": symbol,
        "startDate": start_date,
        "endDate": end_date,
        "legs": legs,
        "entryConditions": entry_conditions,
        "exitConditions": exit_conditions,
    }


def run_backtest(token, payload, poll_interval=5, max_wait=600):
    """
    Submit a backtest and poll until complete.

    Returns the final result dict.
    """
    result = _api_post("/backtests", payload, token)
    backtest_id = result.get("backtestId") or result.get("id")
    if not backtest_id:
        raise RuntimeError(f"No backtest ID in response: {result}")

    print(f"Backtest submitted: {backtest_id}", file=sys.stderr)
    deadline = time.time() + max_wait
    while time.time() < deadline:
        status = get_backtest(token, backtest_id)
        state = status.get("status", "").lower()
        if state in ("completed", "complete", "done", "finished"):
            # Log notices which may explain 0 trades
            notices = status.get("notices", [])
            if notices:
                print(f"  Notices: {notices}", file=sys.stderr)
            trials = status.get("trials", [])
            print(f"  Trials returned: {len(trials)}", file=sys.stderr)
            return status
        if state in ("failed", "error", "cancelled"):
            raise RuntimeError(f"Backtest {state}: {status}")
        print(f"  ... status: {state}", file=sys.stderr)
        time.sleep(poll_interval)

    raise TimeoutError(
        f"Backtest {backtest_id} did not complete within {max_wait}s"
    )


# ---------------------------------------------------------------------------
# Result analysis
# ---------------------------------------------------------------------------


def summarize_results(result):
    """
    Extract key metrics from a completed backtest result.

    Per API docs, trials have `profitLoss` (not `pnl`).

    Returns dict with win_rate, total_pnl, avg_win, avg_loss, trade_count,
    profit_factor, max_drawdown (when available).
    """
    stats = result.get("statistics", {})
    trials = result.get("trials", [])

    def _pnl(t):
        # API uses profitLoss; be tolerant of pnl for backwards compat
        return t.get("profitLoss", t.get("pnl", 0)) or 0

    wins = [t for t in trials if _pnl(t) > 0]
    losses = [t for t in trials if _pnl(t) <= 0]

    summary = {
        "trade_count": len(trials),
        "win_count": len(wins),
        "loss_count": len(losses),
        "win_rate": len(wins) / len(trials) if trials else 0,
        "total_pnl": sum(_pnl(t) for t in trials),
        "avg_win": sum(_pnl(t) for t in wins) / len(wins) if wins else 0,
        "avg_loss": sum(_pnl(t) for t in losses) / len(losses) if losses else 0,
    }
    # Merge any server-computed stats
    for key in ("profitFactor", "maxDrawdown", "sharpeRatio"):
        if key in stats:
            summary[key] = stats[key]
    return summary


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv):
    import argparse

    parser = argparse.ArgumentParser(
        description="Tastytrade backtesting integration (#111)"
    )
    parser.add_argument("--symbol", default="SPY",
                        help="Underlying symbol (default: SPY)")
    parser.add_argument("--strategy", default="bull_put",
                        choices=sorted(STRATEGY_LEGS),
                        help="Strategy to backtest (default: bull_put)")
    parser.add_argument("--start", default="2022-01-01",
                        help="Backtest start date YYYY-MM-DD")
    parser.add_argument("--end",
                        default=datetime.now().strftime("%Y-%m-%d"),
                        help="Backtest end date YYYY-MM-DD")
    parser.add_argument("--dte", type=int, default=45,
                        help="Entry DTE (default: 45)")
    parser.add_argument("--profit-target", type=float, default=0.50,
                        help="Profit target as fraction of credit (default: 0.50)")
    parser.add_argument("--exit-dte", type=int, default=21,
                        help="Exit at DTE (default: 21)")
    parser.add_argument("--check-dates", action="store_true",
                        help="Check available backtest dates and exit")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print the backtest payload without submitting")

    args = parser.parse_args(argv)

    payload = build_backtest(
        symbol=args.symbol,
        strategy=args.strategy,
        start_date=args.start,
        end_date=args.end,
        dte_target=args.dte,
        profit_target=args.profit_target,
        exit_dte=args.exit_dte,
    )

    if args.dry_run:
        print(json.dumps(payload, indent=2))
        return 0

    # Authenticate only when we actually need the API.
    session = OAuthSession()
    token = session.get_access_token()

    if args.check_dates:
        dates = get_available_dates(token, args.symbol)
        print(json.dumps(dates, indent=2))
        return 0

    result = run_backtest(token, payload)
    summary = summarize_results(result)

    print(json.dumps({
        "symbol": args.symbol,
        "strategy": args.strategy,
        "period": f"{args.start} to {args.end}",
        "summary": summary,
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
