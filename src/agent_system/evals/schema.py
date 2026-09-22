"""Eval dataset schema.

A suite is a YAML file in `evals/datasets/`. Each case seeds a throwaway user
with known memories, plays one or more user turns through the real FSM, and
states what should happen. Every `expect` field is optional; scorers only
score what a case asserts.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field

DATASETS_DIR = Path(__file__).parent / "datasets"


class SeedPerson(BaseModel):
    name: str
    relationship_type: str | None = None
    aliases: list[str] = Field(default_factory=list)
    context_notes: str | None = None


class SeedPet(BaseModel):
    name: str
    species: str | None = None
    breed: str | None = None
    aliases: list[str] = Field(default_factory=list)
    personality: list[str] = Field(default_factory=list)
    food_preferences: list[str] = Field(default_factory=list)


class SeedLocation(BaseModel):
    name: str
    location_type: str | None = None
    city: str | None = None
    neighborhood: str | None = None


class SeedPreference(BaseModel):
    category: str
    value: str
    sentiment: float = 0.8


class SeedMessage(BaseModel):
    """A past message, stored as a MessageEmbedding in an earlier conversation."""

    role: Literal["user", "assistant"] = "user"
    content: str
    days_ago: int = 7


class SeedLink(BaseModel):
    source_type: str
    source_name: str
    relationship: str
    target_type: str
    target_name: str


class Seed(BaseModel):
    people: list[SeedPerson] = Field(default_factory=list)
    pets: list[SeedPet] = Field(default_factory=list)
    locations: list[SeedLocation] = Field(default_factory=list)
    preferences: list[SeedPreference] = Field(default_factory=list)
    messages: list[SeedMessage] = Field(default_factory=list)
    links: list[SeedLink] = Field(default_factory=list)
    auto_plan: bool = True


class ExpectedEntity(BaseModel):
    """Expected knowledge-graph state after the case runs."""

    type: Literal["person", "pet", "location"]
    name: str
    aliases: list[str] = Field(default_factory=list)  # each must resolve to `name`
    relationship_type: str | None = None
    species: str | None = None


class Expect(BaseModel):
    intent: str | list[str] | None = None  # one or any-of
    route: list[str] | None = None  # node names that must appear, in order (subsequence)
    route_exact: bool = False
    forbid_nodes: list[str] = Field(default_factory=list)
    tool: str | list[str] | None = None  # one or any-of; "none" = no tool
    tool_args: dict[str, Any] = Field(default_factory=dict)  # substring match per key (case-insensitive)
    must_recall: list[str] = Field(default_factory=list)  # facts that must appear in retrieved context
    must_mention: list[str] = Field(default_factory=list)  # substrings the response must contain (any case)
    must_not_mention: list[str] = Field(default_factory=list)  # hallucination / leakage guards
    entities: list[ExpectedEntity] = Field(default_factory=list)
    forbid_entities: list[str] = Field(default_factory=list)  # names that must NOT exist afterwards
    no_duplicate_entities: bool = True
    answer_criteria: str | None = None  # free text for the judge
    max_latency_ms: float | None = None


class EvalCase(BaseModel):
    id: str
    description: str = ""
    tags: list[str] = Field(default_factory=list)
    seed: Seed = Field(default_factory=Seed)
    turns: list[str]  # user messages, played in one conversation
    expect: Expect = Field(default_factory=Expect)  # applies to the LAST turn (entities: final KG state)
    rubrics: list[str] | None = None  # override the suite's rubrics


class ResearchCase(BaseModel):
    id: str
    question: str
    depth: int = 1
    min_sources: int = 5
    expect_lanes: list[str] = Field(default_factory=lambda: ["academic", "practical", "empirical"])
    answer_criteria: str | None = None


class Suite(BaseModel):
    name: str
    description: str = ""
    kind: Literal["agent", "research"] = "agent"
    rubrics: list[str] = Field(default_factory=list)
    pass_threshold: float = 3.5  # mean judge score (1-5) needed to pass, when judged
    cases: list[EvalCase] = Field(default_factory=list)
    research_cases: list[ResearchCase] = Field(default_factory=list)


def list_suites() -> list[str]:
    return sorted(p.stem for p in DATASETS_DIR.glob("*.yaml"))


def load_suite(name: str) -> Suite:
    path = DATASETS_DIR / f"{name}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"No eval suite '{name}'. Available: {', '.join(list_suites())}")
    raw = yaml.safe_load(path.read_text())
    raw.setdefault("name", name)
    if raw.get("kind") == "research":
        raw["research_cases"] = raw.pop("cases", [])
    return Suite.model_validate(raw)
