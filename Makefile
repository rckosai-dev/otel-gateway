.PHONY: compile-policy up down load logs validate-terraform validate check-parquet cost-report \
        policy-editor new-rule policy-validate policy-tests deploy-dev deploy-uat \
        rollback-dev rollback-uat smoke ledger

compile-policy:
	python3 policy-compiler/compile.py

# --- Authoring: create/validate governance rules -----------------------------
# Visual editor (static, offline): serves the repo so the editor can read the
# policy files, then open http://localhost:8000/tools/policy-editor/
policy-editor:
	@echo "Open http://localhost:8000/tools/policy-editor/  (Ctrl-C to stop)"
	python3 -m http.server 8000

# Interactive rule wizard (or use: policyctl new-rule --from-json rule.json --before <id>)
new-rule:
	python3 policy-compiler/policyctl.py new-rule

policy-validate:
	python3 policy-compiler/policyctl.py validate

policy-tests:
	python3 -m pytest policy-compiler/tests/ -q

# --- Promotion: dev / uat (traceability + rollback) --------------------------
# Local "apply": compile, (re)start the collector with the new config, and
# record the deployment in deployments/ledger.jsonl. In CI the uat stage is
# gated by a GitHub Environment approval (see .github/workflows/policy-uat.yml).
deploy-dev: compile-policy
	docker compose up -d
	docker compose restart otel-gateway-collector
	python3 policy-compiler/policyctl.py record-deploy --env dev
	@echo "dev deploy recorded — see 'make ledger'"

deploy-uat: compile-policy
	docker compose up -d
	docker compose restart otel-gateway-collector
	python3 policy-compiler/policyctl.py record-deploy --env uat
	@echo "uat deploy recorded — see 'make ledger'"

# Roll policy + generated artifacts back to a previous version and re-apply.
# Optionally target a specific version:  make rollback-uat TO=<policy.version|sha>
rollback-dev:
	python3 policy-compiler/policyctl.py rollback --env dev $(if $(TO),--to $(TO),)
	docker compose restart otel-gateway-collector

rollback-uat:
	python3 policy-compiler/policyctl.py rollback --env uat $(if $(TO),--to $(TO),)
	docker compose restart otel-gateway-collector

ledger:
	python3 policy-compiler/policyctl.py ledger

smoke:
	bash scripts/validate-e2e.sh

# Recompiles applying the dynamic budget downgrade, querying the already
# running Prometheus (poor man's OpAMP — see docs/architecture.md). Requires
# `make up` to have been running long enough to accumulate volume.
recompile-policy-with-budget:
	python3 policy-compiler/compile.py --prometheus-url http://localhost:9090
	docker compose restart otel-gateway-collector

up: compile-policy
	docker compose up -d
	@echo "Grafana:    http://localhost:3000 (admin/admin by default)"
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

validate: policy-validate policy-tests compile-policy validate-terraform
	bash scripts/validate-e2e.sh
