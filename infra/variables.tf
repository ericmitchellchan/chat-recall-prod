# -----------------------------------------------------------------------------
# General
# -----------------------------------------------------------------------------

variable "environment" {
  description = "Deployment environment"
  type        = string
  default     = "prod"
}

variable "aws_region" {
  description = "AWS region for all resources"
  type        = string
  default     = "us-west-2"
}

# -----------------------------------------------------------------------------
# RDS
# -----------------------------------------------------------------------------

variable "db_name" {
  description = "Name of the Postgres database"
  type        = string
  default     = "chat_recall"
}

variable "db_username" {
  description = "Master username for the RDS instance"
  type        = string
  default     = "chat_recall"
}

variable "db_password" {
  description = "Master password for the RDS instance"
  type        = string
  sensitive   = true
}

# -----------------------------------------------------------------------------
# Application
# -----------------------------------------------------------------------------

variable "app_image" {
  description = "ECR image URI for the chat-recall-api container"
  type        = string
}

variable "app_port" {
  description = "Port the FastAPI application listens on"
  type        = number
  default     = 8081
}

variable "nextauth_secret" {
  description = "NextAuth.js JWT signing secret"
  type        = string
  sensitive   = true
}

variable "stripe_secret_key" {
  description = "Stripe secret API key"
  type        = string
  sensitive   = true
}

variable "stripe_webhook_secret" {
  description = "Stripe webhook signing secret"
  type        = string
  sensitive   = true
}

variable "stripe_monthly_price_id" {
  description = "Stripe Price ID for the monthly plan"
  type        = string
}

variable "stripe_annual_price_id" {
  description = "Stripe Price ID for the annual plan"
  type        = string
}

variable "stripe_product_id" {
  description = "Stripe Product ID"
  type        = string
}

variable "cors_origins" {
  description = "Comma-separated list of allowed CORS origins"
  type        = string
  default     = "https://chatrecall.ai,https://www.chatrecall.ai"
}

variable "frontend_url" {
  description = "Frontend URL for redirects and links"
  type        = string
  default     = "https://chatrecall.ai"
}

# -----------------------------------------------------------------------------
# Networking / Domain
# -----------------------------------------------------------------------------

variable "domain_name" {
  description = "API domain name (points to the ALB)"
  type        = string
  default     = "api.chatrecall.ai"
}

variable "acm_certificate_arn" {
  description = "ARN of the ACM certificate for HTTPS on the ALB"
  type        = string
}

# -----------------------------------------------------------------------------
# ECS Sizing
# -----------------------------------------------------------------------------

variable "desired_count" {
  description = "Desired number of ECS service tasks"
  type        = number
  default     = 1
}

variable "cpu" {
  description = "CPU units for the Fargate task (1 vCPU = 1024)"
  type        = number
  default     = 256
}

variable "memory" {
  description = "Memory (MiB) for the Fargate task"
  type        = number
  default     = 512
}
