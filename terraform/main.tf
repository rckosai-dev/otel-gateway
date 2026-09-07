# S3 bucket ARNs are derivable directly from the name (no random suffix),
# so we compute them here as locals instead of depending on module outputs
# — this breaks the circular dependency between the IAM module (which needs
# the bucket ARN for the write policy) and the s3-warm-tier module (which
# needs the IAM role ARN for the bucket policy).
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

  # Glue database names don't accept hyphens — normalize the environment name.
  database_name       = "otel_cost_governance_${replace(var.environment, "-", "_")}"
  warm_tier_bucket_id = module.warm_tier.bucket_id
}

module "athena" {
  source = "./modules/athena"

  results_bucket_id = aws_s3_bucket.athena_results.id
  database_name     = module.glue_catalog.database_name
  table_name        = module.glue_catalog.table_name
}
