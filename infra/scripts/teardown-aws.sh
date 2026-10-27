#!/usr/bin/env bash
# Destroy everything this project created in AWS, then double-check nothing billable is left behind.
set -euo pipefail
cd "$(dirname "$0")/../terraform"
terraform init -input=false >/dev/null
terraform destroy -input=false -auto-approve -var-file=aws.tfvars

REGION="$(awk -F'"' '/^region/ {print $2}' aws.tfvars)"; REGION="${REGION:-us-east-1}"
echo "Checking for leftover tagged resources (Project=rootsignal) in $REGION..."
LEFT="$(aws resourcegroupstaggingapi get-resources --region "$REGION" \
  --tag-filters Key=Project,Values=rootsignal --query 'ResourceTagMappingList[].ResourceARN' --output text)"
if [ -n "$LEFT" ]; then
  echo "Still present (tags can lag a few minutes after deletion):"; echo "$LEFT" | tr '\t' '\n'
else
  echo "Nothing left. You are not paying for idle resources."
fi
