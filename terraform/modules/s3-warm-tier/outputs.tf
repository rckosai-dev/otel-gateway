output "bucket_id" {
  value = aws_s3_bucket.warm_tier.id
}

output "bucket_arn" {
  value = aws_s3_bucket.warm_tier.arn
}
