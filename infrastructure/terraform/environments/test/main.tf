# Test environment: single host, ca-central-1, under $20/month (DECISIONS D-072).
# Seed data only, clearly labelled; NO real customer data. Apply only after approval.
#
#   terraform init -backend-config="bucket=<state bucket from bootstrap>"
#   terraform plan -var-file=test.tfvars

terraform {
  required_version = ">= 1.10"
  required_providers {
    aws    = { source = "hashicorp/aws", version = "~> 6.0" }
    random = { source = "hashicorp/random", version = "~> 3.6" }
  }
  backend "s3" {
    key          = "corridor/test/terraform.tfstate"
    region       = "ca-central-1"
    encrypt      = true
    use_lockfile = true # S3-native state locking (no DynamoDB table)
  }
}

provider "aws" {
  region              = var.region
  allowed_account_ids = [var.account_id]
  default_tags {
    tags = { project = "corridor", managed_by = "terraform", environment = "test", data = "seed-only" }
  }
}

locals {
  name = "corridor-test"
}

# Public address first: the hostname (and so the Cognito callback URLs) derive from it.
resource "aws_eip" "host" {
  domain = "vpc"
  tags   = { Name = local.name }
}

locals {
  hostname = var.domain_name != "" ? var.domain_name : "${replace(aws_eip.host.public_ip, ".", "-")}.sslip.io"
}

module "cognito" {
  source        = "../../modules/cognito"
  name          = local.name
  domain_prefix = "${local.name}-${substr(var.account_id, 8, 4)}"
  web_base_url  = "https://${local.hostname}"
}

module "host" {
  source                = "../../modules/single_host"
  name                  = local.name
  environment           = "staging" # deployed safety settings (DEBUG off, no local issuer)
  instance_type         = var.instance_type
  hostname              = local.hostname
  eip_allocation_id     = aws_eip.host.id
  acme_email            = var.alert_email
  backend_image         = var.backend_image
  web_image             = var.web_image
  cognito_issuer        = module.cognito.issuer
  cognito_user_pool_id  = module.cognito.user_pool_id
  cognito_user_pool_arn = module.cognito.user_pool_arn
  cognito_hosted_domain = module.cognito.hosted_domain
  cognito_client_ids    = module.cognito.client_ids
}

# Cost guard: e-mail alerts at $15 (forecast) and $20 (actual). The first two budgets are free.
resource "aws_budgets_budget" "monthly" {
  name         = "${local.name}-monthly"
  budget_type  = "COST"
  limit_amount = "20"
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 15
    threshold_type             = "ABSOLUTE_VALUE"
    notification_type          = "FORECASTED"
    subscriber_email_addresses = [var.alert_email]
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 20
    threshold_type             = "ABSOLUTE_VALUE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = [var.alert_email]
  }
}
