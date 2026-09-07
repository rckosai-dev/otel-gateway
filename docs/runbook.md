# Runbook — rodar e validar a demo localmente

## Pré-requisitos

- Docker + Docker Compose v2
- Python 3.11+ (para `policy-compiler` e `scripts/`)
- `pip install -r policy-compiler/requirements.txt -r scripts/requirements.txt`

## Quickstart

```bash
cp .env.example .env
make up          # compila a política e sobe todo o stack
make load-smoke  # carga curta (30s) só para verificar que está tudo conectado
```

Endpoints:
- Grafana: http://localhost:3000 (admin/admin por padrão)
- Prometheus: http://localhost:9090
- MinIO console: http://localhost:9001

## Fluxo completo de validação (M1 → M4)

```bash
# 1. Stack sobe healthy
docker compose ps

# 2. Bucket warm-tier existe
docker compose exec minio mc alias set local http://localhost:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD"
docker compose exec minio mc ls local/warm-tier

# 3. Carga sintética por alguns minutos
make load

# 4. Hot tier — Grafana Explore
#    - Tempo: procure spans de checkout-api/payment-gateway com erro
#    - Loki: {service_name="payment-gateway"} |= "ERROR"

# 5. Warm tier — objetos brutos no MinIO, depois parquetização
docker compose exec minio mc ls --recursive local/warm-tier/otel/
python3 scripts/parquetize.py --endpoint-url http://localhost:9000 --bucket warm-tier
python3 scripts/check-minio-parquet.py --endpoint-url http://localhost:9000 --bucket warm-tier

# 6. Métricas de custo/drop
curl -s localhost:8888/metrics | grep otelcol_processor_dropped
bash scripts/cost-report.sh

# 7. Dashboard
#    http://localhost:3000/d/otel-cost-showback
#    - "Economia por drop" > 0 para recommendation-engine/batch-etl-job
#    - "Custo residual" concentrado em checkout-api/payment-gateway/auth-service

# 8. Downgrade dinâmico de budget (opcional, requer volume acumulado)
make recompile-policy-with-budget

# 9. Terraform (sintaxe apenas — nunca apply neste ambiente)
make validate-terraform
```

Ou, de forma resumida: `bash scripts/validate-e2e.sh` roda os checks
básicos de saúde (passos 1, 4 parcial, 6 parcial).

## Consultando o warm tier depois (Athena real, ou local via DuckDB)

Localmente, sem AWS, você pode consultar os arquivos Parquet direto com
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

Em produção (AWS real), as mesmas perguntas seriam feitas via Athena usando
as named queries em `terraform/modules/athena/main.tf`
(`incident-investigation-by-service`, `cost-reconstruction-by-team`).

## Troubleshooting

| Sintoma | Causa provável |
|---|---|
| Collector não sobe / restart loop | `otelcol-config.generated.yaml` desatualizado — rode `make compile-policy` |
| Prometheus não carrega rules | `prometheus/rules/cost-rules.generated.yaml` ausente — rode `make compile-policy` |
| `make load` trava por muito tempo | Collector não está no ar ainda — confira `docker compose ps` antes de gerar carga |
| Nenhum dado no dashboard | Rode `make load` por pelo menos 1-2 minutos antes de checar o Grafana |
| `terraform validate` falha por rede | Ambiente sem acesso a `registry.terraform.io` — rode localmente com internet normal |

## Limitações conhecidas deste ambiente de desenvolvimento

Este projeto foi desenvolvido num sandbox remoto sem daemon Docker
disponível — a validação de sintaxe (docker-compose, Terraform via `fmt`,
Python, JSON dos dashboards) foi feita estaticamente, mas a execução
end-to-end completa do `docker-compose.yml` (subir o stack, gerar carga real,
confirmar dados no Grafana/MinIO) **não foi executada neste ambiente** e deve
ser validada por quem rodar o projeto localmente com Docker disponível,
seguindo o fluxo acima.
