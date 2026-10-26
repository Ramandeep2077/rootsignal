locals {
  name   = "${var.project}-${var.environment}"
  images = ["alert-service", "agent-service", "mcp-servers", "dashboard"]
}

module "network" {
  source        = "./modules/network"
  name          = local.name
  cidr          = var.vpc_cidr
  allowed_cidrs = var.allowed_cidrs
}

module "data" {
  source            = "./modules/data"
  name              = local.name
  subnet_ids        = module.network.public_subnet_ids
  security_group_id = module.network.database_security_group_id
  deploy_database   = var.deploy_database
  instance_class    = var.db_instance_class
}

module "registry" {
  count        = var.deploy_registry ? 1 : 0
  source       = "./modules/registry"
  name         = var.project
  repositories = local.images
}

module "services" {
  count                      = var.deploy_compute ? 1 : 0
  source                     = "./modules/services"
  name                       = local.name
  region                     = var.region
  vpc_id                     = module.network.vpc_id
  subnet_ids                 = module.network.public_subnet_ids
  alb_security_group_id      = module.network.alb_security_group_id
  services_security_group_id = module.network.services_security_group_id
  repository_urls            = module.registry[0].repository_urls
  image_tag                  = var.image_tag
  db_host                    = module.data.db_host
  db_password_secret_arn     = module.data.db_password_secret_arn
  internal_token_secret_arn  = module.data.internal_token_secret_arn
  use_fargate_spot           = var.use_fargate_spot
  llm_provider               = var.llm_provider
  ollama_base_url            = var.ollama_base_url
  log_retention_days         = var.log_retention_days
}

# Cost guardrail: e-mail when actual or forecast monthly spend crosses the limit.
resource "aws_budgets_budget" "monthly" {
  count        = var.target == "aws" && var.monthly_budget_usd > 0 && var.budget_alert_email != "" ? 1 : 0
  name         = "${local.name}-monthly"
  budget_type  = "COST"
  limit_amount = tostring(var.monthly_budget_usd)
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  cost_filter {
    name   = "TagKeyValue"
    values = ["user:Project$${var.project}"]
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 80
    threshold_type             = "PERCENTAGE"
    notification_type          = "FORECASTED"
    subscriber_email_addresses = [var.budget_alert_email]
  }
  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 100
    threshold_type             = "PERCENTAGE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = [var.budget_alert_email]
  }
}
