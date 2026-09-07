#!/usr/bin/env bash
# End-to-end validation checklist described in docs/runbook.md and the
# project plan. Requires `make up` already running. Doesn't replace
# `make load` — run the synthetic load first to have data for steps 3-6.
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

check "Grafana responds"           curl -sf http://localhost:3000/api/health
check "Prometheus is healthy"      curl -sf http://localhost:9090/-/healthy
check "MinIO console responds"     curl -sf http://localhost:9001
check "Collector health_check"     curl -sf http://localhost:13133
check "Collector self-telemetry (:8888/metrics)" curl -sf http://localhost:8888/metrics
check "Collector business metrics (:8889/metrics)" curl -sf http://localhost:8889/metrics

echo
echo "Data verification (requires \`make load\` to have already run):"
check "Cost recording rules loaded in Prometheus" \
  bash -c "curl -sf http://localhost:9090/api/v1/rules | grep -q 'otel-cost-governance'"

if [ "$fail" -ne 0 ]; then
  echo
  echo "Some checks failed — see docs/runbook.md for troubleshooting."
  exit 1
fi

echo
echo "All basic checks passed. Run 'make cost-report' and open"
echo "http://localhost:3000/d/otel-cost-showback to validate the numbers."
