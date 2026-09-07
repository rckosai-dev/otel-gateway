terraform {
  required_version = ">= 1.5"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  # Backend local por padrão (adequado para `terraform plan`/`validate` no
  # sandbox de demo). Em produção, trocar para backend remoto com locking:
  #
  # backend "s3" {
  #   bucket         = "otel-cost-gov-tfstate"
  #   key            = "otel-telemetry-cost-governance/terraform.tfstate"
  #   region         = "ap-northeast-1"
  #   dynamodb_table = "otel-cost-gov-tfstate-lock"
  #   encrypt        = true
  # }
}

provider "aws" {
  region = var.region
}
