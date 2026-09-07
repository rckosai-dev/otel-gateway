variable "region" {
  description = "Target AWS region. ap-northeast-1 (Tokyo) by default, given the project's focus on the Japan market."
  type        = string
  default     = "ap-northeast-1"
}

variable "environment" {
  description = "Environment name (e.g., sandbox-plan-only, staging, production) — becomes a resource-name suffix/prefix."
  type        = string
}

variable "warm_tier_bucket_name" {
  description = "S3 bucket name used as the queryable warm tier (Parquet + Athena/Glue)."
  type        = string
}

variable "athena_results_bucket_name" {
  description = "Separate bucket for Athena query results (never reuse the data bucket)."
  type        = string
}

variable "tags" {
  description = "Common tags applied to all resources, to reconcile with the showback cost-center."
  type        = map(string)
  default     = {}
}
