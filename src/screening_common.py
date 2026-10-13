"""Shared result classification and ranking for symbol-universe screeners."""

QUALIFICATION_STATUSES = ("qualified", "rejected", "incomplete_data", "error")
STATUS_ORDER = {status: rank for rank, status in enumerate(QUALIFICATION_STATUSES)}

INCOMPLETE_REASON_PREFIXES = (
    "daily bars failed", "insufficient daily history", "insufficient history",
    "atr uncomputable", "quote failed", "no quote", "intraday bars failed",
    "no intraday bars", "opening range not yet formed", "volume baseline unknown",
    "no reported premarket volume",
    "data error:", "missing or invalid underlying quote",
)
ERROR_REASON_PREFIXES = ("internal error:", "unexpected error:", "evaluation error:",
                        "mcp error:")


def evaluation_record(result=None, reasons=None, error=None):
    """Return a uniform per-symbol record with its qualification category."""
    row = dict(result or {})
    details = [error] if error else list(reasons or [])
    if error or any(str(reason).startswith(ERROR_REASON_PREFIXES) for reason in details):
        status = "error"
    elif any(str(reason).startswith(INCOMPLETE_REASON_PREFIXES) for reason in details):
        status = "incomplete_data"
    else:
        status = "rejected" if details else "qualified"
    row["qualification_status"] = status
    row["qualification_reasons"] = details
    if error:
        row["error"] = error
    return row


def qualification_counts(rows):
    """Count rows in each stable qualification category."""
    return {status: sum(1 for row in rows
                        if row.get("qualification_status") == status)
            for status in QUALIFICATION_STATUSES}


def sort_evaluations(rows, score_key="conviction"):
    """Order full-universe rows by outcome, score, then symbol."""
    def sort_key(row):
        value = row.get(score_key)
        score = value if isinstance(value, (int, float)) else float("-inf")
        return (STATUS_ORDER.get(row.get("qualification_status"), len(STATUS_ORDER)),
                -score, str(row.get("symbol") or ""))
    return sorted(rows, key=sort_key)


def rank_qualified(rows, qualified_rows, limit=None, score_key="conviction"):
    """Add deterministic rank/selection metadata and return ranked qualifiers."""
    def rank_key(row):
        value = row.get(score_key)
        score = value if isinstance(value, (int, float)) else float("-inf")
        return (-score, str(row.get("symbol") or ""))

    ranked = sorted(qualified_rows, key=rank_key)
    ranks = {row.get("symbol"): rank for rank, row in enumerate(ranked, 1)}
    selected_count = len(ranked) if limit is None else max(0, limit)
    for row in rows:
        rank = ranks.get(row.get("symbol"))
        row["candidate_rank"] = rank
        row["selected"] = rank is not None and rank <= selected_count
    return ranked if limit is None else ranked[:limit]
