#!/usr/bin/env bash
# Local only: inputs and position-level evaluation outputs must not be published.
set -euo pipefail
cd "$(dirname "$0")/.."

if [[ $# -lt 1 || $# -gt 3 ]]; then
  echo "usage: bash bin/evaluate-historical-exits.sh INPUT.json [MAX_QUOTE_LAG_MINUTES] [MAX_GAP_HOURS]" >&2
  exit 2
fi

INPUT=$1
MAX_QUOTE_LAG=${2:-5}
MAX_GAP=${3:-72}
STAMP=$(date -u +%F-%H%M%S)
mkdir -p reports
OUT="reports/local-historical-exit-evaluation-$STAMP.json"

python3 src/historical_exit_evaluator.py \
  --input "$INPUT" --out "$OUT" \
  --max-quote-lag-minutes "$MAX_QUOTE_LAG" \
  --max-gap-hours "$MAX_GAP"
echo "Local historical exit evaluation: $OUT"
