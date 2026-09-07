# Bucket do warm tier — dados roteados pela política (telemetry.tier=warm)
# via awss3exporter, e depois reorganizados em Parquet particionado pelo job
# de ETL (scripts/parquetize.py) para consulta via Athena/Glue.
#
# Layout de prefixos:
#   otel/...                                    <- objetos brutos (OTLP JSON) do exporter, intermediários
#   processed/cost_center=<cc>/dt=<yyyy-mm-dd>/service_name=<svc>/*.parquet  <- consultável via Athena

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

  # Objetos brutos são intermediários — o job de parquetização os consome e
  # produz o dado consultável em processed/; não precisam viver muito.
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

  # Dado consultável (Parquet particionado): esfria com o tempo, como
  # qualquer warm tier de observability — consulta ocasional, não real-time.
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
