variable "target" {
  description = "\"aws\" for a real deployment, \"localstack\" to apply against a local LocalStack emulator."
  type        = string
  default     = "localstack"
  validation {
    condition     = contains(["aws", "localstack"], var.target)
    error_message = "target must be \"aws\" or \"localstack\"."
  }
}

variable "localstack_endpoint" {
  description = "LocalStack edge URL (only used when target = localstack)."
  type        = string
  default     = "http://localhost:4566"
}

variable "project" {
  type    = string
  default = "oncall-copilot"
}

variable "environment" {
  type    = string
  default = "demo"
}

variable "region" {
  type    = string
  default = "us-east-1"
}

variable "vpc_cidr" {
  type    = string
  default = "10.42.0.0/16"
}

variable "allowed_cidrs" {
  description = "CIDRs allowed to reach the load balancer. Restrict this to your IP for a demo."
  type        = list(string)
  default     = ["0.0.0.0/0"]
}

# --- What to deploy. LocalStack's free tier doesn't emulate every service, so these can be switched off there. ---

variable "deploy_registry" {
  description = "Create ECR repositories for the service images."
  type        = bool
  default     = true
}

variable "deploy_database" {
  description = "Create the RDS PostgreSQL instance."
  type        = bool
  default     = true
}

variable "deploy_compute" {
  description = "Create the ECS cluster, services and load balancer."
  type        = bool
  default     = true
  validation {
    condition     = !var.deploy_compute || (var.deploy_registry && var.deploy_database)
    error_message = "deploy_compute needs deploy_registry and deploy_database."
  }
}

# --- Services ---

variable "image_tag" {
  description = "Tag of the images pushed to ECR."
  type        = string
  default     = "latest"
}

variable "use_fargate_spot" {
  description = "Run tasks on Fargate Spot (much cheaper; tasks may be interrupted, which is fine for a demo)."
  type        = bool
  default     = true
}

variable "llm_provider" {
  description = "\"mock\" runs the rules-only agents (no GPU needed, $0 inference); \"ollama\" needs ollama_base_url."
  type        = string
  default     = "mock"
}

variable "ollama_base_url" {
  description = "URL of an Ollama server reachable from the tasks (only when llm_provider = ollama)."
  type        = string
  default     = ""
}

variable "db_instance_class" {
  type    = string
  default = "db.t4g.micro"
}

variable "log_retention_days" {
  type    = number
  default = 7
}

# --- Cost guardrails ---

variable "monthly_budget_usd" {
  description = "Create an AWS Budget alert at this monthly amount (0 disables). Only on target = aws."
  type        = number
  default     = 20
}

variable "budget_alert_email" {
  description = "Where budget alerts are sent (required for the budget to be created)."
  type        = string
  default     = ""
}
