variable "database_name" {
  type = string
}

variable "warm_tier_bucket_id" {
  type = string
}

variable "table_s3_prefix" {
  description = "Prefix within the bucket where the partitioned Parquet files live."
  type        = string
  default     = "processed/"
}
