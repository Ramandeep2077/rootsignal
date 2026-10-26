locals {
  localstack = var.target == "localstack"
}

provider "aws" {
  region = var.region

  # LocalStack accepts any credentials; real AWS uses the normal credential chain (env, profile, SSO).
  access_key                  = local.localstack ? "test" : null
  secret_key                  = local.localstack ? "test" : null
  skip_credentials_validation = local.localstack
  skip_metadata_api_check     = local.localstack
  skip_requesting_account_id  = local.localstack
  s3_use_path_style           = local.localstack

  dynamic "endpoints" {
    for_each = local.localstack ? [var.localstack_endpoint] : []
    content {
      cloudwatchlogs   = endpoints.value
      ec2              = endpoints.value
      ecr              = endpoints.value
      ecs              = endpoints.value
      elbv2            = endpoints.value
      iam              = endpoints.value
      rds              = endpoints.value
      s3               = endpoints.value
      secretsmanager   = endpoints.value
      servicediscovery = endpoints.value
      sts              = endpoints.value
      budgets          = endpoints.value
    }
  }

  default_tags {
    tags = {
      Project     = var.project
      Environment = var.environment
      ManagedBy   = "terraform"
    }
  }
}
