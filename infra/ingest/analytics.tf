# Workflow AnalisisDiario: plan preventivo, repuestos, combustible, productividad, KPIs y reporte ejecutivo.
# Cubre: RF-03, RF-04, RF-07, RF-08, RF-10.3, RF-11.4, MH-SFN-02. Dueño: Persona A (worker 3).
# Cada Lambda es un zip con su servicio + analytics_common; arquifusion_shared/ml vienen en la capa común.

locals {
  analytics_dir        = "${path.module}/../../services/analytics"
  analytics_common_dir = "${local.analytics_dir}/common"
  analytics_common_files = setunion(
    fileset(local.analytics_common_dir, "analytics_common/*.py"),
    fileset(local.analytics_common_dir, "analytics_common/sql/*.sql"),
  )

  analytics_lambdas = {
    preventivo = {
      description = "Plan preventivo por condición (RF-03)"
      env = {
        TABLE_MACHINES            = local.tables.machines
        TABLE_MAINTENANCE_RECORDS = local.tables.maintenance_records
        TABLE_CATALOG             = local.tables.catalog
        TABLE_INSIGHTS            = local.tables.insights
      }
    }
    repuestos = {
      description = "Ranking y pronóstico de repuestos (RF-04)"
      env = {
        TABLE_MACHINES            = local.tables.machines
        TABLE_MAINTENANCE_RECORDS = local.tables.maintenance_records
        TABLE_INVENTORY           = local.tables.inventory
        TABLE_CATALOG             = local.tables.catalog
        TABLE_WAREHOUSES          = local.tables.warehouses
        TABLE_INSIGHTS            = local.tables.insights
      }
    }
    combustible = {
      description = "Consumo de combustible vs pares e historial (RF-07)"
      env = {
        TABLE_CATALOG  = local.tables.catalog
        TABLE_INSIGHTS = local.tables.insights
      }
    }
    productividad = {
      description = "Utilización y matriz productividad x costo (RF-08)"
      env = {
        TABLE_MAINTENANCE_RECORDS = local.tables.maintenance_records
        TABLE_INSIGHTS            = local.tables.insights
      }
    }
    kpis_report = {
      description = "KPIs de flota y resumen ejecutivo IA (RF-10.3, RF-11.4)"
      env = {
        TABLE_MACHINES     = local.tables.machines
        TABLE_INCIDENTS    = local.tables.incidents
        TABLE_CATALOG      = local.tables.catalog
        TABLE_INSIGHTS     = local.tables.insights
        IA_GEMINI_FUNCTION = aws_lambda_function.ia_gemini.function_name
      }
    }
  }

  # SQL escapado para insertarlo dentro de un string JSON del ASL.
  # El SQL filtra `operation_id = 'OP-01'` (proyección injected, #10); aquí se fija la operación del stage.
  sql_daily_stats = trimsuffix(trimprefix(jsonencode(replace(
    file("${local.analytics_common_dir}/analytics_common/sql/daily_machine_stats.sql"),
    "operation_id = 'OP-01'", "operation_id = '${var.default_operation_id}'"
  )), "\""), "\"")
}

data "archive_file" "analytics" {
  for_each    = local.analytics_lambdas
  type        = "zip"
  output_path = "${path.module}/../../build/analytics-${each.key}.zip"

  dynamic "source" {
    for_each = merge(
      { for f in setsubtract(fileset("${local.analytics_dir}/${each.key}", "*.py"), ["conftest.py"]) : f => "${local.analytics_dir}/${each.key}/${f}" },
      { for f in local.analytics_common_files : f => "${local.analytics_common_dir}/${f}" },
    )
    content {
      content  = file(source.value)
      filename = source.key
    }
  }
}

resource "aws_cloudwatch_log_group" "analytics" {
  for_each          = local.analytics_lambdas
  name              = "/aws/lambda/${local.prefix}-analytics-${replace(each.key, "_", "-")}"
  retention_in_days = var.log_retention_days
}

resource "aws_lambda_function" "analytics" {
  for_each         = local.analytics_lambdas
  function_name    = "${local.prefix}-analytics-${replace(each.key, "_", "-")}"
  description      = each.value.description
  role             = local.lab_role
  runtime          = "python3.12"
  handler          = "handler.handler"
  filename         = data.archive_file.analytics[each.key].output_path
  source_code_hash = data.archive_file.analytics[each.key].output_base64sha256
  layers           = [aws_lambda_layer_version.common.arn]
  memory_size      = 512
  timeout          = 300

  tracing_config {
    mode = "Active"
  }

  environment {
    variables = merge(local.common_env, each.value.env, { POWERTOOLS_SERVICE_NAME = "analytics-${each.key}" })
  }

  depends_on = [aws_cloudwatch_log_group.analytics]
}

resource "aws_cloudwatch_log_group" "sfn_analisis_diario" {
  name              = "/aws/vendedlogs/states/${local.prefix}-analisis-diario"
  retention_in_days = var.log_retention_days
}

resource "aws_sfn_state_machine" "analisis_diario" {
  name     = "${local.prefix}-analisis-diario"
  role_arn = local.lab_role
  type     = "STANDARD"
  definition = templatefile("${local.analytics_dir}/sfn/analisis_diario.asl.json", {
    sql_daily_stats  = local.sql_daily_stats
    workgroup        = aws_athena_workgroup.a.name
    database         = aws_glue_catalog_database.lake.name
    fn_preventivo    = aws_lambda_function.analytics["preventivo"].arn
    fn_repuestos     = aws_lambda_function.analytics["repuestos"].arn
    fn_combustible   = aws_lambda_function.analytics["combustible"].arn
    fn_productividad = aws_lambda_function.analytics["productividad"].arn
    fn_kpis_report   = aws_lambda_function.analytics["kpis_report"].arn
  })

  logging_configuration {
    log_destination        = "${aws_cloudwatch_log_group.sfn_analisis_diario.arn}:*"
    include_execution_data = true
    level                  = "ERROR"
  }

  tracing_configuration {
    enabled = true
  }
}

resource "aws_scheduler_schedule" "analisis_diario" {
  name                         = "${local.prefix}-analisis-diario"
  description                  = "AnalisisDiario a las 05:00 de Lima (RF-03.3)"
  schedule_expression          = "cron(0 5 * * ? *)"
  schedule_expression_timezone = "America/Lima"

  flexible_time_window {
    mode = "OFF"
  }

  target {
    arn      = aws_sfn_state_machine.analisis_diario.arn
    role_arn = local.lab_role
    input    = jsonencode({ trigger = "schedule" })
  }
}

resource "aws_cloudwatch_metric_alarm" "analisis_diario_failed" {
  alarm_name          = "${local.prefix}-analisis-diario-failed"
  alarm_description   = "AnalisisDiario terminó en Fail (MH-OBS)"
  namespace           = "AWS/States"
  metric_name         = "ExecutionsFailed"
  dimensions          = { StateMachineArn = aws_sfn_state_machine.analisis_diario.arn }
  statistic           = "Sum"
  period              = 3600
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [local.alarm_topic_arn]
}
