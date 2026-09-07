#!/usr/bin/env bash
# Snapshot rápido de custo/saving via API do Prometheus, sem precisar abrir o
# Grafana — útil para colar números no artigo/PR.
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

echo "== Custo residual por serviço/tier (USD) =="
query 'cost:residual_usd:by_service_tier'

echo
echo "== Economia por downgrade hot->warm (USD) =="
query 'cost:downgrade_saving_usd:by_service'

echo
echo "== Economia por drop (USD) =="
query 'cost:drop_saving_usd:by_service'

echo
echo "== Serviços atualmente over-budget =="
query 'policy:over_budget:by_service == 1'
