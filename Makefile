# oncall-copilot task runner. Works on Linux/macOS (sh) and Windows (cmd/PowerShell via GNU make).
# Recipes stick to `cmd1 && cmd2`, which both shells understand.

ifeq ($(OS),Windows_NT)
  MVNW := mvnw.cmd
else
  MVNW := ./mvnw
endif

COMPOSE := docker compose
APP     := --profile app
OBS     := --profile observability
SCENARIO ?= db_pool_exhaustion
RUNS    ?= 3
TRIAGE_MODEL ?= qwen2.5:1.5b
RCA_MODEL ?= qwen2.5:7b

.DEFAULT_GOAL := help
.PHONY: help env infra up up-obs down clean logs ps models test test-java test-python test-dashboard \
        lint sim sim-all eval eval-report tf-validate aws-local tf-plan tf-apply-local tf-destroy-local \n        aws-deploy aws-destroy

help: ## Show available targets
	@echo "infra       start postgres + redpanda only"
	@echo "up          build and start the full stack (needs Ollama running on the host)"
	@echo "up-obs      full stack + jaeger + phoenix tracing"
	@echo "down        stop everything (keeps data)    | clean  stop and delete volumes"
	@echo "logs / ps   follow logs / list containers"
	@echo "models      pull the local Ollama models"
	@echo "test        run every test suite              | lint   run all linters"
	@echo "sim         run one scenario (SCENARIO=...)   | sim-all  run every scenario"
	@echo "eval        run the evaluation suite (PROFILES=$(PROFILES))"
	@echo "tf-plan     terraform plan (full AWS stack) against LocalStack   | tf-apply-local  apply free-tier subset"
	@echo "aws-deploy  build, push and deploy to real AWS                  | aws-destroy     tear it all down"

env: ## Create .env from the example if missing
	uv run python -c "import os,shutil; os.path.exists('.env') or shutil.copy('.env.example','.env')"

infra: env
	$(COMPOSE) up -d --wait postgres redpanda
	$(COMPOSE) up redpanda-init

up: env
	$(COMPOSE) $(APP) up -d --build --wait

up-obs: export OTEL_TRACES_EXPORTER = otlp
up-obs: export ONCALL_TRACING_EXPORT = true
up-obs: env
	$(COMPOSE) $(APP) $(OBS) up -d --build --wait

down:
	$(COMPOSE) $(APP) $(OBS) --profile tools --profile aws down

clean:
	$(COMPOSE) $(APP) $(OBS) --profile tools --profile aws down -v

logs:
	$(COMPOSE) $(APP) $(OBS) logs -f --tail=100

ps:
	$(COMPOSE) $(APP) $(OBS) ps

models:
	ollama pull $(TRIAGE_MODEL) && ollama pull $(RCA_MODEL)

test: test-python test-java test-dashboard

test-python:
	uv run pytest common simulator mcp-servers agent-service evals

test-java:
	cd alert-service && $(MVNW) -B verify

test-dashboard:
	cd dashboard && npm run lint && npm test --if-present

lint:
	uv run ruff check . && uv run ruff format --check .
	cd dashboard && npm run lint

sim:
	uv run python simulator/run.py --scenario $(SCENARIO)

sim-all:
	uv run python simulator/run.py --all

PROFILES ?= routed=3,heuristic=2,small_only=2

# Stops the dockerised agent (the harness runs its own, per model profile), evaluates, then restarts it.
eval:
	$(COMPOSE) stop agent-service
	uv run python -m oncall_evals.run --profiles $(PROFILES) --runs $(RUNS)
	$(COMPOSE) $(APP) start agent-service

eval-report:
	uv run python -m oncall_evals.run --report-only

TF := cd infra/terraform && terraform

tf-validate:
	$(TF) fmt -check -recursive && terraform init -input=false -backend=false && terraform validate

# Plan the FULL stack (all modules) and apply the free-tier subset against LocalStack: `make aws-local` first.
aws-local:
	$(COMPOSE) --profile aws up -d --wait localstack

tf-plan:
	$(TF) init -input=false && terraform plan -input=false -var target=localstack

tf-apply-local:
	$(TF) init -input=false && terraform apply -input=false -auto-approve -var-file=localstack.tfvars

tf-destroy-local:
	$(TF) destroy -input=false -auto-approve -var-file=localstack.tfvars

# Real AWS (needs credentials + infra/terraform/aws.tfvars). Always pair with aws-destroy.
aws-deploy:
	bash infra/scripts/deploy-aws.sh

aws-destroy:
	bash infra/scripts/teardown-aws.sh
