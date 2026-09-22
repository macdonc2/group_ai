"""LLM judges scoring against 1-5 anchored rubrics.

Two interchangeable judges share one interface:
- OpenAIJudge: OpenAI Responses API (EVAL_JUDGE_MODEL, default gpt-6-astra).
- JevJudge: any OpenAI-compatible endpoint (JEV_BASE_URL / JEV_MODEL / JEV_API_KEY).
  It uses prompted JSON output rather than tool calls, since compatible servers
  vary in function-calling support.

Judge LLM calls are tagged `llm_role("judge")` so their tokens and cost are
reported separately from the system under test.
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from string import Template
from typing import Any, Protocol

import yaml
from pydantic import BaseModel, Field

from agent_system.adapters.outbound.telemetry import llm_role

logger = logging.getLogger(__name__)

RUBRICS_DIR = Path(__file__).parent / "rubrics"

JUDGE_SYSTEM_PROMPT = """You are a strict, calibrated evaluator. Score each dimension on a 1-5 integer scale
using the anchors given (1, 3 and 5 are anchored; 2 and 4 sit between them). Base every score on the
evidence shown, quote or point at that evidence, and do not reward length or confident tone.
If the material needed to judge a dimension is absent, score it 3 and say why."""


# ---------------------------------------------------------------------------
# Rubrics
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Rubric:
    name: str
    title: str
    applies_to: str
    dimensions: dict[str, dict[int, str]]
    template: str

    def render(self, **context: Any) -> str:
        body = Template(self.template).safe_substitute({k: (v if v not in (None, "") else "(none)") for k, v in context.items()})
        anchors = "\n".join(
            f"- {dim}:\n" + "\n".join(f"    {lvl} = {txt}" for lvl, txt in sorted(levels.items()))
            for dim, levels in self.dimensions.items()
        )
        return (
            f"{body.strip()}\n\nRUBRIC — score every dimension below (1-5):\n{anchors}\n\n"
            f"Return one entry per dimension, using exactly these names: {', '.join(self.dimensions)}."
        )


@lru_cache
def load_rubric(name: str) -> Rubric:
    text = (RUBRICS_DIR / f"{name}.md").read_text()
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.S)
    if not m:
        raise ValueError(f"Rubric {name} is missing YAML front matter")
    meta = yaml.safe_load(m.group(1))
    dims = {d: {int(k): str(v) for k, v in levels.items()} for d, levels in meta["dimensions"].items()}
    return Rubric(meta["name"], meta.get("title", name), meta.get("applies_to", "agent"), dims, m.group(2))


def list_rubrics() -> list[str]:
    return sorted(p.stem for p in RUBRICS_DIR.glob("*.md"))


# ---------------------------------------------------------------------------
# Output schema
# ---------------------------------------------------------------------------


class DimensionScore(BaseModel):
    dimension: str
    score: int = Field(ge=1, le=5)
    rationale: str = Field(description="One or two sentences citing the evidence")


class Judgement(BaseModel):
    scores: list[DimensionScore]
    summary: str = Field(description="One-sentence overall verdict")


def normalize(rubric: Rubric, j: Judgement) -> dict[str, Any]:
    by_dim = {s.dimension.strip().lower(): s for s in j.scores}
    dims = {}
    for d in rubric.dimensions:
        s = by_dim.get(d)
        dims[d] = {"score": s.score, "rationale": s.rationale} if s else {"score": None, "rationale": "not scored"}
    vals = [v["score"] for v in dims.values() if v["score"] is not None]
    return {"dimensions": dims, "mean": round(sum(vals) / len(vals), 3) if vals else None, "summary": j.summary}


# ---------------------------------------------------------------------------
# Judges
# ---------------------------------------------------------------------------


class JudgePort(Protocol):
    name: str

    async def score(self, rubric: Rubric, context: dict[str, Any]) -> dict[str, Any]: ...


class _AgentJudge:
    name = "judge"

    def __init__(self, model: Any, prompted: bool = False, retries: int = 2) -> None:
        from pydantic_ai import Agent, PromptedOutput

        output_type: Any = PromptedOutput(Judgement) if prompted else Judgement
        self._agent = Agent(model, name=f"judge:{self.name}", output_type=output_type,
                            system_prompt=JUDGE_SYSTEM_PROMPT, retries=retries)
        self._sem = asyncio.Semaphore(4)

    async def score(self, rubric: Rubric, context: dict[str, Any]) -> dict[str, Any]:
        prompt = rubric.render(**context)
        async with self._sem:
            with llm_role("judge"):
                result = await self._agent.run(prompt)
        return normalize(rubric, result.output)


class OpenAIJudge(_AgentJudge):
    name = "openai"

    def __init__(self, model: str, api_key: str) -> None:
        from agent_system.adapters.outbound.llm.agents import _get_model

        self.model_name = model
        super().__init__(_get_model(model, api_key))


class JevJudge(_AgentJudge):
    name = "jev"

    def __init__(self, base_url: str, model: str, api_key: str | None) -> None:
        from pydantic_ai.models.openai import OpenAIChatModel
        from pydantic_ai.providers.openai import OpenAIProvider

        self.model_name = model
        provider = OpenAIProvider(base_url=base_url, api_key=api_key or "not-needed")
        super().__init__(OpenAIChatModel(model, provider=provider), prompted=True)


def build_judges(which: str, api_key: str | None) -> list[JudgePort]:
    """`which` is openai | jev | both | none."""
    from agent_system.composition_root.config import get_settings

    s = get_settings()
    judges: list[JudgePort] = []
    if which in ("openai", "both"):
        if not api_key:
            raise ValueError("OpenAI judge needs EVAL_OPENAI_API_KEY (or OPENAI_API_KEY)")
        judges.append(OpenAIJudge(s.eval_judge_model, api_key))
    if which in ("jev", "both"):
        if not s.jev_base_url:
            raise ValueError("Jev judge needs JEV_BASE_URL (OpenAI-compatible endpoint) and JEV_MODEL")
        judges.append(JevJudge(s.jev_base_url, s.jev_model, s.jev_api_key))
    return judges


# ---------------------------------------------------------------------------
# Inter-judge agreement
# ---------------------------------------------------------------------------


def agreement(pairs: list[tuple[int, int]]) -> dict[str, Any]:
    """Exact / within-1 agreement and quadratic-weighted Cohen's kappa for 1-5 scores."""
    pairs = [(a, b) for a, b in pairs if a is not None and b is not None]
    n = len(pairs)
    if n == 0:
        return {"n": 0, "exact": None, "within_1": None, "weighted_kappa": None}
    exact = sum(a == b for a, b in pairs) / n
    within = sum(abs(a - b) <= 1 for a, b in pairs) / n
    cats = range(1, 6)
    pa = {c: sum(a == c for a, _ in pairs) / n for c in cats}
    pb = {c: sum(b == c for _, b in pairs) / n for c in cats}
    w = lambda i, j: ((i - j) ** 2) / 16  # noqa: E731 - (k-1)^2 with k=5
    observed = sum(w(a, b) for a, b in pairs) / n
    expected = sum(w(i, j) * pa[i] * pb[j] for i in cats for j in cats)
    kappa = 1 - observed / expected if expected else 1.0
    return {"n": n, "exact": round(exact, 3), "within_1": round(within, 3), "weighted_kappa": round(kappa, 3)}
