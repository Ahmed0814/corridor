variable "name" {
  type = string
}

variable "environment" {
  type        = string
  description = "DJANGO_ENV of the stack; the single host runs as 'staging' (deployed safety settings)."
}

variable "instance_type" {
  type    = string
  default = "t4g.small"
}

variable "volume_gb" {
  type    = number
  default = 20
}

variable "hostname" {
  type        = string
  description = "Public DNS name of the host (a domain, or <ip>.sslip.io)."
}

variable "eip_allocation_id" {
  type        = string
  description = "Elastic IP allocated by the environment (the hostname derives from it)."
}

variable "acme_email" {
  type        = string
  description = "Contact address for Let's Encrypt expiry notices."
}

variable "backend_image" {
  type = string
}

variable "web_image" {
  type = string
}

variable "cognito_issuer" {
  type = string
}

variable "cognito_user_pool_id" {
  type = string
}

variable "cognito_user_pool_arn" {
  type = string
}

variable "cognito_hosted_domain" {
  type = string
}

variable "cognito_client_ids" {
  type = object({ web_office = string, web_portal = string, driver = string })
}
