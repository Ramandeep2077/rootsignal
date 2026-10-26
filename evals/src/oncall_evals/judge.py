"""LLM-as-judge: grades a root-cause hypothesis against the scenario's ground-truth explanation."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from oncall_agent.llm.base import LLMError
from oncall_agent.llm.router import ModelRouter, UsageTracker

RUBRIC = """You grade root-cause analyses of production incidents against the known ground truth.
Score 1-5:
5 = same root cause and same originating component; explanation consistent with the ground truth.
4 = correct root cause and component, but some details are wrong or missing.
3 = partially correct: right area or symptom chain, but wrong mechanism OR wrong originating component.
2 = mostly wrong, but identifies a relevant symptom.
1 = wrong root cause.
Judge the substance, not the wording. Be strict: a symptom (e.g. "high error rate on checkout") is not a cause."""


class JudgeVerdict(BaseModel):
    score: int = Field(ge=1, le=5)
    correct: bool = Field(description="True if the analysis identifies the actual root cause (score >= 4)")
    rationale: str = Field(max_length=400)


async def judge(
    router: ModelRouter, ground_truth: dict[str, Any], hypothesis: dict[str, Any] | None, usage: UsageTracker
) -> JudgeVerdict | None:
    """None when there is no hypothesis to grade or the judge model is unavailable."""
    if not hypothesis or not router.uses_llm("judge"):
        return None
    evidence = "; ".join(e.get("finding", "") for e in hypothesis.get("evidence", []))[:800]
    messages = [
        {"role": "system", "content": RUBRIC},
        {
            "role": "user",
            "content": (
                f"GROUND TRUTH: category={ground_truth['category']}, root cause component="
                f"{ground_truth['root_cause_service']}. {ground_truth['summary']}\n\n"
                f"ANALYSIS TO GRADE: category={hypothesis.get('category')}, component="
                f"{hypothesis.get('root_cause_service')}, confidence={hypothesis.get('confidence')}.\n"
                f"{hypothesis.get('hypothesis', '')}\nEvidence cited: {evidence}\n\nReply with JSON."
            ),
        },
    ]
    try:
        return await router.structured("judge", messages, JudgeVerdict, usage)
    except LLMError:
        return None
