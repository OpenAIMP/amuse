"""Exit rules for bull put spreads (issue #9).

Pure functions: given entry state and current market state, return an action.
No I/O, no MCP calls — fully testable in isolation. Position tracking and
execution live in the ledger (issue #10); this module defines the rules.

Actions:
  HOLD            - no exit condition met
  TAKE_PROFIT     - buy-back cost fell to the profit target (keep ~50% of credit)
  STOP_LOSS       - buy-back cost rose to stop_loss_mult x credit; cap the loss
                    well below the spread's max loss
  TIME_EXIT       - DTE fell to min_dte_exit; gamma risk into expiration is not
                    part of this strategy — close or roll, never hold through
  EXPIRATION_RISK - short leg ITM inside the assignment window; close the
                    spread rather than take assignment (no_assignment policy)

All thresholds come from gates.yaml [exits][bull_put_spread].
"""

HOLD = "HOLD"
TAKE_PROFIT = "TAKE_PROFIT"
STOP_LOSS = "STOP_LOSS"
TIME_EXIT = "TIME_EXIT"
EXPIRATION_RISK = "EXPIRATION_RISK"


def evaluate(entry_credit, close_cost, dte, short_itm=False, cfg=None):
    """Decide the action for an open bull put spread.

    entry_credit : credit received at entry (per share, positive)
    close_cost   : current ask to buy back the spread (per share, positive)
    dte          : days to expiration remaining
    short_itm    : True if the short put is in-the-money
    cfg          : dict with profit_target_pct, stop_loss_mult, min_dte_exit,
                   assignment_dte, no_assignment. Defaults to the standard
                   50% / 2x / 7 DTE / no-assignment policy.
    Returns (action, reason).
    """
    cfg = cfg or {}
    profit_target_pct = cfg.get("profit_target_pct", 0.50)
    stop_loss_mult = cfg.get("stop_loss_mult", 2.0)
    min_dte_exit = cfg.get("min_dte_exit", 7)
    assignment_dte = cfg.get("assignment_dte", 2)
    no_assignment = cfg.get("no_assignment", True)

    if entry_credit <= 0:
        return HOLD, "no credit recorded; cannot evaluate exits"
    if close_cost < 0:
        return HOLD, "negative close cost; bad mark"

    # Assignment risk dominates everything inside the window.
    if no_assignment and short_itm and dte <= assignment_dte:
        return (EXPIRATION_RISK,
                f"short put ITM with {dte} DTE; close rather than take assignment")

    # Time exit before gamma run-up.
    if dte <= min_dte_exit:
        return TIME_EXIT, f"{dte} DTE <= {min_dte_exit} DTE floor; close or roll"

    # Profit target: keep profit_target_pct of the credit.
    if close_cost <= entry_credit * (1 - profit_target_pct):
        kept = (entry_credit - close_cost) / entry_credit
        return TAKE_PROFIT, f"buy-back at {close_cost:.2f} keeps {kept:.0%} of credit"

    # Stop loss: buy-back costs stop_loss_mult x the credit.
    if close_cost >= entry_credit * stop_loss_mult:
        return (STOP_LOSS,
                f"buy-back at {close_cost:.2f} = "
                f"{close_cost / entry_credit:.1f}x credit; cap the loss")

    return HOLD, "no exit condition met"


def describe(cfg=None):
    """One-line human summary of the policy (for reports)."""
    cfg = cfg or {}
    pt = cfg.get("profit_target_pct", 0.50)
    sl = cfg.get("stop_loss_mult", 2.0)
    md = cfg.get("min_dte_exit", 7)
    return (f"take profit at {pt:.0%} of credit kept; "
            f"stop at {sl:.0f}x credit buy-back; "
            f"exit by {md} DTE; no assignment")
