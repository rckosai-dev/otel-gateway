.PHONY: compile-policy up down load logs validate-terraform validate check-parquet cost-report

compile-policy:
	python3 policy-compiler/compile.py

# Recompila aplicando o downgrade dinâmico de budget, consultando o Prometheus
# já em execução (poor-man's OpAMP — ver docs/architecture.md). Requer `make up`
# rodando há tempo suficiente para acumular volume.
recompile-policy-with-budget:
	python3 policy-compiler/compile.py --prometheus-url http://localhost:9090
	docker compose restart otel-gateway-collector

up: compile-policy
	docker compose up -d
	@echo "Grafana:    http://localhost:3000 (admin/admin por padrão)"
	@echo "Prometheus: http://localhost:9090"
	@echo "MinIO:      http://localhost:9001"

down:
	docker compose down

load:
	docker compose --profile load run --rm telemetry-generator --profile steady --duration 300

load-smoke:
	docker compose --profile load run --rm telemetry-generator --profile smoke --duration 30

logs:
	docker compose logs -f otel-gateway-collector

check-parquet:
	python3 scripts/check-minio-parquet.py

cost-report:
	bash scripts/cost-report.sh

validate-terraform:
	cd terraform && terraform init -backend=false -input=false && \
	terraform validate && terraform fmt -check -recursive

validate: compile-policy validate-terraform
	bash scripts/validate-e2e.sh
