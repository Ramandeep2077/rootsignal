"""Agent service configuration (environment / .env)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from oncall_common.settings import BaseServiceSettings

CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"


class AgentSettings(BaseServiceSettings):
    kafka_bootstrap_servers: str = "localhost:19092"
    alerts_topic: str = "alerts.raw"
    decisions_topic: str = "incidents.decisions"
    consumer_group: str = "agent-service"

    # LLM
    llm_provider: str = "ollama"  # "ollama" or "mock" (mock forces the heuristic profile)
    ollama_base_url: str = "http://localhost:11434"
    model_profile: str | None = None
    models_config: Path = CONFIG_DIR / "models.yaml"
    triage_model: str | None = None
    investigator_model: str | None = None
    remediation_model: str | None = None
    judge_model: str | None = None
    llm_timeout_seconds: float | None = None
    llm_max_retries: int | None = None

    # Triage grouping
    triage_window_seconds: float = 20.0  # max time a group stays open
    triage_quiet_seconds: float = 6.0  # close a group after this long with no new member
    similarity_threshold: float = 0.55
    attach_window_minutes: float = 10.0  # late alerts join an existing incident within this window

    # Agents & guardrails
    max_concurrent_investigations: int = 1  # CPU inference: one at a time is fastest overall
    remediation_dry_run: bool = True
    min_confidence_for_action: float = 0.5

    # MCP tool servers
    logs_mcp_url: str = "http://localhost:8101/mcp"
    metrics_mcp_url: str = "http://localhost:8102/mcp"
    deploys_mcp_url: str = "http://localhost:8103/mcp"
    runbooks_mcp_url: str = "http://localhost:8104/mcp"

    # Notifications
    slack_webhook_url: str | None = None
    smtp_host: str | None = None
    smtp_port: int = 1025
    notify_email_to: str = "oncall@example.test"
    notify_email_from: str = "copilot@example.test"
    dashboard_url: str = "http://localhost:3000"


@lru_cache
def get_settings() -> AgentSettings:
    return AgentSettings()
