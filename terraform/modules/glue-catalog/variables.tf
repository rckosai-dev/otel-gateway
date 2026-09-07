variable "database_name" {
  type = string
}

variable "warm_tier_bucket_id" {
  type = string
}

variable "table_s3_prefix" {
  description = "Prefixo dentro do bucket onde os arquivos Parquet particionados vivem."
  type        = string
  default     = "processed/"
}
