# Runbook — running and validating the demo locally

## Prerequisites

- Docker + Docker Compose v2
- Python 3.11+ (for `policy-compiler` and `scripts/`)
- `pip install -r policy-compiler/requirements.txt -r scripts/requirements.txt`

## Quickstart

```bash
cp .env.example .env
make up          # compiles the policy and brings up the whole local stack
make load-smoke  # short load run (30s) just to check everything's wired up
```

Endpoints:
- Grafana: http://localhost:3000 (admin/admin by default)
- Prometheus: http://localhost:9090
- MinIO console: http://localhost:9001

## Full validation flow (M1 → M4)

```bash
# 1. Stack comes up healthy
docker compose ps

# 2. warm-tier bucket exists
docker compose exec minio mc alias set local http://localhost:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD"
docker compose exec minio mc ls local/warm-tier

# 3. Synthetic load for a few minutes
make load

# 4. Hot tier — Grafana Explore
#    - Tempo: look for error spans from checkout-api/payment-gateway
#    - Loki: {service_name="payment-gateway"} |= "ERROR"

# 5. Warm tier — raw objects in MinIO, then parquetization
docker compose exec minio mc ls --recursive local/warm-tier/otel/
python3 scripts/parquetize.py --endpoint-url http://localhost:9000 --bucket warm-tier
python3 scripts/check-minio-parquet.py --endpoint-url http://localhost:9000 --bucket warm-tier

# 6. Cost/drop metrics
curl -s localhost:8888/metrics | grep otelcol_processor_dropped
bash scripts/cost-report.sh

# 7. Dashboard
#    http://localhost:3000/d/otel-cost-showback
#    - "Drop saving" > 0 for recommendation-engine/batch-etl-job
#    - "Residual cost" concentrated in checkout-api/payment-gateway/auth-service

# 8. Dynamic budget downgrade (optional, requires accumulated volume)
make recompile-policy-with-budget

# 9. Terraform (syntax only — never apply in this environment)
make validate-terraform
```

Or, more concisely: `bash scripts/validate-e2e.sh` runs the basic health
checks (steps 1, part of 4, part of 6).

## Querying the warm tier later (real Athena, or locally via DuckDB)

Locally, without AWS, you can query the Parquet files directly with
DuckDB:

```bash
pip install duckdb
python3 -c "
import duckdb
con = duckdb.connect()
con.execute(\"INSTALL httpfs; LOAD httpfs;\")
con.execute(\"SET s3_endpoint='localhost:9000'; SET s3_use_ssl=false; SET s3_url_style='path';\")
print(con.execute(\"SELECT * FROM read_parquet('s3://warm-tier/processed/**/*.parquet') LIMIT 10\").fetchdf())
"
```

In production (real AWS), the same questions would be asked via Athena
using the named queries in `terraform/modules/athena/main.tf`
(`incident-investigation-by-service`, `cost-reconstruction-by-team`).

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| Collector won't start / restart loop | `otelcol-config.generated.yaml` is stale — run `make compile-policy` |
| Prometheus fails to load rules | `prometheus/rules/cost-rules.generated.yaml` is missing — run `make compile-policy` |
| `make load` hangs for a long time | Collector isn't up yet — check `docker compose ps` before generating load |
| No data in the dashboard | Run `make load` for at least 1-2 minutes before checking Grafana |
| `terraform validate` fails due to network | Environment has no access to `registry.terraform.io` — run it locally with normal internet access |

## Known limitations of this development environment

This project was developed in a remote sandbox with no Docker daemon
available. What **was** actually validated here, directly against the
real `otelcol-contrib` v0.102.1 binary (the exact version pinned in
`docker-compose.yml`), downloaded and run standalone (not via compose):

- `otelcol-contrib validate --config=collector/config/otelcol-config.generated.yaml`
  passes.
- Running the binary directly, it builds all pipelines and reaches
  "Everything is ready" — this is what caught two real OTTL bugs
  (`resource.attributes[...]` used inside a context that was already
  `resource`, and `metric.name` instead of `name` inside `context: metric`)
  that static YAML/schema validation could not have caught, since they're
  errors in the *content* of OTTL expression strings, not the YAML shape.
- Feeding it real OTLP traffic from `telemetry-generator` end to end
  confirmed the routing decision and the cost-showback count connectors:
  `logs_count_by_service_total`/`spans_count_by_service_total`/
  `datapoints_count_by_service_total` came out on `:8889` with correct
  `service_name`/`team`/`cost_center`/`telemetry_tier` labels, and the
  values matched the routing policy's intent (e.g. `recommendation-engine`
  and `batch-etl-job` concentrating `telemetry_tier="drop"`;
  `payment-gateway`/`auth-service`, both `compliance_hold`, never
  appearing as `drop`). This is also what caught a second real bug: the
  `countconnector` only reads attributes off the item itself (LogRecord/
  Span/DataPoint), never off the Resource, and silently drops a named
  metric entirely if any configured attribute is missing.

What was **not** validated in this environment, and needs a real
`docker compose up` locally to confirm:

- The full multi-container stack coming up together (network, volumes,
  healthcheck ordering) — only the Collector binary was run standalone.
- Data actually landing in Loki/Tempo (the `otlphttp/loki` and
  `otlp/tempo` exporters only got as far as "backend unreachable," since
  those containers weren't running in the standalone test).
- Objects actually landing in MinIO via `awss3/warm`, and the
  `parquetize.py`/`check-minio-parquet.py` scripts against real objects.
- The Grafana dashboards actually rendering with real data.
- `terraform plan`/`apply` against real AWS credentials.

Follow the flow above to validate those; report back anything that still
breaks — the OTTL and countconnector fixes above were both found this way
(by actually running the real binary against real traffic, not by
reading the config), so it's the fastest way to catch anything left.
