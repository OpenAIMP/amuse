"""
Tastytrade backtesting integration (#111).

Submits options backtests to Tastytrade's backtesting API and retrieves
results for strategy validation. Uses only stdlib (urllib, json) to match
the repo's no-dependency convention.

API host: https://backtester.vast.tastyworks.com
Docs: https://developer.tastytrade.com/docs/guides/backtesting/

Auth: requires a Tastytrade account. Set TT_USERNAME and TT_PASSWORD
environment variables, or pass a session token directly.

Usage:
    python3 src/tastytrade_backtest.py --symbol SPY --strategy bull_put \
        --start 2022-01-01 --end 2026-10-01

    python3 src/tastytrade_backtest.py --check-dates --symbol SPY
"""

import json
import os
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime

# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

AUTH_HOST = "https://api.tastyworks.com"
BACKTEST_HOST = "https://backtester.vast.tastyworks.com"

# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------


def get_session_token(username=None, password=None):
    """Authenticate and return a session token."""
    username = username or os.environ.get("TT_USERNAME")
    password = password or os.environ.get("TT_PASSWORD")
    if not username or not password:
        raise ValueError(
            "Tastytrade credentials required. Set TT_USERNAME and TT_PASSWORD "
            "environment variables."
        )

    url = f"{AUTH_HOST}/sessions"
    body = json.dumps({"login": username, "password": password}).encode()
    req = urllib.request.Request(
        url, data=body, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
            return data["data"]["session-token"]
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"Authentication failed: HTTP {e.code}") from e


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

STRATEGY_LEGS = {
    "bull_put": [
        {"type": "equity-option", "side": "put", "direction": "short",
         "strikeSelection": "delta", "strikeValue": 0.16, "quantity": 1},
        {"type": "equity-option", "side": "put", "direction": "long",
         "strikeSelection": "delta", "strikeValue": 0.10, "quantity": 1},
    ],
    "bear_call": [
        {"type": "equity-option", "side": "call", "direction": "short",
         "strikeSelection": "delta", "strikeValue": 0.16, "quantity": 1},
        {"type": "equity-option", "side": "call", "direction": "long",
         "strikeSelection": "delta", "strikeValue": 0.10, "quantity": 1},
    ],
    "iron_condor": [
        {"type": "equity-option", "side": "put", "direction": "short",
         "strikeSelection": "delta", "strikeValue": 0.16, "quantity": 1},
        {"type": "equity-option", "side": "put", "direction": "long",
         "strikeSelection": "delta", "strikeValue": 0.10, "quantity": 1},
        {"type": "equity-option", "side": "call", "direction": "short",
         "strikeSelection": "delta", "strikeValue": 0.16, "quantity": 1},
        {"type": "equity-option", "side": "call", "direction": "long",
         "strikeSelection": "delta", "strikeValue": 0.10, "quantity": 1},
    ],
}


def build_backtest(symbol, strategy, start_date, end_date,
                   dte_target=45, profit_target=0.50,
                   stop_loss=None, exit_dte=21):
    """
    Build a backtest request payload for one of our strategies.

    Entry: <dte_target> DTE, delta-based strike selection.
    Exits: profit_target (fraction of credit), optional stop_loss,
           exit at <exit_dte> DTE.

    Returns the payload dict ready for POST /backtests.
    """
    if strategy not in STRATEGY_LEGS:
        raise ValueError(
            f"Unknown strategy '{strategy}'. "
            f"Available: {sorted(STRATEGY_LEGS)}"
        )

    entry_conditions = {
        "daysToExpiration": dte_target,
    }

    exit_conditions = {
        "profitTarget": profit_target,
        "atDaysToExpiration": exit_dte,
    }
    if stop_loss is not None:
        exit_conditions["stopLoss"] = stop_loss

    return {
        "symbol": symbol,
        "startDate": start_date,
        "endDate": end_date,
        "legs": STRATEGY_LEGS[strategy],
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

    Returns dict with win_rate, total_pnl, avg_win, avg_loss, trade_count,
    profit_factor, max_drawdown (when available).
    """
    stats = result.get("statistics", {})
    trials = result.get("trials", [])

    wins = [t for t in trials if (t.get("pnl") or 0) > 0]
    losses = [t for t in trials if (t.get("pnl") or 0) <= 0]

    summary = {
        "trade_count": len(trials),
        "win_count": len(wins),
        "loss_count": len(losses),
        "win_rate": len(wins) / len(trials) if trials else 0,
        "total_pnl": sum(t.get("pnl", 0) for t in trials),
        "avg_win": sum(t.get("pnl", 0) for t in wins) / len(wins) if wins else 0,
        "avg_loss": sum(t.get("pnl", 0) for t in losses) / len(losses) if losses else 0,
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

    token = get_session_token()

    if args.check_dates:
        dates = get_available_dates(token, args.symbol)
        print(json.dumps(dates, indent=2))
        return 0

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
