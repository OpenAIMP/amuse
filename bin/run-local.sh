#!/bin/bash
# Local pipeline runner — mirrors the GitHub Actions jobs without CI.
# Usage: bin/run-local.sh [daytrade|daily|monthly|all|test]
# Requires: PUBLIC_API_KEY set (export PUBLIC_API_KEY=...).
set -euo pipefail
cd "$(dirname "$0")/.."

need_key() {
  : "${PUBLIC_API_KEY:?export PUBLIC_API_KEY first (Public.com API key)}"
}
export PUBLIC_MCP_CLI="${PUBLIC_MCP_CLI:-$PWD/bin/public-mcp}"
chmod +x bin/public-mcp 2>/dev/null || true
mkdir -p reports docs/reports

STAMP=$(date -u +%F-%H%M)

run_daytrade() {
  need_key
  python3 src/daytrade_screen.py \
    --json-out "reports/daytrade-screen-$STAMP.json" \
    | tee "reports/daytrade-screen-$STAMP.txt"
  python3 src/render_report.py \
    --daytrade "reports/daytrade-screen-$STAMP.json" \
    --report-id "daytrade-sp500-$STAMP" --source sp500 \
    --source-detail "S&P 500" \
    --out "docs/reports/daytrade-sp500-$STAMP.html"
}

run_daily() {
  need_key
  WATCHLIST=$(grep -v '^#' src/watchlist.txt | grep -v '^$' | tr '\n' ',' | sed 's/,$//')
  python3 src/stock_screener.py --names "$WATCHLIST" \
    --json-out "reports/stock-screen-$STAMP.json" \
    | tee "reports/stock-screen-$STAMP.txt"
  python3 src/spread_screener.py --names "$WATCHLIST" \
    --json-out "reports/spread-screen-$STAMP.json" \
    | tee "reports/spread-screen-$STAMP.txt"
  python3 src/decision_engine.py \
    --stock "reports/stock-screen-$STAMP.json" \
    --spreads "reports/spread-screen-$STAMP.json" \
    --json-out "reports/decision-$STAMP.json" \
    --markdown-out "reports/decision-$STAMP.md"
  RISK_ARGS=()
  if [ -n "${PORTFOLIO_RISK_LEDGER:-}" ] && [ -n "${PORTFOLIO_RISK_MARKET:-}" ]; then
    python3 src/portfolio_risk.py \
      --ledger "$PORTFOLIO_RISK_LEDGER" \
      --market "$PORTFOLIO_RISK_MARKET" \
      --out "reports/portfolio-risk-$STAMP.json"
    RISK_ARGS+=(--portfolio-risk "reports/portfolio-risk-$STAMP.json")
  fi
  python3 src/render_report.py \
    --stock "reports/stock-screen-$STAMP.json" \
    --spreads "reports/spread-screen-$STAMP.json" \
    --decision "reports/decision-$STAMP.json" \
    "${RISK_ARGS[@]}" \
    --report-id "daily-watchlist-$STAMP" --source watchlist \
    --out "docs/reports/daily-watchlist-$STAMP.html"
}

run_monthly() {
  need_key
  WATCHLIST=$(grep -v '^#' src/watchlist.txt | grep -v '^$' | tr '\n' ',' | sed 's/,$//')
  python3 src/pmcc_quality.py --names "$WATCHLIST" \
    --json-out "reports/pmcc-quality-$STAMP.json" \
    | tee "reports/pmcc-quality-$STAMP.txt"
  python3 src/render_report.py \
    --pmcc "reports/pmcc-quality-$STAMP.json" \
    --report-id "pmcc-watchlist-$STAMP" --source watchlist \
    --out "docs/reports/pmcc-watchlist-$STAMP.html"
}

run_tests() {
  for t in tests/test_*.py; do
    echo "== $t"; python3 "$t" || exit 1
  done
}

case "${1:-all}" in
  daytrade) run_daytrade ;;
  daily)    run_daily ;;
  monthly)  run_monthly ;;
  test)     run_tests ;;
  all)      run_daytrade; run_daily; run_monthly ;;
  *) echo "usage: $0 [daytrade|daily|monthly|all|test]"; exit 1 ;;
esac

python3 src/render_hub.py --docs docs
echo "done — open docs/index.html"
