#!/usr/bin/env bash
# Quick cost/saving snapshot via the Prometheus API, no need to open
# Grafana — handy for pasting numbers into the article/PR.
set -euo pipefail

PROM_URL="${PROM_URL:-http://localhost:9090}"

query() {
  local expr="$1"
  curl -sS --get "${PROM_URL}/api/v1/query" --data-urlencode "query=${expr}" \
    | python3 -c "
import json, sys
data = json.load(sys.stdin)
for r in data.get('data', {}).get('result', []):
    print(' ', r['metric'], '=>', r['value'][1])
"
}

echo "== Residual cost by service/tier (USD) =="
query 'cost:residual_usd:by_service_tier'

echo
echo "== Downgrade saving hot->warm (USD) =="
query 'cost:downgrade_saving_usd:by_service'

echo
echo "== Drop saving (USD) =="
query 'cost:drop_saving_usd:by_service'

echo
echo "== Services currently over budget =="
query 'policy:over_budget:by_service == 1'
