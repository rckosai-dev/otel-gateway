# Glue catalog over the warm tier (partitioned Parquet), queryable via
# Athena. Deliberate demo simplification: logs/traces/metrics routed to
# warm share ONE generic "records" table (signal_type differentiates the
# type); in real production, separate tables per signal tend to offset the
# extra maintenance cost with simpler queries — see docs/cost-model.md.
#
# Partitioning: cost_center / dt / service_name — optimized for the two
# most common query patterns (per-service incident investigation, and
# cost/audit reconstruction by team at period end).

resource "aws_glue_catalog_database" "warm_tier" {
  name = var.database_name
}

resource "aws_glue_catalog_table" "warm_records" {
  name          = "warm_records"
  database_name = aws_glue_catalog_database.warm_tier.name
  table_type    = "EXTERNAL_TABLE"

  parameters = {
    "classification"   = "parquet"
    "parquet.compress" = "SNAPPY"
  }

  storage_descriptor {
    location      = "s3://${var.warm_tier_bucket_id}/${var.table_s3_prefix}"
    input_format  = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetInputFormat"
    output_format = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetOutputFormat"

    ser_de_info {
      serialization_library = "org.apache.hadoop.hive.ql.io.parquet.serde.ParquetHiveSerDe"
    }

    columns {
      name = "ts"
      type = "bigint"
    }
    columns {
      name = "signal_type"
      type = "string"
    }
    columns {
      name = "team"
      type = "string"
    }
    columns {
      name = "telemetry_tier"
      type = "string"
    }
    columns {
      name = "severity"
      type = "string"
    }
    columns {
      name = "trace_id"
      type = "string"
    }
    columns {
      name = "span_id"
      type = "string"
    }
    columns {
      name = "status_code"
      type = "string"
    }
    columns {
      name = "body"
      type = "string"
    }
    columns {
      name = "policy_version"
      type = "string"
    }
  }

  partition_keys {
    name = "cost_center"
    type = "string"
  }
  partition_keys {
    name = "dt"
    type = "string"
  }
  partition_keys {
    name = "service_name"
    type = "string"
  }
}
