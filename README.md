# otel-gateway — otel-telemetry-cost-governance

Arquitetura de **governança de custo de telemetria vendor-neutral**, construída
sobre o OpenTelemetry Collector: roteamento por valor (hot/warm/drop) decidido
por uma política centralizada e versionada — não configuração dispersa por
collector —, com showback de custo por serviço/cost-center e retenção como
código.

Ver o artigo completo em [`docs/article.md`](docs/article.md) e a arquitetura
detalhada em [`docs/architecture.md`](docs/architecture.md).

## O que tem aqui

- **`policy/`** — catálogo de serviços, matriz de roteamento e budgets de
  custo. Fonte de verdade única, versionada em Git.
- **`policy-compiler/`** — compila a política em config real do Collector
  (OTTL) + recording rules de custo do Prometheus.
- **`collector/`** — Gateway Collector: tagging, roteamento (`routingconnector`),
  `tail_sampling`, contagem por service/team/cost_center.
- **`telemetry-generator/`** — carga sintética (8 serviços, mix realista de
  criticidade/volume/erro) para exercitar o roteamento sem dados reais.
- **`dashboards/` + `prometheus/rules/`** — showback de custo (downgrade
  saving, drop saving, custo residual) e saúde do pipeline, como código.
- **`terraform/`** — infraestrutura AWS real do warm tier (S3 + Glue + Athena
  + IAM), escrita mas não aplicada neste ambiente de demo.
- **`docs/`** — arquitetura, racional da política de roteamento, modelo de
  custo, runbook operacional, e o artigo.

## Quickstart

```bash
cp .env.example .env
pip install -r policy-compiler/requirements.txt -r scripts/requirements.txt
make up          # compila a política e sobe todo o stack local (Docker)
make load-smoke  # carga curta para verificar conectividade ponta a ponta
```

Depois: Grafana em http://localhost:3000, Prometheus em
http://localhost:9090, MinIO em http://localhost:9001. Fluxo completo de
validação em [`docs/runbook.md`](docs/runbook.md).

## Estado deste ambiente de desenvolvimento

Este projeto foi construído num sandbox sem daemon Docker disponível — toda
a lógica (policy-compiler, telemetry-generator, parsing de OTLP JSON) foi
testada isoladamente, sintaxe de Terraform/docker-compose/JSON validada
estaticamente, mas a execução end-to-end completa do stack via
`docker-compose.yml` **ainda não foi executada**. Rode o quickstart acima
localmente com Docker disponível para validar de ponta a ponta — ver
[`docs/runbook.md`](docs/runbook.md#limitações-conhecidas-deste-ambiente-de-desenvolvimento).
