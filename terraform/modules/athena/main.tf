# Workgroup + queries de exemplo para os dois padrões de consulta do warm
# tier documentados em docs/runbook.md: (a) investigação de incidente por
# serviço/janela de tempo, (b) reconstrução de custo/auditoria por
# time/cost-center. Nunca aponte result_configuration para o mesmo bucket
# dos dados — Athena cobra por TB escaneado, então os resultados de query
# (pequenos) ficam isolados dos dados particionados (grandes).

resource "aws_athena_workgroup" "cost_governance" {
  name = var.workgroup_name

  configuration {
    enforce_workgroup_configuration    = true
    publish_cloudwatch_metrics_enabled = true

    result_configuration {
      output_location = "s3://${var.results_bucket_id}/athena-results/"
    }
  }
}

resource "aws_athena_named_query" "incident_investigation" {
  name      = "incident-investigation-by-service"
  workgroup = aws_athena_workgroup.cost_governance.id
  database  = var.database_name
  query     = <<-SQL
    -- Padrão (a): investigação de incidente — logs/traces warm de um
    -- serviço numa janela de tempo, sem precisar reingerir no backend caro.
    -- Particionamento por service_name/dt torna isto barato mesmo em
    -- volumes grandes (Athena cobra por TB escaneado).
    SELECT ts, signal_type, severity, status_code, trace_id, body
    FROM ${var.table_name}
    WHERE service_name = 'checkout-api'
      AND dt = '2026-09-07'
    ORDER BY ts DESC
    LIMIT 200;
  SQL
}

resource "aws_athena_named_query" "cost_reconstruction" {
  name      = "cost-reconstruction-by-team"
  workgroup = aws_athena_workgroup.cost_governance.id
  database  = var.database_name
  query     = <<-SQL
    -- Padrão (b): reconstrução de custo por time/cost-center no fim do
    -- período, cruzando volume warm real armazenado com o custo por GB
    -- (mesmo modelo usado no dashboard de showback, ver docs/cost-model.md).
    SELECT cost_center, dt, COUNT(*) AS records
    FROM ${var.table_name}
    WHERE dt BETWEEN '2026-09-01' AND '2026-09-30'
    GROUP BY cost_center, dt
    ORDER BY cost_center, dt;
  SQL
}
