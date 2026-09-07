variable "bucket_name" {
  type = string
}

variable "collector_role_arn" {
  type = string
}

variable "tags" {
  type    = map(string)
  default = {}
}
