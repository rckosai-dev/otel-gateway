variable "region" {
  description = "Região AWS de destino. ap-northeast-1 (Tóquio) por padrão, dado o foco em mercado Japão do projeto."
  type        = string
  default     = "ap-northeast-1"
}

variable "environment" {
  description = "Nome do ambiente (ex.: sandbox-plan-only, staging, production) — vira sufixo/prefixo de nomes de recurso."
  type        = string
}

variable "warm_tier_bucket_name" {
  description = "Nome do bucket S3 usado como warm tier consultável (Parquet + Athena/Glue)."
  type        = string
}

variable "athena_results_bucket_name" {
  description = "Bucket separado para resultados de query do Athena (nunca reaproveitar o bucket de dados)."
  type        = string
}

variable "tags" {
  description = "Tags comuns aplicadas a todos os recursos, para reconciliar com o cost-center do showback."
  type        = map(string)
  default     = {}
}
