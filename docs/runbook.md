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
available — syntax validation (docker-compose, Terraform via `fmt`,
Python, dashboard JSON) was done statically, but a full end-to-end run of
`docker-compose.yml` (bringing up the stack, generating real load,
confirming data in Grafana/MinIO) **was not executed in this environment**
and should be validated by whoever runs the project locally with Docker
available, following the flow above.
