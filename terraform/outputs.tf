output "warm_tier_bucket_id" {
  value = module.warm_tier.bucket_id
}

output "collector_role_arn" {
  value = module.iam.collector_role_arn
}

output "glue_database_name" {
  value = module.glue_catalog.database_name
}

output "athena_workgroup_name" {
  value = module.athena.workgroup_name
}
