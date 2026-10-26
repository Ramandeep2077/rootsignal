# Secrets (generated, stored in Secrets Manager, injected into tasks), an S3 bucket for artefacts
# (eval results, exports), and an optional small single-AZ RDS PostgreSQL instance with pgvector.

variable "name" { type = string }
variable "subnet_ids" { type = list(string) }
variable "security_group_id" { type = string }
variable "deploy_database" { type = bool }
variable "instance_class" { type = string }

resource "random_password" "db" {
  length  = 32
  special = false
}

resource "random_password" "internal_token" {
  length  = 40
  special = false
}

resource "aws_secretsmanager_secret" "db_password" {
  name                    = "${var.name}/db-password"
  recovery_window_in_days = 0 # demo: allow immediate re-creation after teardown
}

resource "aws_secretsmanager_secret_version" "db_password" {
  secret_id     = aws_secretsmanager_secret.db_password.id
  secret_string = random_password.db.result
}

resource "aws_secretsmanager_secret" "internal_token" {
  name                    = "${var.name}/internal-api-token"
  recovery_window_in_days = 0
}

resource "aws_secretsmanager_secret_version" "internal_token" {
  secret_id     = aws_secretsmanager_secret.internal_token.id
  secret_string = random_password.internal_token.result
}

resource "aws_s3_bucket" "artifacts" {
  bucket_prefix = "${var.name}-artifacts-"
  force_destroy = true # teardown must never be blocked by leftover objects
}

resource "aws_s3_bucket_public_access_block" "artifacts" {
  bucket                  = aws_s3_bucket.artifacts.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "artifacts" {
  bucket = aws_s3_bucket.artifacts.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "artifacts" {
  bucket = aws_s3_bucket.artifacts.id
  rule {
    id     = "expire-old-artifacts"
    status = "Enabled"
    filter {}
    expiration {
      days = 30
    }
  }
}

resource "aws_db_subnet_group" "this" {
  count      = var.deploy_database ? 1 : 0
  name       = var.name
  subnet_ids = var.subnet_ids
}

resource "aws_db_instance" "this" {
  count                   = var.deploy_database ? 1 : 0
  identifier              = var.name
  engine                  = "postgres"
  engine_version          = "17"
  instance_class          = var.instance_class
  allocated_storage       = 20
  storage_type            = "gp3"
  storage_encrypted       = true
  db_name                 = "oncall"
  username                = "oncall"
  password                = random_password.db.result
  db_subnet_group_name    = aws_db_subnet_group.this[0].name
  vpc_security_group_ids  = [var.security_group_id]
  publicly_accessible     = false
  multi_az                = false
  backup_retention_period = 1
  deletion_protection     = false
  skip_final_snapshot     = true # demo database: teardown leaves nothing billable behind
  apply_immediately       = true
}

output "db_host" { value = var.deploy_database ? aws_db_instance.this[0].address : "" }
output "db_password_secret_arn" { value = aws_secretsmanager_secret.db_password.arn }
output "internal_token_secret_arn" { value = aws_secretsmanager_secret.internal_token.arn }
output "artifacts_bucket" { value = aws_s3_bucket.artifacts.bucket }
