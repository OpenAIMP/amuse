#!/usr/bin/env bash
# Local only: position-level records must not be committed or published.
set -euo pipefail
cd "$(dirname "$0")/.."

if [[ $# -lt 2 || $# -gt 3 ]]; then
  echo "usage: bin/manage-positions.sh LEDGER.json MARKS.json [MAX_AGE_MINUTES]" >&2
  exit 2
fi

LEDGER=$1
MARKS=$2
MAX_AGE=${3:-30}
STAMP=$(date -u +%F-%H%M%S)
mkdir -p reports
python3 src/position_manager.py \
  --ledger "$LEDGER" \
  --marks "$MARKS" \
  --max-age-minutes "$MAX_AGE" \
  --out "reports/position-management-$STAMP.json" \
  --markdown-out "reports/position-management-$STAMP.md"
echo "Local position review: reports/position-management-$STAMP.md"
