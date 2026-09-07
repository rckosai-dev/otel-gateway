output "database_name" {
  value = aws_glue_catalog_database.warm_tier.name
}

output "table_name" {
  value = aws_glue_catalog_table.warm_records.name
}
