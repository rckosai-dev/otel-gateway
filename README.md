# otel-gateway — otel-telemetry-cost-governance

A **vendor-neutral telemetry cost governance** architecture built on the
OpenTelemetry Collector: routing by value (hot/warm/drop) decided by a
centralized, versioned policy — not configuration scattered across
collectors —, with cost showback by service/cost-center and retention as
code.

See the full article at [`docs/article.md`](docs/article.md) and the
detailed architecture at [`docs/architecture.md`](docs/architecture.md).

## What's in here

- **`policy/`** — service catalog, routing matrix, and cost budgets. The
  single source of truth, versioned in Git.
- **`policy-compiler/`** — compiles the policy into real Collector config
  (OTTL) + Prometheus cost recording rules.
- **`collector/`** — Gateway Collector: tagging, routing (`routingconnector`),
  `tail_sampling`, counting by service/team/cost_center.
- **`telemetry-generator/`** — synthetic load (8 services, a realistic
  criticality/volume/error mix) to exercise routing without real data.
- **`dashboards/` + `prometheus/rules/`** — cost showback (downgrade
  saving, drop saving, residual cost) and pipeline health, as code.
- **`terraform/`** — real AWS infrastructure for the warm tier (S3 + Glue +
  Athena + IAM), written but not applied in this demo environment.
- **`docs/`** — architecture, routing-policy rationale, cost model,
  operational runbook, and the article.

## Quickstart

```bash
cp .env.example .env
pip install -r policy-compiler/requirements.txt -r scripts/requirements.txt
make up          # compiles the policy and brings up the full local stack (Docker)
make load-smoke  # short load run to check end-to-end connectivity
```

Then: Grafana at http://localhost:3000, Prometheus at
http://localhost:9090, MinIO at http://localhost:9001. Full validation
flow in [`docs/runbook.md`](docs/runbook.md).

## State of this development environment

This project was built in a sandbox with no Docker daemon available, so
the full `docker-compose.yml` stack (Grafana/Loki/Tempo/Prometheus/MinIO
together) has not been exercised end to end here. That said, the Collector
config itself **was** validated against the real thing: the pinned
`otelcol-contrib` v0.102.1 binary was downloaded and run directly against
`collector/config/otelcol-config.generated.yaml`, fed real OTLP traffic
from `telemetry-generator`, and confirmed to route and count correctly
(see [`docs/runbook.md`](docs/runbook.md#known-limitations-of-this-development-environment)
for exactly what that did and didn't cover). Run the quickstart above
locally with Docker available to validate the full stack (Grafana
dashboards, Loki/Tempo/MinIO actually receiving data, Terraform apply).
