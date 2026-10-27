#!/usr/bin/env bash
# Build the images, push them to ECR and apply the full stack to a real AWS account.
# Prereqs: AWS credentials (aws sts get-caller-identity works), Docker, Terraform, infra/terraform/aws.tfvars.
set -euo pipefail
cd "$(dirname "$0")/../terraform"

TAG="${IMAGE_TAG:-$(git rev-parse --short HEAD)}"
REGION="$(awk -F'"' '/^region/ {print $2}' aws.tfvars)"; REGION="${REGION:-us-east-1}"

terraform init -input=false
# 1) Registry first, so there is somewhere to push.
terraform apply -input=false -auto-approve -var-file=aws.tfvars -var "image_tag=$TAG" -target=module.registry

ACCOUNT="$(aws sts get-caller-identity --query Account --output text)"
REGISTRY="$ACCOUNT.dkr.ecr.$REGION.amazonaws.com"
aws ecr get-login-password --region "$REGION" | docker login --username AWS --password-stdin "$REGISTRY"

ROOT="$(git rev-parse --show-toplevel)"
build() { docker build --platform linux/amd64 -t "$REGISTRY/rootsignal/$1:$TAG" "${@:2}" && docker push "$REGISTRY/rootsignal/$1:$TAG"; }
build alert-service "$ROOT/alert-service"
build agent-service -f "$ROOT/agent-service/Dockerfile" "$ROOT"
build mcp-servers -f "$ROOT/mcp-servers/Dockerfile" "$ROOT"
# Same-origin API (the ALB routes /api/* to the alert service), so the dashboard is built with an empty base URL.
build dashboard --build-arg NEXT_PUBLIC_API_URL= "$ROOT/dashboard"

# 2) Everything else.
terraform apply -input=false -auto-approve -var-file=aws.tfvars -var "image_tag=$TAG"
echo "Deployed. Dashboard: $(terraform output -raw url)"
echo "Tear down when finished: make aws-destroy"
