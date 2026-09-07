# Terraform — retention as code

This directory describes the real production infrastructure for the warm
tier (S3 + Glue + Athena + IAM) — the same architecture that
`docker-compose.yml` simulates locally with MinIO. **It is not applied in
this repository/sandbox.**

## What runs here, and what doesn't

| Command | Runs in the demo sandbox? | Requires real AWS credentials? |
|---|---|---|
| `terraform fmt -check -recursive` | Yes | No |
| `terraform init -backend=false` | Yes | No |
| `terraform validate` | Yes | No |
| `terraform plan` | No (no credentials in the environment) | Yes |
| `terraform apply` | **Never here** | Yes |

`make validate-terraform` (repo root) runs the first three. To actually run
`plan`/`apply`, use your own AWS credentials locally:

```bash
cd terraform
terraform init
terraform plan -var-file=environments/sandbox-plan-only/terraform.tfvars
```

## Why the bucket names in `environments/sandbox-plan-only/` are "fake"

S3 bucket names are globally unique. The values in `terraform.tfvars` are
just placeholders for syntax validation — replace them with real names
(likely already reserved by another account) before running a real
`plan`/`apply`.

## How this connects to the rest of the project

- `modules/s3-warm-tier`: the same bucket the `awss3exporter` writes to
  locally in MinIO (`docker-compose.yml`), here as real S3.
- `modules/glue-catalog` + `modules/athena`: schema and example queries
  for the same query pattern validated locally with `duckdb`
  (see `scripts/check-minio-parquet.py` and `docs/runbook.md`).
- `modules/iam`: separates the write identity (Collector) from the read
  identity (teams querying their own data) — least-privilege principle.

## Known limitation

`terraform fmt -check -recursive` and `terraform init -backend=false` were
run in this environment (`fmt` passed, formatting already fixed).
`terraform validate` **could not be run here**: the sandbox's network
policy blocks `registry.terraform.io` (required to download the
`hashicorp/aws` provider), so `terraform init` fails before it gets to
`validate`. The module syntax was reviewed manually against the documented
schema of the AWS provider ~> 5.0, but run `terraform validate` locally
(with normal internet access) before trusting it blindly.
