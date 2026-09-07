# Example/fake values — used only for `terraform validate`/`terraform fmt`
# in this demo environment. NEVER run `terraform apply` with these values:
# there are no AWS credentials configured in the sandbox, and the bucket
# names below are neither reserved nor exclusive.

environment                = "sandbox-plan-only"
region                     = "ap-northeast-1"
warm_tier_bucket_name      = "otel-cost-gov-demo-warm-tier"
athena_results_bucket_name = "otel-cost-gov-demo-athena-results"

tags = {
  project     = "otel-telemetry-cost-governance"
  environment = "sandbox-plan-only"
  managed_by  = "terraform"
}
