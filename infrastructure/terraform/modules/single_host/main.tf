# Single-host test environment (DECISIONS D-072): the production container images on one small
# Graviton EC2 instance with Docker Compose. Not for production or real customer data.
#
# Network: one VPC, one public subnet, internet gateway; no NAT, no load balancer.
# Inbound: only 80/443 (Caddy, HTTPS via Let's Encrypt). No SSH: access via SSM Session Manager.
# Secrets: generated here, stored as SSM SecureString parameters, read by the instance at boot
# (never placed in user data). They are also in Terraform state, which lives in the encrypted,
# private, TLS-only state bucket.
# Backups: daily EBS snapshots kept 7 days (Data Lifecycle Manager).

terraform {
  required_providers {
    aws    = { source = "hashicorp/aws", version = "~> 6.0" }
    random = { source = "hashicorp/random", version = "~> 3.6" }
  }
}

data "aws_region" "current" {}
data "aws_caller_identity" "current" {}

data "aws_availability_zones" "available" {
  state = "available"
}

# Amazon Linux 2023, arm64, latest (resolved at plan time; pinned afterwards by ignore_changes).
data "aws_ssm_parameter" "al2023_arm64" {
  name = "/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-arm64"
}

# ------------------------------------------------------------------------------- network

resource "aws_vpc" "this" {
  cidr_block           = "10.42.0.0/16"
  enable_dns_support   = true
  enable_dns_hostnames = true
  tags                 = { Name = var.name }
}

resource "aws_internet_gateway" "this" {
  vpc_id = aws_vpc.this.id
  tags   = { Name = var.name }
}

resource "aws_subnet" "public" {
  vpc_id                  = aws_vpc.this.id
  cidr_block              = "10.42.1.0/24"
  availability_zone       = data.aws_availability_zones.available.names[0]
  map_public_ip_on_launch = false # the Elastic IP is the only public address
  tags                    = { Name = "${var.name}-public" }
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.this.id
  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.this.id
  }
  tags = { Name = "${var.name}-public" }
}

resource "aws_route_table_association" "public" {
  subnet_id      = aws_subnet.public.id
  route_table_id = aws_route_table.public.id
}

# Lock down the default security group of the VPC (nothing uses it).
resource "aws_default_security_group" "default" {
  vpc_id = aws_vpc.this.id
}

resource "aws_security_group" "host" {
  name        = "${var.name}-host"
  description = "HTTPS (and HTTP for ACME + redirect) only; no SSH"
  vpc_id      = aws_vpc.this.id
  tags        = { Name = "${var.name}-host" }
}

resource "aws_vpc_security_group_ingress_rule" "https" {
  security_group_id = aws_security_group.host.id
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
  description       = "HTTPS"
}

resource "aws_vpc_security_group_ingress_rule" "http" {
  security_group_id = aws_security_group.host.id
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "tcp"
  from_port         = 80
  to_port           = 80
  description       = "HTTP for ACME challenge and redirect to HTTPS"
}

resource "aws_vpc_security_group_egress_rule" "all" {
  security_group_id = aws_security_group.host.id
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "-1"
  description       = "Image pulls, OS updates, Cognito, ACME"
}

locals {
  hostname = var.hostname
}

# ------------------------------------------------------------------------------- secrets

resource "random_password" "db" {
  for_each = toset(["postgres", "migrator", "app", "relay", "platform"])
  length   = 32
  special  = false
}

resource "random_password" "django_secret" {
  length  = 64
  special = false
}

resource "random_bytes" "field_key" {
  length = 32
}

locals {
  # Fernet needs url-safe base64 of 32 bytes.
  fernet_key = replace(replace(random_bytes.field_key.base64, "+", "-"), "/", "_")
  secrets = {
    db_postgres_password = random_password.db["postgres"].result
    db_migrator_password = random_password.db["migrator"].result
    db_app_password      = random_password.db["app"].result
    db_relay_password    = random_password.db["relay"].result
    db_platform_password = random_password.db["platform"].result
    django_secret_key    = random_password.django_secret.result
    field_encryption_key = local.fernet_key
  }
  param_prefix = "/corridor/${var.environment}"
}

resource "aws_ssm_parameter" "secret" {
  for_each = local.secrets
  name     = "${local.param_prefix}/${each.key}"
  type     = "SecureString"
  value    = each.value
  tier     = "Standard" # free
}

# ------------------------------------------------------------------------------- IAM

resource "aws_iam_role" "host" {
  name = "${var.name}-host"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ec2.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "ssm_core" {
  role       = aws_iam_role.host.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

# Least privilege: read only this environment's parameters; the Cognito admin calls the API
# makes (create user, read MFA state, global sign-out) on this pool only.
resource "aws_iam_role_policy" "host" {
  name = "${var.name}-host"
  role = aws_iam_role.host.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "ReadEnvironmentParameters"
        Effect   = "Allow"
        Action   = ["ssm:GetParameter", "ssm:GetParameters", "ssm:GetParametersByPath"]
        Resource = "arn:aws:ssm:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:parameter${local.param_prefix}/*"
      },
      {
        Sid      = "CognitoAdminForApi"
        Effect   = "Allow"
        Action   = ["cognito-idp:AdminCreateUser", "cognito-idp:AdminGetUser", "cognito-idp:AdminUserGlobalSignOut"]
        Resource = var.cognito_user_pool_arn
      },
    ]
  })
}

resource "aws_iam_instance_profile" "host" {
  name = "${var.name}-host"
  role = aws_iam_role.host.name
}

# ------------------------------------------------------------------------------- instance

locals {
  compose = templatefile("${path.module}/templates/compose.yml.tftpl", {
    environment     = var.environment
    hostname        = local.hostname
    backend_image   = var.backend_image
    web_image       = var.web_image
    region          = data.aws_region.current.region
    cognito_issuer  = var.cognito_issuer
    cognito_pool_id = var.cognito_user_pool_id
    cognito_domain  = var.cognito_hosted_domain
    client_office   = var.cognito_client_ids.web_office
    client_portal   = var.cognito_client_ids.web_portal
    client_driver   = var.cognito_client_ids.driver
  })
  caddyfile = templatefile("${path.module}/templates/Caddyfile.tftpl", {
    hostname   = local.hostname
    acme_email = var.acme_email
  })
  elasticmq = templatefile("${path.module}/templates/elasticmq.conf.tftpl", {
    prefix = "corridor-${var.environment}-"
  })
  user_data = templatefile("${path.module}/templates/user_data.sh.tftpl", {
    param_prefix   = local.param_prefix
    region         = data.aws_region.current.region
    compose_b64    = base64gzip(local.compose)
    caddyfile_b64  = base64gzip(local.caddyfile)
    elasticmq_b64  = base64gzip(local.elasticmq)
    extensions_b64 = base64gzip(file("${path.module}/../../../../docker/postgres/init/01-extensions.sql"))
    roles_sql_b64  = base64gzip(file("${path.module}/../../../../backend/db/bootstrap_roles.sql"))
    roles_sh_b64   = base64gzip(file("${path.module}/templates/02-roles.sh"))
  })
}

resource "aws_instance" "host" {
  ami                         = data.aws_ssm_parameter.al2023_arm64.value
  instance_type               = var.instance_type
  subnet_id                   = aws_subnet.public.id
  vpc_security_group_ids      = [aws_security_group.host.id]
  iam_instance_profile        = aws_iam_instance_profile.host.name
  associate_public_ip_address = false
  user_data_base64            = base64gzip(local.user_data)
  user_data_replace_on_change = false

  metadata_options {
    http_tokens                 = "required" # IMDSv2 only
    http_put_response_hop_limit = 2          # containers use the instance role through IMDS
    http_endpoint               = "enabled"
  }

  root_block_device {
    volume_type           = "gp3"
    volume_size           = var.volume_gb
    encrypted             = true
    delete_on_termination = false # data survives an accidental instance replacement
    tags                  = { Name = var.name, backup = "daily-7d" }
  }

  credit_specification {
    cpu_credits = "standard" # never bill for CPU bursts beyond the baseline credits
  }

  tags = { Name = var.name }

  lifecycle {
    # No surprise replacement: AMI or config updates, and AWS reporting the attached Elastic IP as a
    # public address (associate_public_ip_address reads true once the EIP is associated).
    ignore_changes = [ami, user_data_base64, associate_public_ip_address]
  }
}

resource "aws_eip_association" "host" {
  instance_id   = aws_instance.host.id
  allocation_id = var.eip_allocation_id
}

# ------------------------------------------------------------------------------- backups

resource "aws_iam_role" "dlm" {
  name = "${var.name}-dlm"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "dlm.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "dlm" {
  role       = aws_iam_role.dlm.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSDataLifecycleManagerServiceRole"
}

resource "aws_dlm_lifecycle_policy" "daily" {
  description        = "${var.name} daily snapshots kept 7 days"
  execution_role_arn = aws_iam_role.dlm.arn
  state              = "ENABLED"
  policy_details {
    resource_types = ["VOLUME"]
    target_tags    = { backup = "daily-7d" }
    schedule {
      name = "daily"
      create_rule {
        interval      = 24
        interval_unit = "HOURS"
        times         = ["03:00"]
      }
      retain_rule {
        count = 7
      }
      copy_tags = true
    }
  }
}
