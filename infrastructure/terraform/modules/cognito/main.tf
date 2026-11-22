# Cognito user pool for one environment (DECISIONS D-006, D-042). The local issuer is refused
# outside development, so deployed environments always use a real pool.
#
# * Sign-in with email or phone; users are created by the API (admin_create_user), never by
#   self sign-up.
# * MFA optional, TOTP only (no SMS cost); the API enforces MFA for roles that need it.
# * Three public app clients (authorization code + PKCE, no client secret): web office,
#   web portal, driver app.
# * Free at test volume (Cognito free tier).

variable "name" {
  type = string
}

variable "domain_prefix" {
  type        = string
  description = "Prefix of the Cognito hosted domain (<prefix>.auth.<region>.amazoncognito.com); globally unique."
}

variable "web_base_url" {
  type        = string
  description = "https://<host> of the web app."
}

variable "driver_redirect_uris" {
  type    = list(string)
  default = ["corridor-driver://auth/callback"]
}

resource "aws_cognito_user_pool" "this" {
  name                     = var.name
  username_attributes      = ["email", "phone_number"]
  auto_verified_attributes = ["email"]
  mfa_configuration        = "OPTIONAL"
  deletion_protection      = "ACTIVE"

  software_token_mfa_configuration {
    enabled = true
  }

  admin_create_user_config {
    allow_admin_create_user_only = true
  }

  password_policy {
    minimum_length                   = 12
    require_lowercase                = true
    require_uppercase                = true
    require_numbers                  = true
    require_symbols                  = false
    temporary_password_validity_days = 3
  }

  account_recovery_setting {
    recovery_mechanism {
      name     = "verified_email"
      priority = 1
    }
  }

  schema {
    name                = "name"
    attribute_data_type = "String"
    mutable             = true
    required            = false
    string_attribute_constraints {
      min_length = 1
      max_length = 200
    }
  }
}

resource "aws_cognito_user_pool_domain" "this" {
  domain       = var.domain_prefix
  user_pool_id = aws_cognito_user_pool.this.id
}

locals {
  common = {
    allowed_oauth_flows_user_pool_client = true
    allowed_oauth_flows                  = ["code"]
    allowed_oauth_scopes                 = ["openid", "email", "phone"]
    # Web users set up their own authenticator app (D-073): AssociateSoftwareToken etc. need it.
    web_oauth_scopes             = ["openid", "email", "phone", "aws.cognito.signin.user.admin"]
    supported_identity_providers = ["COGNITO"]
    explicit_auth_flows          = ["ALLOW_REFRESH_TOKEN_AUTH", "ALLOW_USER_SRP_AUTH"]
  }
}

resource "aws_cognito_user_pool_client" "web_office" {
  name                                 = "${var.name}-web-office"
  user_pool_id                         = aws_cognito_user_pool.this.id
  generate_secret                      = false
  allowed_oauth_flows_user_pool_client = local.common.allowed_oauth_flows_user_pool_client
  allowed_oauth_flows                  = local.common.allowed_oauth_flows
  allowed_oauth_scopes                 = local.common.web_oauth_scopes
  supported_identity_providers         = local.common.supported_identity_providers
  explicit_auth_flows                  = local.common.explicit_auth_flows
  callback_urls                        = ["${var.web_base_url}/auth/callback"]
  logout_urls                          = ["${var.web_base_url}/"]
  access_token_validity                = 15
  id_token_validity                    = 15
  refresh_token_validity               = 12
  token_validity_units {
    access_token  = "minutes"
    id_token      = "minutes"
    refresh_token = "hours"
  }
  prevent_user_existence_errors = "ENABLED"
  enable_token_revocation       = true
}

resource "aws_cognito_user_pool_client" "web_portal" {
  name                                 = "${var.name}-web-portal"
  user_pool_id                         = aws_cognito_user_pool.this.id
  generate_secret                      = false
  allowed_oauth_flows_user_pool_client = local.common.allowed_oauth_flows_user_pool_client
  allowed_oauth_flows                  = local.common.allowed_oauth_flows
  allowed_oauth_scopes                 = local.common.web_oauth_scopes
  supported_identity_providers         = local.common.supported_identity_providers
  explicit_auth_flows                  = local.common.explicit_auth_flows
  callback_urls                        = ["${var.web_base_url}/auth/callback"]
  logout_urls                          = ["${var.web_base_url}/"]
  access_token_validity                = 15
  id_token_validity                    = 15
  refresh_token_validity               = 24
  token_validity_units {
    access_token  = "minutes"
    id_token      = "minutes"
    refresh_token = "hours"
  }
  prevent_user_existence_errors = "ENABLED"
  enable_token_revocation       = true
}

resource "aws_cognito_user_pool_client" "driver" {
  name                                 = "${var.name}-driver-mobile"
  user_pool_id                         = aws_cognito_user_pool.this.id
  generate_secret                      = false
  allowed_oauth_flows_user_pool_client = local.common.allowed_oauth_flows_user_pool_client
  allowed_oauth_flows                  = local.common.allowed_oauth_flows
  allowed_oauth_scopes                 = local.common.allowed_oauth_scopes
  supported_identity_providers         = local.common.supported_identity_providers
  explicit_auth_flows                  = local.common.explicit_auth_flows
  callback_urls                        = var.driver_redirect_uris
  logout_urls                          = var.driver_redirect_uris
  access_token_validity                = 60
  id_token_validity                    = 60
  refresh_token_validity               = 30
  token_validity_units {
    access_token  = "minutes"
    id_token      = "minutes"
    refresh_token = "days"
  }
  prevent_user_existence_errors = "ENABLED"
  enable_token_revocation       = true
}

data "aws_region" "current" {}

output "user_pool_id" {
  value = aws_cognito_user_pool.this.id
}

output "user_pool_arn" {
  value = aws_cognito_user_pool.this.arn
}

output "issuer" {
  value = "https://cognito-idp.${data.aws_region.current.region}.amazonaws.com/${aws_cognito_user_pool.this.id}"
}

output "hosted_domain" {
  value = "https://${aws_cognito_user_pool_domain.this.domain}.auth.${data.aws_region.current.region}.amazoncognito.com"
}

output "client_ids" {
  value = {
    web_office = aws_cognito_user_pool_client.web_office.id
    web_portal = aws_cognito_user_pool_client.web_portal.id
    driver     = aws_cognito_user_pool_client.driver.id
  }
}
