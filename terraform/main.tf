# ARNs de bucket S3 são deriváveis diretamente do nome (sem sufixo aleatório),
# então computamos aqui como locals em vez de depender de outputs de módulo —
# isso quebra a dependência circular entre o módulo IAM (que precisa do ARN
# do bucket para a policy de escrita) e o módulo s3-warm-tier (que precisa do
# ARN da role IAM para a bucket policy).
locals {
  warm_tier_bucket_arn      = "arn:aws:s3:::${var.warm_tier_bucket_name}"
  athena_results_bucket_arn = "arn:aws:s3:::${var.athena_results_bucket_name}"
}

module "iam" {
  source = "./modules/iam"

  warm_tier_bucket_arn      = local.warm_tier_bucket_arn
  athena_results_bucket_arn = local.athena_results_bucket_arn
}

module "warm_tier" {
  source = "./modules/s3-warm-tier"

  bucket_name        = var.warm_tier_bucket_name
  collector_role_arn = module.iam.collector_role_arn
  tags               = var.tags
}

resource "aws_s3_bucket" "athena_results" {
  bucket = var.athena_results_bucket_name
  tags   = var.tags
}

resource "aws_s3_bucket_public_access_block" "athena_results" {
  bucket                  = aws_s3_bucket.athena_results.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

module "glue_catalog" {
  source = "./modules/glue-catalog"

  # Nomes de database Glue não aceitam hífen — normaliza o nome do ambiente.
  database_name       = "otel_cost_governance_${replace(var.environment, "-", "_")}"
  warm_tier_bucket_id = module.warm_tier.bucket_id
}

module "athena" {
  source = "./modules/athena"

  results_bucket_id = aws_s3_bucket.athena_results.id
  database_name     = module.glue_catalog.database_name
  table_name        = module.glue_catalog.table_name
}
