variable "role_name" {
  type    = string
  default = "otel-gateway-collector"
}

variable "warm_tier_bucket_arn" {
  type = string
}

variable "athena_results_bucket_arn" {
  type = string
}
