# Cognito User Pool (RNF-08, contratos.md §2.1). Grupos = roles; precedencia = rbac.ROLE_PRECEDENCE.
# Los usuarios demo los crea scripts/cognito_users.py (C) con custom:zone y custom:technician_id.
locals {
  role_precedence = {
    admin         = 0
    gerencia      = 1
    supervisor    = 2
    mantenimiento = 3
    tecnico       = 4
    operador      = 5
  }
}

resource "aws_cognito_user_pool" "users" {
  name                = "${local.prefix}-users"
  deletion_protection = "INACTIVE"
  username_configuration {
    case_sensitive = false
  }

  admin_create_user_config {
    allow_admin_create_user_only = true # sin auto-registro: los usuarios los crea el admin / script
  }

  password_policy {
    minimum_length                   = 8
    require_lowercase                = true
    require_uppercase                = true
    require_numbers                  = true
    require_symbols                  = false
    temporary_password_validity_days = 7
  }

  schema {
    name                     = "email"
    attribute_data_type      = "String"
    mutable                  = true
    required                 = false
    developer_only_attribute = false
    string_attribute_constraints {
      min_length = 0
      max_length = 256
    }
  }

  # custom:zone = norte|sur|este|oeste|* (§2.1)
  schema {
    name                     = "zone"
    attribute_data_type      = "String"
    mutable                  = true
    required                 = false
    developer_only_attribute = false
    string_attribute_constraints {
      min_length = 1
      max_length = 16
    }
  }

  # custom:technician_id = TEC-07 (solo grupo tecnico, #8)
  schema {
    name                     = "technician_id"
    attribute_data_type      = "String"
    mutable                  = true
    required                 = false
    developer_only_attribute = false
    string_attribute_constraints {
      min_length = 1
      max_length = 32
    }
  }

  lifecycle {
    # Cognito no permite modificar el schema después de crear el pool
    ignore_changes = [schema]
  }
}

resource "aws_cognito_user_group" "roles" {
  for_each     = local.role_precedence
  name         = each.key
  user_pool_id = aws_cognito_user_pool.users.id
  precedence   = each.value
  description  = "Rol ${each.key} (RNF-08)"
}

resource "aws_cognito_user_pool_client" "web" {
  name         = "${local.prefix}-web"
  user_pool_id = aws_cognito_user_pool.users.id

  generate_secret               = false # SPA
  prevent_user_existence_errors = "ENABLED"
  explicit_auth_flows           = ["ALLOW_USER_SRP_AUTH", "ALLOW_USER_PASSWORD_AUTH", "ALLOW_REFRESH_TOKEN_AUTH"]

  # El ID token lleva cognito:groups, custom:zone y custom:technician_id (lo usa el authorizer y las Lambdas)
  read_attributes  = ["email", "custom:zone", "custom:technician_id"]
  write_attributes = ["email"] # el usuario no puede cambiarse la zona ni el técnico

  id_token_validity      = 60
  access_token_validity  = 60
  refresh_token_validity = 7
  token_validity_units {
    id_token      = "minutes"
    access_token  = "minutes"
    refresh_token = "days"
  }
}
