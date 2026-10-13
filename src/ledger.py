"""Paper/live position ledger with sizing controls (issue #10).

Records every position with explicit fill assumptions, closes them with a
reason, and computes realized P&L net of fees. Sizing controls enforce the
1-2% max-loss-per-trade rule and the 30-40% portfolio heat cap from the
allocation framework.

Stdlib only. The ledger is a plain dict, serializable to JSON.
"""

import json
import uuid
from datetime import date, datetime, timezone

MULT = 100  # shares per contract


def new_ledger():
    return {"schema_version": 1, "updated_at": _now_utc(), "positions": []}


def _today():
    return date.today().isoformat()


def _now_utc():
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _touch(ledger):
    ledger["updated_at"] = _now_utc()


def open_position(ledger, underlying, strategy, legs, credit, contracts,
                  max_loss, dte, fill_note="", opened=None, fee_per_contract=0.65):
    """Record a new open position.

    legs        : list of {side, type, strike, expiry} describing the structure
    credit      : per-share credit received (positive)
    contracts   : number of spreads
    max_loss    : per-share maximum loss of the structure (positive)
    fill_note   : explicit execution assumption, e.g. "short bid - long ask"
    Returns the position dict (with generated id).
    """
    pos = {
        "id": uuid.uuid4().hex[:8],
        "underlying": underlying,
        "strategy": strategy,
        "legs": legs,
        "credit": credit,
        "contracts": contracts,
        "max_loss": max_loss,
        "dte_at_entry": dte,
        "fill_note": fill_note,
        "fee_per_contract": fee_per_contract,
        "fees_paid": round(contracts * fee_per_contract, 2),
        "opened": opened or _today(),
        "status": "open",
        "exit": None,
    }
    ledger["positions"].append(pos)
    _touch(ledger)
    return pos


def close_position(ledger, pos_id, close_cost, reason, closed=None, note=""):
    """Close an open position.

    close_cost : per-share debit paid to buy back (positive)
    reason     : TAKE_PROFIT / STOP_LOSS / TIME_EXIT / EXPIRATION_RISK / MANUAL
    Returns (position, realized_pnl).
    """
    pos = next((p for p in ledger["positions"]
                if p["id"] == pos_id and p["status"] == "open"), None)
    if pos is None:
        raise KeyError(f"no open position {pos_id}")
    exit_fees = round(pos["contracts"] * pos["fee_per_contract"], 2)
    gross = (pos["credit"] - close_cost) * MULT * pos["contracts"]
    realized = round(gross - pos["fees_paid"] - exit_fees, 2)
    pos["status"] = "closed"
    pos["exit"] = {
        "closed": closed or _today(),
        "close_cost": close_cost,
        "reason": reason,
        "fees": exit_fees,
        "realized_pnl": realized,
        "note": note,
    }
    _touch(ledger)
    return pos, realized


def realized_pnl(ledger):
    return round(sum(p["exit"]["realized_pnl"] for p in ledger["positions"]
                     if p["status"] == "closed"), 2)


def stats(ledger):
    """Win rate, average win/loss, totals — per strategy and overall."""
    closed = [p for p in ledger["positions"] if p["status"] == "closed"]
    pnls = [p["exit"]["realized_pnl"] for p in closed]
    wins = [x for x in pnls if x > 0]
    losses = [x for x in pnls if x <= 0]
    by_strategy = {}
    for p in closed:
        s = by_strategy.setdefault(p["strategy"], [])
        s.append(p["exit"]["realized_pnl"])
    return {
        "trades": len(closed),
        "win_rate": round(len(wins) / len(closed), 3) if closed else 0.0,
        "avg_win": round(sum(wins) / len(wins), 2) if wins else 0.0,
        "avg_loss": round(sum(losses) / len(losses), 2) if losses else 0.0,
        "total": round(sum(pnls), 2),
        "by_strategy": {k: round(sum(v), 2) for k, v in by_strategy.items()},
    }


def open_heat(ledger):
    """Total max loss at risk across open positions ($)."""
    return round(sum(p["max_loss"] * MULT * p["contracts"]
                     for p in ledger["positions"] if p["status"] == "open"), 2)


def max_contracts(max_loss_per_share, account, max_loss_pct=0.02):
    """Contracts such that one trade's max loss <= max_loss_pct of account."""
    if max_loss_per_share <= 0 or account <= 0:
        return 0
    return int(account * max_loss_pct // (max_loss_per_share * MULT))


def can_open(ledger, max_loss_per_share, contracts, account, cfg=None):
    """Sizing + heat gate. Returns (ok, reason)."""
    cfg = cfg or {}
    max_loss_pct = cfg.get("max_loss_pct", 0.02)
    heat_cap_pct = cfg.get("heat_cap_pct", 0.35)
    if contracts < 1:
        return False, "zero contracts"
    trade_risk = max_loss_per_share * MULT * contracts
    if trade_risk > account * max_loss_pct:
        allowed = max_contracts(max_loss_per_share, account, max_loss_pct)
        return (False,
                f"trade risk ${trade_risk:.0f} > {max_loss_pct:.0%} of account; "
                f"max {allowed} contracts")
    if open_heat(ledger) + trade_risk > account * heat_cap_pct:
        return (False,
                f"heat cap: open ${open_heat(ledger):.0f} + new ${trade_risk:.0f} "
                f"> {heat_cap_pct:.0%} of account")
    return True, "within sizing and heat limits"


def save(ledger, path):
    with open(path, "w") as f:
        json.dump(ledger, f, indent=2)


def load(path):
    with open(path) as f:
        return json.load(f)
