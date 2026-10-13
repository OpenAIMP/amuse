"""Build a local portfolio-risk market snapshot from timestamped data sources.

Public MCP is used only for read-only market quotes. Treasury supplies the
daily 3-month par yield. Account positions and generated snapshots stay local.
"""
import argparse
import json
import math
import os
import re
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date, datetime, timezone

import mcp_client

RATE_URL = "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/pages/xml"
QUOTE_BATCH_SIZE = 50
OSI_RE = re.compile(r"^(.+?)(\d{6})([CP])(\d{8})$")


def _utc(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("timestamp missing")
    parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp must include UTC offset")
    return parsed.astimezone(timezone.utc)


def _positive(value, name):
    if isinstance(value, bool):
        raise ValueError(f"{name} must be numeric")
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be numeric")
    if not math.isfinite(number) or number <= 0:
        raise ValueError(f"{name} must be finite and positive")
    return number


def _quote_records(payload):
    """Recursively collect Public quote objects keyed by their instrument symbol."""
    found = {}

    def walk(value):
        if isinstance(value, dict):
            instrument = value.get("instrument")
            symbol = instrument.get("symbol") if isinstance(instrument, dict) else None
            if isinstance(symbol, str) and symbol and symbol not in found:
                found[symbol] = value
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(payload)
    return found


def _quotes(symbols, account_id, errors):
    records = {}
    symbols = list(dict.fromkeys(symbols))
    for start in range(0, len(symbols), QUOTE_BATCH_SIZE):
        batch = symbols[start:start + QUOTE_BATCH_SIZE]
        try:
            payload = mcp_client.mcp_call(
                "get_quotes", {"symbols": batch, "account_id": account_id})
            records.update(_quote_records(payload))
        except (mcp_client.McpError, OSError, ValueError) as exc:
            errors.append(f"quote batch {start // QUOTE_BATCH_SIZE + 1} failed: {exc}")
    return records


def fetch_treasury_rate(asof_date=None, timeout=20):
    """Return latest available daily 3-month Treasury par yield as a decimal."""
    asof_date = asof_date or date.today()
    query = urllib.parse.urlencode({"data": "daily_treasury_yield_curve",
                                    "field_tdr_date_value": asof_date.year})
    request = urllib.request.Request(
        f"{RATE_URL}?{query}", headers={"User-Agent": "Amuse portfolio-risk snapshot"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        root = ET.fromstring(response.read())

    candidates = []
    for entry in root.iter():
        fields = {node.tag.rsplit("}", 1)[-1]: (node.text or "").strip()
                  for node in entry.iter()}
        raw_date, raw_yield = fields.get("NEW_DATE"), fields.get("BC_3MONTH")
        if not raw_date or not raw_yield or raw_yield.upper() in {"N/A", "NA"}:
            continue
        try:
            observation_date = datetime.fromisoformat(raw_date).date()
            percent = float(raw_yield)
        except (TypeError, ValueError):
            continue
        if observation_date <= asof_date and math.isfinite(percent):
            candidates.append((observation_date, percent / 100.0))
    if not candidates:
        raise ValueError("Treasury feed has no valid 3-month yield for this year")
    observation_date, rate = max(candidates)
    # Treasury records are date-only observations; midnight UTC is a date
    # marker, not a claim that the market published the rate at that instant.
    rate_asof = datetime(observation_date.year, observation_date.month,
                         observation_date.day, tzinfo=timezone.utc)
    return rate, rate_asof


def _open_legs(ledger, errors):
    if not isinstance(ledger, dict):
        errors.append("ledger must be a JSON object")
        return [], [], []
    positions = ledger.get("positions", [])
    if not isinstance(positions, list):
        errors.append("ledger positions must be a list")
        return [], [], []
    underlyings, osi_symbols = set(), set()
    leg_lookup = []
    for pos in positions:
        if not isinstance(pos, dict) or pos.get("status") != "open":
            continue
        underlying = pos.get("underlying")
        if not isinstance(underlying, str) or not underlying.strip():
            errors.append(f"position {pos.get('id', '?')}: underlying is missing")
            continue
        underlyings.add(underlying.strip())
        legs = pos.get("legs")
        if not isinstance(legs, list) or not legs:
            errors.append(f"position {pos.get('id', '?')}: legs are missing")
            continue
        for index, leg in enumerate(legs):
            if not isinstance(leg, dict):
                errors.append(f"position {pos.get('id', '?')} leg {index + 1}: invalid leg")
                continue
            osi = leg.get("osi") or leg.get("symbol")
            match = OSI_RE.fullmatch(osi) if isinstance(osi, str) else None
            if not match:
                errors.append(f"position {pos.get('id', '?')} leg {index + 1}: exact OSI symbol required")
                continue
            try:
                yy, mm, dd = int(match.group(2)[:2]), int(match.group(2)[2:4]), int(match.group(2)[4:6])
                osi_expiry = date(2000 + yy, mm, dd).isoformat()
                osi_type = "call" if match.group(3) == "C" else "put"
                osi_strike = int(match.group(4)) / 1000.0
                leg_strike = _positive(leg.get("strike"), "ledger strike")
            except (TypeError, ValueError):
                errors.append(f"position {pos.get('id', '?')} leg {index + 1}: ledger contract terms are invalid")
                continue
            if (osi_expiry != leg.get("expiry") or osi_type != str(leg.get("type", "")).lower()
                    or abs(osi_strike - leg_strike) > 0.0005):
                errors.append(f"{osi}: OSI does not match ledger type, strike, or expiration")
                continue
            root = re.sub(r"[^A-Z0-9]", "", match.group(1).upper())
            symbol_root = re.sub(r"[^A-Z0-9]", "", underlying.strip().upper())
            if root != symbol_root:
                errors.append(f"{osi}: OSI root does not match {underlying}; adjusted deliverables are unsupported")
                continue
            osi_symbols.add(osi)
            leg_lookup.append((underlying.strip(), osi))
    return sorted(underlyings), sorted(osi_symbols), leg_lookup


def collect_snapshot(ledger, account_id, now=None, rate_fetcher=fetch_treasury_rate,
                     quote_fetcher=None):
    """Build schema v1 snapshot; missing source observations remain explicit gaps."""
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    now = now.astimezone(timezone.utc)
    errors = []
    if not isinstance(account_id, str) or not account_id.strip():
        errors.append("PUBLIC_ACCOUNT_ID is required to request Public market data")
        account_id = ""
    else:
        account_id = account_id.strip()
    underlyings, osi_symbols, leg_lookup = _open_legs(ledger, errors)
    quotes = {}
    if account_id:
        quotes = (quote_fetcher or _quotes)(underlyings + osi_symbols,
                                             account_id, errors)

    contexts, contracts = {}, {}
    for symbol in underlyings:
        quote = quotes.get(symbol)
        if not isinstance(quote, dict):
            errors.append(f"{symbol}: underlying quote unavailable")
            continue
        try:
            spot = _positive(quote.get("last"), f"{symbol}.last")
            observed = _utc(quote.get("lastTimestamp"))
            contexts[symbol] = {
                "spot": spot,
                "spot_asof": observed.isoformat().replace("+00:00", "Z"),
            }
        except (TypeError, ValueError) as exc:
            errors.append(f"{symbol}: no timestamped last quote ({exc})")

    for _, osi in leg_lookup:
        quote = quotes.get(osi)
        if not isinstance(quote, dict):
            errors.append(f"{osi}: option quote unavailable")
            continue
        details = quote.get("optionDetails") or {}
        greeks = details.get("greeks") if isinstance(details, dict) else None
        if not isinstance(greeks, dict):
            errors.append(f"{osi}: option quote has no implied volatility")
            continue
        try:
            iv = _positive(greeks.get("impliedVolatility"), f"{osi}.impliedVolatility")
            if iv > 5:
                raise ValueError("IV must be <= 5.0 (500%)")
            observed = _utc(quote.get("lastTimestamp"))
            contracts[osi] = {"iv": iv,
                              "iv_asof": observed.isoformat().replace("+00:00", "Z")}
        except (TypeError, ValueError) as exc:
            errors.append(f"{osi}: no timestamped contract IV ({exc})")

    rate, rate_asof = None, None
    rate_source = "U.S. Treasury Daily Treasury Par Yield Curve, 3-month tenor"
    try:
        rate, rate_asof = rate_fetcher(asof_date=now.date())
    except (OSError, ValueError, ET.ParseError) as exc:
        errors.append(f"3-month Treasury rate unavailable: {exc}")

    return {
        "schema_version": 1,
        "source": "Public MCP quote observations + U.S. Treasury daily par yield curve",
        "asof": now.isoformat().replace("+00:00", "Z"),
        "risk_free_rate": rate,
        "risk_free_rate_asof": (rate_asof.isoformat().replace("+00:00", "Z")
                                 if rate_asof else None),
        "risk_free_rate_source": rate_source,
        "underlyings": contexts,
        "contracts": contracts,
        "collection_errors": errors,
        "assumptions": [
            "The 3-month Treasury par yield is a maturity proxy for the model risk-free rate.",
            "Dividend yield is not supplied by the source; the portfolio model's zero-yield default applies.",
            "The model assumes standard option deliverables and European exercise; corporate-action adjustments and early exercise are not modeled.",
            "Public option IV is bundled with its contract quote; its quote lastTimestamp is used as the observation timestamp.",
        ],
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--ledger", required=True, help="local position ledger JSON")
    ap.add_argument("--out", required=True, help="local market snapshot JSON")
    ap.add_argument("--account-id", default=None,
                    help="Public account ID (defaults to PUBLIC_ACCOUNT_ID environment variable)")
    args = ap.parse_args()
    with open(args.ledger, encoding="utf-8") as f:
        ledger = json.load(f)
    account_id = (args.account_id or os.environ.get("PUBLIC_ACCOUNT_ID", "")).strip()
    snapshot = collect_snapshot(ledger, account_id)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, indent=2)
        f.write("\n")
    print(json.dumps({"underlyings": len(snapshot["underlyings"]),
                      "contracts": len(snapshot["contracts"]),
                      "collection_errors": len(snapshot["collection_errors"]),
                      "out": args.out}, indent=2))
    if snapshot["collection_errors"]:
        print("Snapshot has missing inputs; portfolio-risk output will remain incomplete.",
              file=sys.stderr)


if __name__ == "__main__":
    main()
