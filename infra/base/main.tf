# Tablas DynamoDB (contracts/dynamodb.md, contratos.md §9.1). On-demand, PITR y Streams NEW_AND_OLD_IMAGES.

# ---------- machines ----------
resource "aws_dynamodb_table" "machines" {
  name             = "${local.prefix}-machines"
  billing_mode     = "PAY_PER_REQUEST"
  hash_key         = "pk"
  range_key        = "sk"
  stream_enabled   = true
  stream_view_type = "NEW_AND_OLD_IMAGES"

  attribute {
    name = "pk"
    type = "S"
  }
  attribute {
    name = "sk"
    type = "S"
  }
  attribute {
    name = "zone"
    type = "S"
  }
  attribute {
    name = "machine_id"
    type = "S"
  }

  global_secondary_index {
    name            = "by_zone"
    hash_key        = "zone"
    range_key       = "machine_id"
    projection_type = "ALL"
  }

  point_in_time_recovery {
    enabled = true
  }
}

# ---------- technicians ----------
resource "aws_dynamodb_table" "technicians" {
  name             = "${local.prefix}-technicians"
  billing_mode     = "PAY_PER_REQUEST"
  hash_key         = "pk"
  range_key        = "sk"
  stream_enabled   = true
  stream_view_type = "NEW_AND_OLD_IMAGES"

  attribute {
    name = "pk"
    type = "S"
  }
  attribute {
    name = "sk"
    type = "S"
  }
  attribute {
    name = "zone"
    type = "S"
  }
  attribute {
    name = "technician_id"
    type = "S"
  }

  global_secondary_index {
    name            = "by_zone"
    hash_key        = "zone"
    range_key       = "technician_id"
    projection_type = "ALL"
  }

  point_in_time_recovery {
    enabled = true
  }
}

# ---------- catalog ----------
resource "aws_dynamodb_table" "catalog" {
  name             = "${local.prefix}-catalog"
  billing_mode     = "PAY_PER_REQUEST"
  hash_key         = "pk"
  range_key        = "sk"
  stream_enabled   = true
  stream_view_type = "NEW_AND_OLD_IMAGES"

  attribute {
    name = "pk"
    type = "S"
  }
  attribute {
    name = "sk"
    type = "S"
  }

  point_in_time_recovery {
    enabled = true
  }
}

# ---------- inventory ----------
resource "aws_dynamodb_table" "inventory" {
  name             = "${local.prefix}-inventory"
  billing_mode     = "PAY_PER_REQUEST"
  hash_key         = "pk"
  range_key        = "sk"
  stream_enabled   = true
  stream_view_type = "NEW_AND_OLD_IMAGES"

  attribute {
    name = "pk"
    type = "S"
  }
  attribute {
    name = "sk"
    type = "S"
  }
  attribute {
    name = "component_id"
    type = "S"
  }
  attribute {
    name = "warehouse_id"
    type = "S"
  }

  global_secondary_index {
    name            = "by_component"
    hash_key        = "component_id"
    range_key       = "warehouse_id"
    projection_type = "ALL"
  }

  point_in_time_recovery {
    enabled = true
  }
}

# ---------- notification-rules ----------
resource "aws_dynamodb_table" "notification_rules" {
  name             = "${local.prefix}-notification-rules"
  billing_mode     = "PAY_PER_REQUEST"
  hash_key         = "pk"
  range_key        = "sk"
  stream_enabled   = true
  stream_view_type = "NEW_AND_OLD_IMAGES"

  attribute {
    name = "pk"
    type = "S"
  }
  attribute {
    name = "sk"
    type = "S"
  }

  point_in_time_recovery {
    enabled = true
  }
}

# ---------- incidents ----------
resource "aws_dynamodb_table" "incidents" {
  name             = "${local.prefix}-incidents"
  billing_mode     = "PAY_PER_REQUEST"
  hash_key         = "pk"
  range_key        = "sk"
  stream_enabled   = true
  stream_view_type = "NEW_AND_OLD_IMAGES"

  attribute {
    name = "pk"
    type = "S"
  }
  attribute {
    name = "sk"
    type = "S"
  }
  attribute {
    name = "machine_id"
    type = "S"
  }
  attribute {
    name = "status"
    type = "S"
  }
  attribute {
    name = "detected_at"
    type = "S"
  }

  global_secondary_index {
    name            = "by_machine"
    hash_key        = "machine_id"
    range_key       = "detected_at"
    projection_type = "ALL"
  }

  global_secondary_index {
    name            = "by_status"
    hash_key        = "status"
    range_key       = "detected_at"
    projection_type = "ALL"
  }

  point_in_time_recovery {
    enabled = true
  }
}

# ---------- machine-state (TTL) ----------
resource "aws_dynamodb_table" "machine_state" {
  name             = "${local.prefix}-machine-state"
  billing_mode     = "PAY_PER_REQUEST"
  hash_key         = "pk"
  range_key        = "sk"
  stream_enabled   = true
  stream_view_type = "NEW_AND_OLD_IMAGES"

  attribute {
    name = "pk"
    type = "S"
  }
  attribute {
    name = "sk"
    type = "S"
  }

  ttl {
    attribute_name = "expires_at"
    enabled        = true
  }

  point_in_time_recovery {
    enabled = true
  }
}

# ---------- anomalies ----------
resource "aws_dynamodb_table" "anomalies" {
  name             = "${local.prefix}-anomalies"
  billing_mode     = "PAY_PER_REQUEST"
  hash_key         = "pk"
  range_key        = "sk"
  stream_enabled   = true
  stream_view_type = "NEW_AND_OLD_IMAGES"

  attribute {
    name = "pk"
    type = "S"
  }
  attribute {
    name = "sk"
    type = "S"
  }
  attribute {
    name = "zone"
    type = "S"
  }
  attribute {
    name = "detected_at"
    type = "S"
  }

  global_secondary_index {
    name            = "by_zone"
    hash_key        = "zone"
    range_key       = "detected_at"
    projection_type = "ALL"
  }

  point_in_time_recovery {
    enabled = true
  }
}

# ---------- idempotency (solo pk, TTL) ----------
resource "aws_dynamodb_table" "idempotency" {
  name             = "${local.prefix}-idempotency"
  billing_mode     = "PAY_PER_REQUEST"
  hash_key         = "pk"
  stream_enabled   = true
  stream_view_type = "NEW_AND_OLD_IMAGES"

  attribute {
    name = "pk"
    type = "S"
  }

  ttl {
    attribute_name = "expires_at"
    enabled        = true
  }

  point_in_time_recovery {
    enabled = true
  }
}

# ---------- audit-events ----------
resource "aws_dynamodb_table" "audit_events" {
  name             = "${local.prefix}-audit-events"
  billing_mode     = "PAY_PER_REQUEST"
  hash_key         = "pk"
  range_key        = "sk"
  stream_enabled   = true
  stream_view_type = "NEW_AND_OLD_IMAGES"

  attribute {
    name = "pk"
    type = "S"
  }
  attribute {
    name = "sk"
    type = "S"
  }

  point_in_time_recovery {
    enabled = true
  }
}

# ---------- warehouses (seed de C, #19) ----------
resource "aws_dynamodb_table" "warehouses" {
  name             = "${local.prefix}-warehouses"
  billing_mode     = "PAY_PER_REQUEST"
  hash_key         = "pk"
  range_key        = "sk"
  stream_enabled   = true
  stream_view_type = "NEW_AND_OLD_IMAGES"

  attribute {
    name = "pk"
    type = "S"
  }
  attribute {
    name = "sk"
    type = "S"
  }

  point_in_time_recovery {
    enabled = true
  }
}

# ---------- maintenance-records (B escribe el corrective al cerrar; A y C leen) ----------
resource "aws_dynamodb_table" "maintenance_records" {
  name             = "${local.prefix}-maintenance-records"
  billing_mode     = "PAY_PER_REQUEST"
  hash_key         = "pk"
  range_key        = "sk"
  stream_enabled   = true
  stream_view_type = "NEW_AND_OLD_IMAGES"

  attribute {
    name = "pk"
    type = "S"
  }
  attribute {
    name = "sk"
    type = "S"
  }

  point_in_time_recovery {
    enabled = true
  }
}

# ---------- insights (A escribe, C lee) ----------
resource "aws_dynamodb_table" "insights" {
  name             = "${local.prefix}-insights"
  billing_mode     = "PAY_PER_REQUEST"
  hash_key         = "pk"
  range_key        = "sk"
  stream_enabled   = true
  stream_view_type = "NEW_AND_OLD_IMAGES"

  attribute {
    name = "pk"
    type = "S"
  }
  attribute {
    name = "sk"
    type = "S"
  }

  point_in_time_recovery {
    enabled = true
  }
}
