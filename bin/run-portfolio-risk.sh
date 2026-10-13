#!/usr/bin/env bash
# Local only: never publish a ledger or position-level risk report.
set -euo pipefail
cd "$(dirname "$0")/.."

if [[ $# -lt 1 || $# -gt 3 ]]; then
  echo "usage: bash bin/run-portfolio-risk.sh LEDGER.json [MAX_QUOTE_AGE_MINUTES] [MAX_RATE_AGE_DAYS]" >&2
  exit 2
fi
: "${PUBLIC_ACCOUNT_ID:?Set PUBLIC_ACCOUNT_ID in your local environment}"

LEDGER=$1
MAX_QUOTE_AGE=${2:-30}
MAX_RATE_AGE=${3:-7}
STAMP=$(date -u +%F-%H%M%S)
mkdir -p reports
MARKET="reports/private-market-context-$STAMP.json"
RISK="reports/private-portfolio-risk-$STAMP.json"

export PUBLIC_MCP_CLI="${PUBLIC_MCP_CLI:-$PWD/bin/public-mcp}"
python3 src/portfolio_context.py --ledger "$LEDGER" --out "$MARKET"
python3 src/portfolio_risk.py \
  --ledger "$LEDGER" --market "$MARKET" \
  --max-age-minutes "$MAX_QUOTE_AGE" \
  --max-rate-age-days "$MAX_RATE_AGE" \
  --out "$RISK"
echo "Local portfolio risk report: $RISK"
