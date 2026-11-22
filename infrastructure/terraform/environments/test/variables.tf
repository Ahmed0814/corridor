variable "region" {
  type    = string
  default = "ca-central-1"
}

variable "account_id" {
  type        = string
  description = "AWS account id; Terraform refuses to run against any other account."
  validation {
    condition     = can(regex("^[0-9]{12}$", var.account_id))
    error_message = "account_id must be 12 digits."
  }
}

variable "alert_email" {
  type        = string
  description = "Receives budget alerts and Let's Encrypt notices."
}

variable "instance_type" {
  type    = string
  default = "t4g.small"
  validation {
    condition     = can(regex("^t4g\\.", var.instance_type))
    error_message = "The test host is Graviton (arm64) only; images are built for linux/arm64."
  }
}

variable "domain_name" {
  type        = string
  default     = ""
  description = "Optional DNS name pointed at the Elastic IP. Empty: <ip>.sslip.io (free)."
}

variable "backend_image" {
  type        = string
  description = "linux/arm64 backend image, pinned by digest (ghcr.io/<owner>/corridor-backend@sha256:...)."
}

variable "web_image" {
  type        = string
  description = "linux/arm64 web image, pinned by digest (ghcr.io/<owner>/corridor-web@sha256:...)."
}
