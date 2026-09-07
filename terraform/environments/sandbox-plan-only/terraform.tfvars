# Valores de exemplo/fake — usados só para `terraform validate`/`terraform fmt`
# neste ambiente de demo. NUNCA rode `terraform apply` com estes valores:
# não há credenciais AWS configuradas no sandbox, e os nomes de bucket abaixo
# não são reservados nem exclusivos.

environment                = "sandbox-plan-only"
region                     = "ap-northeast-1"
warm_tier_bucket_name      = "otel-cost-gov-demo-warm-tier"
athena_results_bucket_name = "otel-cost-gov-demo-athena-results"

tags = {
  project     = "otel-telemetry-cost-governance"
  environment = "sandbox-plan-only"
  managed_by  = "terraform"
}
