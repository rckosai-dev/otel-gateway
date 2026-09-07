# Workgroup + example queries for the two warm-tier query patterns
# documented in docs/runbook.md: (a) per-service/time-window incident
# investigation, (b) cost/audit reconstruction by team/cost-center. Never
# point result_configuration at the same bucket as the data — Athena
# charges by TB scanned, so the (small) query results stay isolated from
# the (large) partitioned data.

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
    -- Pattern (a): incident investigation — warm logs/traces for a
    -- service in a time window, with no need to re-ingest into the
    -- expensive backend. Partitioning by service_name/dt keeps this cheap
    -- even at large volumes (Athena charges by TB scanned).
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
    -- Pattern (b): cost reconstruction by team/cost-center at period end,
    -- cross-referencing real stored warm volume with cost per GB (the same
    -- model used in the showback dashboard, see docs/cost-model.md).
    SELECT cost_center, dt, COUNT(*) AS records
    FROM ${var.table_name}
    WHERE dt BETWEEN '2026-09-01' AND '2026-09-30'
    GROUP BY cost_center, dt
    ORDER BY cost_center, dt;
  SQL
}
