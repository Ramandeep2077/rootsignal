# Apply against LocalStack (free tier): network, secrets, S3 and IAM are emulated.
# ECR, RDS, ECS and ELBv2 are paid LocalStack features, so those modules are planned (validated) but not applied.
target              = "localstack"
localstack_endpoint = "http://localhost:4566"
deploy_registry     = false
deploy_database     = false
deploy_compute      = false
