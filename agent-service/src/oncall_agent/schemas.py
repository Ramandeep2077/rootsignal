"""Structured outputs of each agent (Pydantic). The JSON schemas also drive Ollama's constrained decoding."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from oncall_common.taxonomy import RiskLevel, RootCauseCategory

Severity = Literal["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"]


class TriageSummary(BaseModel):
    """Output of the triage agent for a group of alerts."""

    title: str = Field(max_length=140, description="Short incident title naming the main symptom and service")
    severity: Severity
    affected_services: list[str] = Field(min_length=1, max_length=8)
    summary: str = Field(max_length=600, description="Two sentences: what is failing and where")


class Evidence(BaseModel):
    source: Literal["logs", "metrics", "deploys", "alerts", "runbooks"]
    finding: str = Field(max_length=300, description="A concrete observation, quoting values or log text")


class RootCauseHypothesis(BaseModel):
    """Output of the investigator agent."""

    category: RootCauseCategory
    root_cause_service: str = Field(description="Service or component where the problem originates")
    hypothesis: str = Field(max_length=600, description="What went wrong and why the symptoms follow from it")
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: list[Evidence] = Field(min_length=1, max_length=6)


class ProposedAction(BaseModel):
    """Output of the remediation agent. ``action`` is a free string on purpose: the guardrails validate it."""

    action: str = Field(description="One of the allowed action names")
    target: str = Field(description="Service or component the action applies to")
    risk_level: RiskLevel
    steps: list[str] = Field(min_length=1, max_length=8)
    rollback_plan: str = Field(max_length=500)
    rationale: str = Field(max_length=500)
    runbook_id: str | None = None
    dry_run: bool = True


class GuardrailResult(BaseModel):
    allowed: bool
    violations: list[str] = Field(default_factory=list)
    original_action: str | None = None
    requires_approval: bool = True
