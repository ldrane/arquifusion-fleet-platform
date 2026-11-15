# Data lake de telemetría: S3 (Parquet) + Glue + Firehose + Athena.
# Cubre: RF-01.4, RNF-05, RNF-14, ESC-05, ESC-08, MH-HA-01. Dueño: Persona A (worker 2).
# Recursos que usa el worker 3 (analítica): module.lake_bucket, aws_glue_catalog_database.lake,
# aws_glue_catalog_table.telemetry_raw, aws_athena_workgroup.a.

locals {
  # Copia de services/ml/arquifusion_ml/lake.py (LAKE_COLUMNS / PARTITION_KEYS), que es la FUENTE DE VERDAD.
  # Si cambia allí, cambia aquí en el mismo PR.
  lake_columns = [
    { name = "machine_id", type = "string" },
    { name = "model", type = "string" },
    { name = "ts", type = "timestamp" },
    { name = "lat", type = "double" },
    { name = "lon", type = "double" },
    { name = "zone", type = "string" },
    { name = "operating_hours", type = "double" },
    { name = "temperature_c", type = "double" },
    { name = "vibration_mm_s", type = "double" },
    { name = "pressure_bar", type = "double" },
    { name = "fuel_rate_lph", type = "double" },
    { name = "load_pct", type = "double" },
    { name = "speed_kmh", type = "double" },
    { name = "rpm", type = "double" },
    { name = "state", type = "string" },
    { name = "sim_scenario", type = "string" },
    { name = "health_score", type = "int" },
    { name = "severity", type = "string" },
    { name = "correlation_id", type = "string" },
  ]
  lake_partition_keys = [
    { name = "operation_id", type = "string" },
    { name = "dt", type = "string" },
    { name = "machine_type", type = "string" },
  ]
  glue_database = replace("${local.prefix}_lake", "-", "_")
}

# ---------------------------------------------------------------- bucket
# Learner Lab: no usar resource "aws_s3_bucket" (SCP bloquea GetBucketObjectLockConfiguration).
# Ver infra/modules/lab_s3_bucket.
module "lake_bucket" {
  source = "../modules/lab_s3_bucket"
  name   = "${local.prefix}-lake-${local.account_id}"
  region = var.aws_region
}

resource "aws_s3_bucket_versioning" "lake" {
  bucket = module.lake_bucket.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "lake" {
  bucket = module.lake_bucket.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "lake" {
  bucket                  = module.lake_bucket.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_lifecycle_configuration" "lake" {
  bucket = module.lake_bucket.id
  rule {
    id     = "retencion-telemetria"
    status = "Enabled"
    filter {}
    transition {
      days          = 30
      storage_class = "STANDARD_IA"
    }
    transition {
      days          = 365
      storage_class = "GLACIER"
    }
    expiration {
      days = 730 # RNF-05: ≥ 1 año de histórico (Glacier solo a partir de 365 días)
    }
    noncurrent_version_expiration {
      noncurrent_days = 30
    }
  }
}

resource "aws_s3_bucket_policy" "lake_tls" {
  bucket = module.lake_bucket.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "DenyInsecureTransport"
      Effect    = "Deny"
      Principal = "*"
      Action    = "s3:*"
      Resource  = [module.lake_bucket.arn, "${module.lake_bucket.arn}/*"]
      Condition = { Bool = { "aws:SecureTransport" = "false" } }
    }]
  })
  depends_on = [aws_s3_bucket_public_access_block.lake]
}

# ---------------------------------------------------------------- catálogo (sin crawlers)
resource "aws_glue_catalog_database" "lake" {
  name        = local.glue_database
  description = "Data lake de ArquiFusion (${var.stage})"
}

resource "aws_glue_catalog_table" "telemetry_raw" {
  database_name = aws_glue_catalog_database.lake.name
  name          = "telemetry_raw"
  description   = "Telemetría cruda en Parquet. Esquema: services/ml/arquifusion_ml/lake.py"
  table_type    = "EXTERNAL_TABLE"

  # Partition projection: Athena encuentra las particiones sin MSCK REPAIR ni crawlers.
  parameters = {
    "classification"                 = "parquet"
    "EXTERNAL"                       = "TRUE"
    "projection.enabled"             = "true"
    "projection.operation_id.type"   = "injected"
    "projection.dt.type"             = "date"
    "projection.dt.format"           = "yyyy-MM-dd"
    "projection.dt.range"            = "2025-01-01,NOW"
    "projection.dt.interval"         = "1"
    "projection.dt.interval.unit"    = "DAYS"
    "projection.machine_type.type"   = "enum"
    "projection.machine_type.values" = "excavator,mining_truck,loader,bulldozer,drill"
    "storage.location.template"      = "s3://${module.lake_bucket.id}/telemetry/operation_id=$${operation_id}/dt=$${dt}/machine_type=$${machine_type}/"
  }

  dynamic "partition_keys" {
    for_each = local.lake_partition_keys
    content {
      name = partition_keys.value.name
      type = partition_keys.value.type
    }
  }

  storage_descriptor {
    location      = "s3://${module.lake_bucket.id}/telemetry/"
    input_format  = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetInputFormat"
    output_format = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetOutputFormat"

    ser_de_info {
      serialization_library = "org.apache.hadoop.hive.ql.io.parquet.serde.ParquetHiveSerDe"
    }

    dynamic "columns" {
      for_each = local.lake_columns
      content {
        name = columns.value.name
        type = columns.value.type
      }
    }
  }
}

# ---------------------------------------------------------------- Firehose (JSON → Parquet particionado)
resource "aws_cloudwatch_log_group" "firehose" {
  name              = "/aws/kinesisfirehose/${local.prefix}-telemetry"
  retention_in_days = var.log_retention_days
}

resource "aws_cloudwatch_log_stream" "firehose" {
  name           = "S3Delivery"
  log_group_name = aws_cloudwatch_log_group.firehose.name
}

resource "aws_kinesis_firehose_delivery_stream" "telemetry" {
  name        = "${local.prefix}-telemetry"
  destination = "extended_s3"

  extended_s3_configuration {
    role_arn            = local.lab_role
    bucket_arn          = module.lake_bucket.arn
    buffering_size      = 64  # MB (mínimo con conversión de formato)
    buffering_interval  = 300 # s
    prefix              = "telemetry/operation_id=!{partitionKeyFromQuery:operation_id}/dt=!{partitionKeyFromQuery:dt}/machine_type=!{partitionKeyFromQuery:machine_type}/"
    error_output_prefix = "errors/!{firehose:error-output-type}/dt=!{timestamp:yyyy-MM-dd}/"

    cloudwatch_logging_options {
      enabled         = true
      log_group_name  = aws_cloudwatch_log_group.firehose.name
      log_stream_name = aws_cloudwatch_log_stream.firehose.name
    }

    # procesar envía operation_id, dt y machine_type en cada registro (service.py::_lake_row).
    dynamic_partitioning_configuration {
      enabled = true
    }

    processing_configuration {
      enabled = true
      processors {
        type = "MetadataExtraction"
        parameters {
          parameter_name  = "MetadataExtractionQuery"
          parameter_value = "{operation_id:.operation_id,dt:.dt,machine_type:.machine_type}"
        }
        parameters {
          parameter_name  = "JsonParsingEngine"
          parameter_value = "JQ-1.6"
        }
      }
    }

    data_format_conversion_configuration {
      input_format_configuration {
        deserializer {
          hive_json_ser_de {
            timestamp_formats = ["yyyy-MM-dd'T'HH:mm:ss'Z'", "yyyy-MM-dd'T'HH:mm:ss.SSS'Z'"]
          }
        }
      }
      output_format_configuration {
        serializer {
          parquet_ser_de {
            compression = "SNAPPY"
          }
        }
      }
      schema_configuration {
        database_name = aws_glue_catalog_database.lake.name
        table_name    = aws_glue_catalog_table.telemetry_raw.name
        role_arn      = local.lab_role
      }
    }
  }
}

# ---------------------------------------------------------------- Athena
resource "aws_athena_workgroup" "a" {
  name          = "${local.prefix}-a"
  description   = "Consultas de analítica e IA de la Persona A (RF-03, RF-04, RF-07, RF-08, RF-13)"
  force_destroy = true

  configuration {
    enforce_workgroup_configuration    = true
    publish_cloudwatch_metrics_enabled = true
    bytes_scanned_cutoff_per_query     = 1073741824 # 1 GB: tope de costo por consulta

    result_configuration {
      output_location = "s3://${module.artifacts_bucket.id}/athena-results/"
      encryption_configuration {
        encryption_option = "SSE_S3"
      }
    }
  }
}
