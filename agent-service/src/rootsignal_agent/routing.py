"""Model routing: resolves which model (and fallbacks/limits) each agent uses, from config/models.yaml + env."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from rootsignal_agent.settings import AgentSettings

AGENTS = ("triage", "investigator", "remediation", "judge")
HEURISTIC = "heuristic"


@dataclass(frozen=True)
class AgentRoute:
    agent: str
    model: str
    fallbacks: tuple[str, ...]
    timeout_seconds: float
    max_retries: int
    temperature: float
    max_tokens: int
    num_ctx: int
    options: dict[str, Any] = field(default_factory=dict)

    @property
    def chain(self) -> tuple[str, ...]:
        """Models to try in order; the heuristic is always the final fallback."""
        models = (self.model, *self.fallbacks)
        return models if HEURISTIC in models else (*models, HEURISTIC)


@dataclass(frozen=True)
class Routing:
    profile: str
    routes: dict[str, AgentRoute]
    pricing: dict[str, dict[str, float]]

    def __getitem__(self, agent: str) -> AgentRoute:
        return self.routes[agent]

    def describe(self) -> dict[str, Any]:
        return {
            "profile": self.profile,
            **{a: {"model": r.model, "fallbacks": list(r.fallbacks)} for a, r in self.routes.items()},
        }


def load_routing(
    settings: AgentSettings, profile: str | None = None, config_path: Path | None = None
) -> Routing:
    config = yaml.safe_load((config_path or settings.models_config).read_text(encoding="utf-8"))
    if settings.llm_provider == "mock":
        chosen = HEURISTIC
    else:
        chosen = profile or settings.model_profile or config["profile"]
    if chosen not in config["profiles"]:
        raise ValueError(f"Unknown model profile '{chosen}'. Available: {', '.join(config['profiles'])}")
    defaults = config.get("defaults", {})
    overrides = {
        "triage": settings.triage_model,
        "investigator": settings.investigator_model,
        "remediation": settings.remediation_model,
        "judge": settings.judge_model,
    }
    routes = {}
    for agent in AGENTS:
        profile_entry = config["profiles"][chosen][agent]
        agent_cfg = config.get("agents", {}).get(agent, {})
        # Env overrides only apply to real-model profiles; mock/heuristic must stay deterministic.
        model = overrides[agent] if overrides[agent] and chosen != HEURISTIC else profile_entry["model"]
        routes[agent] = AgentRoute(
            agent=agent,
            model=model,
            fallbacks=tuple(profile_entry.get("fallbacks", [])),
            timeout_seconds=float(
                settings.llm_timeout_seconds
                or agent_cfg.get("timeout_seconds")
                or defaults.get("timeout_seconds", 240)
            ),
            max_retries=int(
                settings.llm_max_retries
                if settings.llm_max_retries is not None
                else agent_cfg.get("max_retries", defaults.get("max_retries", 2))
            ),
            temperature=float(agent_cfg.get("temperature", defaults.get("temperature", 0.1))),
            max_tokens=int(agent_cfg.get("max_tokens", 400)),
            num_ctx=int(agent_cfg.get("num_ctx", defaults.get("num_ctx", 8192))),
            options={
                k: v
                for k, v in agent_cfg.items()
                if k not in {"temperature", "max_tokens", "num_ctx", "timeout_seconds", "max_retries"}
            },
        )
    return Routing(profile=chosen, routes=routes, pricing=config.get("pricing", {}))
