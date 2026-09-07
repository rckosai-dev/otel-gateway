# Warm-tier bucket — data routed by the policy (telemetry.tier=warm) via
# awss3exporter, later reorganized into partitioned Parquet by the ETL job
# (scripts/parquetize.py) for querying via Athena/Glue.
#
# Prefix layout:
#   otel/...                                    <- raw (OTLP JSON) objects from the exporter, intermediate
#   processed/cost_center=<cc>/dt=<yyyy-mm-dd>/service_name=<svc>/*.parquet  <- queryable via Athena

resource "aws_s3_bucket" "warm_tier" {
  bucket = var.bucket_name
  tags   = var.tags
}

resource "aws_s3_bucket_versioning" "warm_tier" {
  bucket = aws_s3_bucket.warm_tier.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_public_access_block" "warm_tier" {
  bucket                  = aws_s3_bucket.warm_tier.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_lifecycle_configuration" "warm_tier" {
  bucket = aws_s3_bucket.warm_tier.id

  # Raw objects are intermediate — the parquetization job consumes them and
  # produces the queryable data in processed/; they don't need to live long.
  rule {
    id     = "expire-raw-intermediate"
    status = "Enabled"
    filter {
      prefix = "otel/"
    }
    expiration {
      days = 7
    }
  }

  # Queryable data (partitioned Parquet): cools down over time, like any
  # observability warm tier — occasional queries, not real-time.
  rule {
    id     = "cool-down-processed"
    status = "Enabled"
    filter {
      prefix = "processed/"
    }
    transition {
      days          = 30
      storage_class = "STANDARD_IA"
    }
    transition {
      days          = 90
      storage_class = "GLACIER"
    }
    expiration {
      days = 365
    }
  }
}

data "aws_iam_policy_document" "warm_tier_write" {
  statement {
    sid    = "CollectorWriteOnly"
    effect = "Allow"
    principals {
      type        = "AWS"
      identifiers = [var.collector_role_arn]
    }
    actions   = ["s3:PutObject"]
    resources = ["${aws_s3_bucket.warm_tier.arn}/otel/*"]
  }

  statement {
    sid    = "DenyInsecureTransport"
    effect = "Deny"
    principals {
      type        = "*"
      identifiers = ["*"]
    }
    actions   = ["s3:*"]
    resources = [aws_s3_bucket.warm_tier.arn, "${aws_s3_bucket.warm_tier.arn}/*"]
    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }
}

resource "aws_s3_bucket_policy" "warm_tier" {
  bucket = aws_s3_bucket.warm_tier.id
  policy = data.aws_iam_policy_document.warm_tier_write.json
}
