# ECS Fargate cluster running the whole system, mirroring docker-compose:
#   redpanda, alert-service, mcp-servers, agent-service, mock-slack, dashboard
# Services find each other through Cloud Map private DNS (<service>.<namespace>). One ALB is the public
# entry point: /api/* (+ Swagger) -> alert-service, everything else -> dashboard (same origin, so no CORS).

variable "name" { type = string }
variable "region" { type = string }
variable "vpc_id" { type = string }
variable "subnet_ids" { type = list(string) }
variable "alb_security_group_id" { type = string }
variable "services_security_group_id" { type = string }
variable "repository_urls" { type = map(string) }
variable "image_tag" { type = string }
variable "db_host" { type = string }
variable "db_password_secret_arn" { type = string }
variable "internal_token_secret_arn" { type = string }
variable "use_fargate_spot" { type = bool }
variable "llm_provider" { type = string }
variable "ollama_base_url" { type = string }
variable "log_retention_days" { type = number }

locals {
  namespace = "${var.name}.internal"
  dns       = { for s in ["redpanda", "alert-service", "mcp-servers", "agent-service", "mock-slack"] : s => "${s}.${local.namespace}" }
  db_env = {
    POSTGRES_HOST = var.db_host
    POSTGRES_PORT = "5432"
    POSTGRES_DB   = "rootsignal"
    POSTGRES_USER = "rootsignal"
  }
  mcp_urls = { for i, s in ["LOGS", "METRICS", "DEPLOYS", "RUNBOOKS"] : "${s}_MCP_URL" => "http://${local.dns["mcp-servers"]}:${8101 + i}/mcp" }

  services = {
    redpanda = {
      image  = "docker.redpanda.com/redpandadata/redpanda:v26.2.6"
      cpu    = 512
      memory = 1024
      port   = 9092
      command = ["redpanda", "start", "--mode=dev-container", "--smp=1", "--memory=768M", "--overprovisioned",
      "--kafka-addr=0.0.0.0:9092", "--advertise-kafka-addr=${local.dns["redpanda"]}:9092"]
      environment = {}
      secrets     = {}
      public      = null
    }
    alert-service = {
      image   = "${var.repository_urls["alert-service"]}:${var.image_tag}"
      cpu     = 512
      memory  = 1024
      port    = 8080
      command = null
      environment = {
        SPRING_DATASOURCE_URL           = "jdbc:postgresql://${var.db_host}:5432/rootsignal"
        SPRING_DATASOURCE_USERNAME      = "rootsignal"
        SPRING_KAFKA_BOOTSTRAP_SERVERS  = "${local.dns["redpanda"]}:9092"
        ROOTSIGNAL_CORS_ALLOWED_ORIGINS = "http://${aws_lb.this.dns_name}"
      }
      secrets = {
        SPRING_DATASOURCE_PASSWORD    = var.db_password_secret_arn
        ROOTSIGNAL_INTERNAL_API_TOKEN = var.internal_token_secret_arn
      }
      public = { health = "/actuator/health", paths = ["/api/*", "/swagger-ui*", "/v3/api-docs*"], priority = 10 }
    }
    mcp-servers = {
      image       = "${var.repository_urls["mcp-servers"]}:${var.image_tag}"
      cpu         = 512
      memory      = 2048
      port        = 8104
      command     = null
      environment = merge(local.db_env, { EMBEDDINGS_PROVIDER = "local" })
      secrets     = { POSTGRES_PASSWORD = var.db_password_secret_arn }
      public      = null
    }
    agent-service = {
      image   = "${var.repository_urls["agent-service"]}:${var.image_tag}"
      cpu     = 512
      memory  = 2048
      port    = 8000
      command = null
      environment = merge(local.db_env, local.mcp_urls, {
        KAFKA_BOOTSTRAP_SERVERS = "${local.dns["redpanda"]}:9092"
        ALERT_SERVICE_URL       = "http://${local.dns["alert-service"]}:8080"
        LLM_PROVIDER            = var.llm_provider
        OLLAMA_BASE_URL         = var.ollama_base_url
        EMBEDDINGS_PROVIDER     = "local"
        SLACK_WEBHOOK_URL       = "http://${local.dns["mock-slack"]}:8090/webhook"
        DASHBOARD_URL           = "http://${aws_lb.this.dns_name}"
        REMEDIATION_DRY_RUN     = "true"
      })
      secrets = {
        POSTGRES_PASSWORD  = var.db_password_secret_arn
        INTERNAL_API_TOKEN = var.internal_token_secret_arn
      }
      public = null
    }
    mock-slack = {
      image       = "${var.repository_urls["agent-service"]}:${var.image_tag}"
      cpu         = 256
      memory      = 512
      port        = 8090
      command     = ["python", "-m", "rootsignal_agent.notifications.mock_slack"]
      environment = {}
      secrets     = {}
      public      = null
    }
    dashboard = {
      image       = "${var.repository_urls["dashboard"]}:${var.image_tag}"
      cpu         = 256
      memory      = 512
      port        = 3000
      command     = null
      environment = {}
      secrets     = {}
      public      = { health = "/incidents", paths = [], priority = 0 }
    }
  }
}

data "aws_iam_policy_document" "assume_ecs_tasks" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "execution" {
  name               = "${var.name}-task-execution"
  assume_role_policy = data.aws_iam_policy_document.assume_ecs_tasks.json
}

resource "aws_iam_role_policy_attachment" "execution" {
  role       = aws_iam_role.execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

# Least privilege: tasks may read exactly the two secrets they need, nothing else.
data "aws_iam_policy_document" "read_secrets" {
  statement {
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [var.db_password_secret_arn, var.internal_token_secret_arn]
  }
}

resource "aws_iam_role_policy" "read_secrets" {
  name   = "read-secrets"
  role   = aws_iam_role.execution.id
  policy = data.aws_iam_policy_document.read_secrets.json
}

resource "aws_ecs_cluster" "this" {
  name = var.name
  setting {
    name  = "containerInsights"
    value = "disabled" # extra cost; CloudWatch logs + OpenTelemetry cover the demo
  }
}

resource "aws_ecs_cluster_capacity_providers" "this" {
  cluster_name       = aws_ecs_cluster.this.name
  capacity_providers = ["FARGATE", "FARGATE_SPOT"]
}

resource "aws_cloudwatch_log_group" "service" {
  for_each          = local.services
  name              = "/ecs/${var.name}/${each.key}"
  retention_in_days = var.log_retention_days
}

resource "aws_service_discovery_private_dns_namespace" "this" {
  name = local.namespace
  vpc  = var.vpc_id
}

resource "aws_service_discovery_service" "this" {
  for_each = local.services
  name     = each.key
  dns_config {
    namespace_id   = aws_service_discovery_private_dns_namespace.this.id
    routing_policy = "MULTIVALUE"
    dns_records {
      type = "A"
      ttl  = 10
    }
  }
}

resource "aws_ecs_task_definition" "this" {
  for_each                 = local.services
  family                   = "${var.name}-${each.key}"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = each.value.cpu
  memory                   = each.value.memory
  execution_role_arn       = aws_iam_role.execution.arn
  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "X86_64"
  }
  container_definitions = jsonencode([merge({
    name         = each.key
    image        = each.value.image
    essential    = true
    portMappings = [{ containerPort = each.value.port, protocol = "tcp" }]
    environment  = [for k, v in each.value.environment : { name = k, value = v }]
    secrets      = [for k, v in each.value.secrets : { name = k, valueFrom = v }]
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        awslogs-group         = aws_cloudwatch_log_group.service[each.key].name
        awslogs-region        = var.region
        awslogs-stream-prefix = each.key
      }
    }
  }, each.value.command == null ? {} : { command = each.value.command })])
}

resource "aws_lb" "this" {
  name               = substr(var.name, 0, 32)
  load_balancer_type = "application"
  security_groups    = [var.alb_security_group_id]
  subnets            = var.subnet_ids
}

resource "aws_lb_target_group" "public" {
  for_each    = { for k, s in local.services : k => s if s.public != null }
  name        = substr("${var.name}-${each.key}", 0, 32)
  port        = each.value.port
  protocol    = "HTTP"
  target_type = "ip"
  vpc_id      = var.vpc_id
  health_check {
    path                = each.value.public.health
    matcher             = "200"
    healthy_threshold   = 2
    unhealthy_threshold = 5
    interval            = 30
  }
  deregistration_delay = 10
}

resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.this.arn
  port              = 80
  protocol          = "HTTP"
  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.public["dashboard"].arn
  }
}

resource "aws_lb_listener_rule" "api" {
  listener_arn = aws_lb_listener.http.arn
  priority     = local.services["alert-service"].public.priority
  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.public["alert-service"].arn
  }
  condition {
    path_pattern {
      values = local.services["alert-service"].public.paths
    }
  }
}

resource "aws_ecs_service" "this" {
  for_each        = local.services
  name            = each.key
  cluster         = aws_ecs_cluster.this.id
  task_definition = aws_ecs_task_definition.this[each.key].arn
  desired_count   = 1

  capacity_provider_strategy {
    capacity_provider = var.use_fargate_spot ? "FARGATE_SPOT" : "FARGATE"
    weight            = 1
  }

  network_configuration {
    subnets          = var.subnet_ids
    security_groups  = [var.services_security_group_id]
    assign_public_ip = true # no NAT gateway; outbound for image pulls / model downloads
  }

  service_registries {
    registry_arn = aws_service_discovery_service.this[each.key].arn
  }

  dynamic "load_balancer" {
    for_each = each.value.public == null ? [] : [each.value]
    content {
      target_group_arn = aws_lb_target_group.public[each.key].arn
      container_name   = each.key
      container_port   = each.value.port
    }
  }

  deployment_minimum_healthy_percent = 0 # single-task demo services: allow replace-in-place
  deployment_maximum_percent         = 100
  wait_for_steady_state              = false
  depends_on                         = [aws_lb_listener.http]
}

output "url" { value = "http://${aws_lb.this.dns_name}" }
output "cluster_name" { value = aws_ecs_cluster.this.name }
