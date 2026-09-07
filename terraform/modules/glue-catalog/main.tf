# Catálogo Glue sobre o warm tier (Parquet particionado), consultável via
# Athena. Simplificação deliberada de demo: logs/traces/metrics roteados
# para warm compartilham UMA tabela genérica de "registros" (signal_type
# diferencia o tipo); em produção real, tabelas separadas por sinal
# tendem a compensar o custo extra de manutenção com queries mais simples —
# ver docs/cost-model.md.
#
# Particionamento: cost_center / dt / service_name — otimizado para os dois
# padrões de consulta mais comuns (investigação de incidente por serviço, e
# reconstrução de custo/auditoria por time no fim do período).

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
