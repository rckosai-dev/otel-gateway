#!/usr/bin/env bash
# Checklist de validação end-to-end descrito em docs/runbook.md e no plano do
# projeto. Requer `make up` já rodando. Não substitui `make load` — rode a
# carga sintética antes para ter dados nos passos 3-6.
set -uo pipefail

fail=0
check() {
  local desc="$1"; shift
  if "$@" >/dev/null 2>&1; then
    echo "[OK]   $desc"
  else
    echo "[FAIL] $desc"
    fail=1
  fi
}

check "Grafana responde"        curl -sf http://localhost:3000/api/health
check "Prometheus está healthy" curl -sf http://localhost:9090/-/healthy
check "MinIO console responde"  curl -sf http://localhost:9001
check "Collector health_check"  curl -sf http://localhost:13133
check "Collector self-telemetry (:8888/metrics)" curl -sf http://localhost:8888/metrics
check "Collector métricas de negócio (:8889/metrics)" curl -sf http://localhost:8889/metrics

echo
echo "Verificação de dados (requer \`make load\` já ter rodado):"
check "Recording rules de custo carregadas no Prometheus" \
  bash -c "curl -sf http://localhost:9090/api/v1/rules | grep -q 'otel-cost-governance'"

if [ "$fail" -ne 0 ]; then
  echo
  echo "Alguns checks falharam — veja docs/runbook.md para troubleshooting."
  exit 1
fi

echo
echo "Todos os checks básicos passaram. Rode 'make cost-report' e abra"
echo "http://localhost:3000/d/otel-cost-showback para validar os números."
